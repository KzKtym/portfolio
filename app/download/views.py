import os
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import DownloadToken, DownloadUser, generate_token
from .utils import get_draft_template_path, load_config, render_draft_text


# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------

def _calc_expiration(now, config):
    upload_limit_minutes = config.get('upload_limit_minutes', 30)
    download_expire_days = config.get('download_expire_days', 7)
    upload_deadline = now + timedelta(minutes=upload_limit_minutes)
    next_day = (now + timedelta(days=1)).date()
    download_expire_date = next_day + timedelta(days=download_expire_days)
    return upload_deadline, download_expire_date


def _build_absolute_url(request, url_name, *args, **kwargs):
    path = reverse(url_name, args=args, kwargs=kwargs)
    return request.build_absolute_uri(path)


def _upload_limit_title(upload_deadline):
    """トークン発行時のタイトル初期値 '(Up Limit hh:mm:ss)' を返す"""
    local_deadline = timezone.localtime(upload_deadline)
    return f'(Up Limit {local_deadline.strftime("%H:%M:%S")})'


def _get_client_ip(request):
    """リバースプロキシ対応でクライアントIPを取得する"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def no_cache_no_index(view_func):
    """ブラウザキャッシュ抑制とクローラー除外用ヘッダーを付与するデコレータ"""
    def wrapped(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response
    return wrapped


def _visible_tokens_queryset(request, base_queryset):
    """ログインユーザーに応じてDownloadTokenを絞り込む（スーパーユーザーは全件）"""
    if request.user.is_superuser:
        return base_queryset
    return base_queryset.filter(issuer=request.user)


def _visible_users_queryset(request, base_queryset):
    """ログインユーザーに応じてDownloadUserを絞り込む（スーパーユーザーは全件）"""
    if request.user.is_superuser:
        return base_queryset
    return base_queryset.filter(owner=request.user)


def _check_token_owner(request, token_obj):
    """トークンの発行者本人またはスーパーユーザーでなければ403"""
    if request.user.is_superuser:
        return
    if token_obj.issuer_id != request.user.id:
        raise PermissionDenied('このトークンを操作する権限がありません。')


def _check_user_owner(request, user_obj):
    """許可ユーザーの登録者本人またはスーパーユーザーでなければ403"""
    if request.user.is_superuser:
        return
    if user_obj.owner_id != request.user.id:
        raise PermissionDenied('このユーザー情報を操作する権限がありません。')


def _check_api_password(request, config):
    """POSTパラメータのapi_passwordを検証する。OKならNone、NGならJsonResponseを返す"""
    api_password = config.get('api_password', '')
    if not api_password:
        return JsonResponse({'code': 1, 'error': 'api_password is not configured'}, status=500)
    if request.POST.get('api_password') != api_password:
        return JsonResponse({'code': 1, 'error': 'invalid api_password'}, status=401)
    return None


# ---------------------------------------------------------------------------
# トークン発行API
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(['POST'])
def api_issue_token(request):
    """
    トークンを新規発行する。
    必須パラメータ: api_password
    任意パラメータ: auth_user（発行者として記録するログインユーザーのusername）
    """
    config = load_config()

    auth_error = _check_api_password(request, config)
    if auth_error:
        return auth_error

    issuer = None
    auth_user = request.POST.get('auth_user')
    if auth_user:
        UserModel = get_user_model()
        try:
            issuer = UserModel.objects.get(username=auth_user, is_active=True)
        except UserModel.DoesNotExist:
            return JsonResponse(
                {'code': 4, 'error': 'auth_user not found or inactive'}, status=400
            )

    now = timezone.now()
    upload_deadline, download_expire_date = _calc_expiration(now, config)

    token_obj = DownloadToken.objects.create(
        token=generate_token(),
        issuer=issuer,
        upload_deadline=upload_deadline,
        download_expire_date=download_expire_date,
        title=_upload_limit_title(upload_deadline),
    )

    return JsonResponse({
        'code': 0,
        'token': token_obj.token,
        'issued_at': token_obj.issued_at.isoformat(),
        'upload_deadline': token_obj.upload_deadline.isoformat(),
        'download_expire_date': token_obj.download_expire_date.isoformat(),
        'download_url': _build_absolute_url(request, 'download:download', token=token_obj.token),
        'draft_url': _build_absolute_url(request, 'download:draft', token=token_obj.token),
    }, status=201)


# ---------------------------------------------------------------------------
# アップロードAPI
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(['POST'])
def api_upload(request):
    """
    指定トークンのレコードへ title / upload_type / target_user / file を反映する。

    必須: token, api_password
    任意: title, upload_type, user_id（target_userの別名も可）, file
          file が省略された場合は <token>.zip として保存する。
          user_id はそのまま target_user としてレコードに格納する。

    レスポンスコード:
        code=0: アップロード成功
        code=1: アップロード処理エラー
        code=2: アップロード期限切れ
        code=3: 既にアップロード済み（情報）
    """
    config = load_config()

    auth_error = _check_api_password(request, config)
    if auth_error:
        return auth_error

    token = request.POST.get('token')
    if not token:
        return JsonResponse({'code': 1, 'error': 'token is required'}, status=400)

    try:
        token_obj = DownloadToken.objects.get(token=token, is_deleted=False)
    except DownloadToken.DoesNotExist:
        return JsonResponse({'code': 1, 'error': 'token not found'}, status=404)

    # 既にアップロード済みチェック
    if token_obj.is_uploaded:
        return JsonResponse({'code': 3, 'error': 'file has already been uploaded for this token'}, status=200)

    # アップロード期限チェック
    if token_obj.is_upload_expired:
        return JsonResponse({'code': 2, 'error': 'upload deadline has expired'}, status=400)

    title = request.POST.get('title')
    upload_type = request.POST.get('upload_type')
    target_user = request.POST.get('user_id') or request.POST.get('target_user')
    uploaded_file = request.FILES.get('file')
    now = timezone.now()

    try:
        if uploaded_file:
            token_obj.uploaded_file.save(uploaded_file.name, uploaded_file, save=False)
        else:
            filename = f'{token_obj.token}.zip'
            token_obj.uploaded_file.save(filename, ContentFile(b''), save=False)

        if title is not None:
            token_obj.title = title
        if upload_type is not None:
            token_obj.upload_type = upload_type
        if target_user is not None:
            token_obj.target_user = target_user

        token_obj.uploaded_at = now
        token_obj.save()
    except Exception as e:
        return JsonResponse({'code': 1, 'error': str(e)}, status=500)

    return JsonResponse({
        'code': 0,
        'token': token_obj.token,
        'title': token_obj.title,
        'upload_type': token_obj.upload_type,
        'target_user': token_obj.target_user,
        'uploaded_at': token_obj.uploaded_at.isoformat(),
        'download_url': _build_absolute_url(request, 'download:download', token=token_obj.token),
        'draft_url': _build_absolute_url(request, 'download:draft', token=token_obj.token),
    }, status=200)


# ---------------------------------------------------------------------------
# ダウンロード実行画面
# ---------------------------------------------------------------------------

@csrf_exempt
@no_cache_no_index
def download_view(request, token):
    """
    ダウンロード実行画面。
    GET: 画面表示
    POST: パスワード照合 → 一致したらファイルをダウンロードさせる
    """
    token_obj = get_object_or_404(DownloadToken, token=token, is_deleted=False)

    context = {
        'token_obj': token_obj,
        'is_expired': token_obj.is_download_expired or not token_obj.is_uploaded,
        'error': None,
    }

    if request.method == 'POST':
        password = request.POST.get('password', '')

        if context['is_expired']:
            context['error'] = 'このダウンロードは期限切れ、または無効です。'
            return render(request, 'download/main.html', context)

        matched_user = None
        for user in DownloadUser.objects.all():
            if check_password(password, user.password):
                matched_user = user
                break

        if matched_user is None:
            context['error'] = 'パスワードが正しくありません。'
            return render(request, 'download/main.html', context)

        # IPアドレスを記録
        token_obj.downloaded_at = timezone.now()
        token_obj.download_user = _get_client_ip(request)
        token_obj.save(update_fields=['downloaded_at', 'download_user'])

        if not token_obj.uploaded_file:
            raise Http404('対象ファイルが見つかりません。')

        return FileResponse(
            token_obj.uploaded_file.open('rb'),
            as_attachment=True,
            filename=os.path.basename(token_obj.uploaded_file.name),
        )

    return render(request, 'download/main.html', context)


# ---------------------------------------------------------------------------
# テストダウンロード（管理画面配下・ログイン必須）
# ---------------------------------------------------------------------------

@login_required
@no_cache_no_index
def test_download_view(request, token):
    """
    管理者用テストダウンロード。
    パスワード入力なし・downloaded_at等の記録なしでファイルを返す。
    ログイン必須。
    """
    token_obj = get_object_or_404(DownloadToken, token=token, is_deleted=False)
    _check_token_owner(request, token_obj)

    if not token_obj.is_uploaded or not token_obj.uploaded_file:
        raise Http404('ファイルがアップロードされていません。')

    return FileResponse(
        token_obj.uploaded_file.open('rb'),
        as_attachment=True,
        filename=os.path.basename(token_obj.uploaded_file.name),
    )


# ---------------------------------------------------------------------------
# ダウンロード案内の下書き表示
# ---------------------------------------------------------------------------

@login_required
@no_cache_no_index
def draft_view(request, token):
    """
    指定トークンの情報からダウンロード案内文を生成し表示する。
    テンプレート: ./data/download/[upload_type].txt
    ログイン必須。
    """
    token_obj = get_object_or_404(DownloadToken, token=token, is_deleted=False)
    _check_token_owner(request, token_obj)

    draft_text = ''
    template_error = None

    if token_obj.upload_type:
        template_path = get_draft_template_path(token_obj.upload_type)
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                template_text = f.read()
            try:
                du = DownloadUser.objects.get(user_id=token_obj.target_user)
                user_name = du.user_name or du.user_id
            except DownloadUser.DoesNotExist:
                user_name = token_obj.target_user or ''

            context_values = {
                'user_name': user_name,
                'title': token_obj.title or '',
                'download_url': _build_absolute_url(request, 'download:download', token=token_obj.token),
                'download_expire_date':token_obj.download_expire_date or '',
            }
            draft_text = render_draft_text(template_text, context_values)
        else:
            template_error = f'テンプレートファイルが見つかりません: data/download/{token_obj.upload_type}.txt'
    else:
        template_error = 'アップロードタイプが未設定のため、テンプレートを表示できません。'

    download_url = _build_absolute_url(request, 'download:download', token=token_obj.token)
    test_download_url = _build_absolute_url(request, 'download:test_download', token=token_obj.token)

    context = {
        'token_obj': token_obj,
        'draft_text': draft_text,
        'template_error': template_error,
        'download_url': download_url,
        'test_download_url': test_download_url,
    }
    return render(request, 'download/draft.html', context)


# ---------------------------------------------------------------------------
# ダウンロード管理画面
# ---------------------------------------------------------------------------

@login_required
@no_cache_no_index
def manage_view(request):
    """
    ダウンロード管理画面。
    表示モード: 既定(直近n日) / 全表示 / 削除含む
    """
    config = load_config()
    list_default_days = config.get('list_default_days', 30)

    mode = request.GET.get('mode', 'default')

    if mode == 'all_deleted':
        tokens = DownloadToken.objects.all()
    elif mode == 'all':
        tokens = DownloadToken.objects.filter(is_deleted=False)
    else:
        threshold = timezone.now() - timedelta(days=list_default_days)
        tokens = DownloadToken.objects.filter(is_deleted=False, issued_at__gte=threshold)

    tokens = _visible_tokens_queryset(request, tokens).order_by('-issued_at')
    users = _visible_users_queryset(request, DownloadUser.objects.all()).order_by('user_id')

    context = {
        'tokens': tokens,
        'users': users,
        'mode': mode,
        'config': config,
        'now': timezone.now(),
    }
    return render(request, 'download/manage.html', context)


@login_required
@require_http_methods(['POST'])
def manage_issue_token(request):
    """管理画面からの新規発行"""
    config = load_config()
    now = timezone.now()
    upload_deadline, download_expire_date = _calc_expiration(now, config)

    DownloadToken.objects.create(
        token=generate_token(),
        issuer=request.user,
        upload_deadline=upload_deadline,
        download_expire_date=download_expire_date,
        title=_upload_limit_title(upload_deadline),
    )

    return redirect(reverse('download:manage'))


@login_required
@require_http_methods(['POST'])
def manage_delete_token(request, token):
    """発行レコードの論理削除"""
    token_obj = get_object_or_404(DownloadToken, token=token)
    _check_token_owner(request, token_obj)
    token_obj.is_deleted = True
    token_obj.save(update_fields=['is_deleted'])
    return redirect(reverse('download:manage'))


# ---------------------------------------------------------------------------
# ユーザー管理
# ---------------------------------------------------------------------------

@login_required
@require_http_methods(['POST'])
def manage_user_add(request):
    user_id = request.POST.get('user_id', '').strip()
    user_name = request.POST.get('user_name', '').strip()
    password = request.POST.get('password', '').strip()
    comment = request.POST.get('comment', '').strip()
    if user_id and password:
        DownloadUser.objects.create(
            user_id=user_id,
            user_name=user_name,
            password=make_password(password),
            comment=comment,
            owner=request.user,
        )
    return redirect(reverse('download:manage'))


@login_required
@require_http_methods(['POST'])
def manage_user_edit(request, user_id):
    user = get_object_or_404(DownloadUser, pk=user_id)
    _check_user_owner(request, user)
    new_user_id = request.POST.get('user_id', '').strip()
    new_user_name = request.POST.get('user_name', '').strip()
    new_password = request.POST.get('password', '').strip()
    new_comment = request.POST.get('comment', '').strip()
    if new_user_id:
        user.user_id = new_user_id
    user.user_name = new_user_name
    if new_password:
        user.password = make_password(new_password)
    user.comment = new_comment
    user.save()
    return redirect(reverse('download:manage'))


@login_required
@require_http_methods(['POST'])
def manage_user_delete(request, user_id):
    user = get_object_or_404(DownloadUser, pk=user_id)
    _check_user_owner(request, user)
    user.delete()
    return redirect(reverse('download:manage'))