"""
セル同期API。

ローカルのスプレッド形式アプリと DB のカラムを双方向に同期する。

このモジュールは book / sheet / cell といったスプレッドシート側の概念を一切
持たない。受け取るのは CellBinding の「名称」と「値」だけで、テーブル名・
フィールド名・レコードidがクライアントから送られてくることは無い。
"""
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import BindingConfigError, CellBinding
from .utils import load_config, resolve_secret

CODE_OK = 0            # 成功
CODE_ERROR = 1         # 認証エラー / サーバーエラー
CODE_BAD_REQUEST = 2   # リクエスト不正（未登録の名称、書き込み不可、値が不正）

DIRECTIONS = ('push', 'pull')


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------

def _parse_json_body(request):
    """JSONボディを dict として返す。不正なら (None, JsonResponse)。"""
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return None, JsonResponse(
            {'code': CODE_BAD_REQUEST, 'error': 'request body must be valid UTF-8 JSON'},
            status=400,
        )
    if not isinstance(payload, dict):
        return None, JsonResponse(
            {'code': CODE_BAD_REQUEST, 'error': 'request body must be a JSON object'},
            status=400,
        )
    return payload, None


def _check_api_password(payload):
    """api_password を検証する。OKなら None、NGなら JsonResponse を返す。"""
    api_password = resolve_secret(load_config().get('api_password', ''))
    if not api_password:
        return JsonResponse(
            {'code': CODE_ERROR, 'error': 'api_password is not configured'}, status=500
        )
    if payload.get('api_password') != api_password:
        return JsonResponse(
            {'code': CODE_ERROR, 'error': 'invalid api_password'}, status=401
        )
    return None


def _validate_items(items):
    """
    items の構造を検証する。全件が構造的に正しいときだけ先へ進む。

    戻り値: (正規化した items, エラーメッセージのリスト)
    """
    errors = []
    if not isinstance(items, list):
        return [], ['items must be a list']
    if not items:
        return [], ['items must not be empty']

    normalized = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f'items[{index}]: must be an object')
            continue
        name = item.get('name')
        direction = item.get('direction')
        if not isinstance(name, str) or not name:
            errors.append(f'items[{index}]: "name" is required')
            continue
        if direction not in DIRECTIONS:
            errors.append(f'items[{index}] ({name}): "direction" must be one of {DIRECTIONS}')
            continue
        if direction == 'push' and 'value' not in item:
            errors.append(f'items[{index}] ({name}): "value" is required for push')
            continue
        normalized.append({'name': name, 'direction': direction, 'value': item.get('value')})

    return normalized, errors


def _result(item, status, **extra):
    row = {'name': item['name'], 'direction': item['direction'], 'status': status}
    row.update(extra)
    return row


def _rejected(results, message, status_code):
    return JsonResponse(
        {'code': CODE_BAD_REQUEST, 'error': message, 'results': results}, status=status_code
    )


# ---------------------------------------------------------------------------
# セル同期API
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(['POST'])
def api_cells(request):
    """
    名称で指定されたセルを同期する。

    pull を先に読み終えてから push を書く。順序を固定しないと、同一実行内で
    pull と push が混在したときに結果が非決定的になるため。
    push は全件成功か全件ロールバック。
    """
    payload, error = _parse_json_body(request)
    if error:
        return error

    auth_error = _check_api_password(payload)
    if auth_error:
        return auth_error

    items, structure_errors = _validate_items(payload.get('items'))
    if structure_errors:
        return JsonResponse(
            {'code': CODE_BAD_REQUEST, 'error': '; '.join(structure_errors)}, status=400
        )

    # --- 名称の解決（1クエリ） ---
    bindings = {b.name: b for b in CellBinding.objects.filter(
        name__in={item['name'] for item in items}
    )}

    unknown = [item['name'] for item in items if item['name'] not in bindings]
    if unknown:
        available = list(CellBinding.objects.values_list('name', flat=True))
        return JsonResponse({
            'code': CODE_BAD_REQUEST,
            'error': f"unknown name(s): {', '.join(sorted(set(unknown)))}",
            'available': available,
        }, status=400)

    # --- 書き込み権限の事前確認（1件でも不許可なら何も実行しない） ---
    forbidden = [
        item['name'] for item in items
        if item['direction'] == 'push' and not bindings[item['name']].writable
    ]
    if forbidden:
        results = [
            _result(
                item,
                'error' if item['name'] in forbidden else 'skipped',
                **({'error': f"{bindings[item['name']].label}: 書き込みが許可されていません"}
                   if item['name'] in forbidden else {}),
            )
            for item in items
        ]
        return _rejected(results, f"not writable: {', '.join(sorted(set(forbidden)))}", 403)

    # --- pull（副作用なし） ---
    try:
        pulled = {
            item['name']: bindings[item['name']].read_value()
            for item in items if item['direction'] == 'pull'
        }
    except BindingConfigError as e:
        return JsonResponse({'code': CODE_ERROR, 'error': str(e)}, status=500)

    # --- push（全件成功か全件ロールバック） ---
    failures = {}
    try:
        with transaction.atomic():
            for item in items:
                if item['direction'] != 'push':
                    continue
                binding = bindings[item['name']]
                try:
                    binding.write_value(item['value'])
                except ValidationError as e:
                    failures[item['name']] = f"{binding.label}: {' / '.join(e.messages)}"
                    raise
    except ValidationError:
        results = [
            _result(item, 'error', error=failures[item['name']])
            if item['name'] in failures else _result(item, 'skipped')
            for item in items
        ]
        return _rejected(results, f'{len(failures)} item(s) rejected', 400)
    except BindingConfigError as e:
        return JsonResponse({'code': CODE_ERROR, 'error': str(e)}, status=500)

    results = [
        _result(item, 'ok', value=pulled[item['name']]) if item['direction'] == 'pull'
        else _result(item, 'ok')
        for item in items
    ]
    return JsonResponse({'code': CODE_OK, 'results': results}, status=200)


# ---------------------------------------------------------------------------
# バインディング一覧API
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(['POST'])
def api_bindings(request):
    """ローカル設定ファイルを書くときに、利用可能な名称を確認するためのAPI。"""
    payload, error = _parse_json_body(request)
    if error:
        return error

    auth_error = _check_api_password(payload)
    if auth_error:
        return auth_error

    bindings = [
        {
            'name': b.name,
            'label': b.label,
            'writable': b.writable,
            'type': b.field_type,
            'description': b.description or '',
        }
        for b in CellBinding.objects.all()
    ]
    return JsonResponse({'code': CODE_OK, 'bindings': bindings}, status=200)
