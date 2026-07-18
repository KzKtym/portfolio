# app/work_shift/spa_views.py
"""
work_shift の Vue SPA本体を配信するビュー、および FastAPI（読み取り専任BFF、別プロセス:8090）への
中継用プロキシビュー。

ログイン必須化・キャッシュ禁止/クローラ拒否ヘッダーの付与は、ここでは行わない
（urls.py側で一律にラップする方針。app/work_shift/urls.py 参照）。
"""
import logging
import urllib.error
import urllib.request
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)

# vite.config.ts の build.outDir / base をここに合わせている。
# 「app/work_shift/static/work_shift/」はDjangoのアプリ静的ディレクトリ規約
# （AppDirectoriesFinder）に乗るため、STATICFILES_DIRSへの追加登録は不要。
_SPA_INDEX_HTML_PATH = Path(__file__).resolve().parent / "static" / "work_shift" / "index.html"

# FastAPI（127.0.0.1:8090固定。デプロイ環境側でこのポートをlocalhost限定で待ち受けさせる前提。
# 8節参照）への中継先ベースURL。
_FASTAPI_BASE_URL = "http://127.0.0.1:8090"

# 中継を許可するパスのホワイトリスト（SSRF対策。任意URL中継にしない）。
# 現状FastAPIが公開しているエンドポイントはこの1つのみ（specs.md 4.1節）。
_ALLOWED_FASTAPI_PATHS = {
    "/api/v1/shifts/snapshot",
}


@ensure_csrf_cookie
def spa_index(request):
    """
    `/shift/` のSPA本体。vite buildで生成された index.html をそのまま返す
    （Djangoのテンプレートエンジンには通さない。ビルド済み静的HTMLの単純な配信）。

    @ensure_csrf_cookie: SPAが起動する前に csrftoken クッキーを確実に発行しておく。
    書き込み系API（Django側）は CsrfViewMiddleware で保護されており、フロントは
    このクッキーを読んで X-CSRFToken ヘッダに載せる（src/lib/api.ts の apiFetch）。
    """
    try:
        html = _SPA_INDEX_HTML_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error("work_shift SPA の index.html が見つかりません: %s", _SPA_INDEX_HTML_PATH)
        return HttpResponse(
            "シフト作成アプリのビルド成果物が見つかりません。"
            "frontend/work_shift で `npm run build` を実行してください。",
            status=503,
        )
    return HttpResponse(html, content_type="text/html; charset=utf-8")


@require_http_methods(["GET"])
@ensure_csrf_cookie
def csrf_token(request):
    """
    csrftoken クッキーを発行するためだけの軽量エンドポイント。

    `npm run dev`（Viteの:5173）では index.html を Vite が配信するため spa_index を通らず、
    クッキーが未発行のままとなる。フロントは書き込み前にこのエンドポイントを叩いて
    クッキーを取得する（src/lib/api.ts の ensureCsrfToken）。本番配信時は spa_index で
    既に発行済みのため、通常は呼ばれない。

    GET専用（require_http_methods）。書き込みメソッドは使わないため405で弾く。
    レスポンスbody自体に意味はない（トークンはSet-Cookieヘッダで返る）。
    """
    return JsonResponse({"detail": "ok"})


def fastapi_proxy(request):
    """
    FastAPI（読み取り専任BFF）への中継ビュー。
    ビルド済みSPAが呼び出す `/api/v1/...` の相対パスfetchを、フロント側の改修なしにそのまま
    Djangoの同一オリジン(:8000)で受けられるようにする（決定事項1.1）。

    許可パスはホワイトリストで固定しており、これ以外のパスはURLconf側でそもそもこのビューに
    到達しない（config/urls.pyで許可パスを1件ずつ明示的に登録する運用。念のためここでも
    二重にチェックする）。
    """
    if request.path not in _ALLOWED_FASTAPI_PATHS:
        return JsonResponse({"error": "forbidden path"}, status=403)
    if request.method != "GET":
        return JsonResponse({"error": "method not allowed"}, status=405)

    query_string = request.META.get("QUERY_STRING", "")
    target_url = f"{_FASTAPI_BASE_URL}{request.path}"
    if query_string:
        target_url += f"?{query_string}"

    try:
        proxied_request = urllib.request.Request(target_url, method="GET")
        with urllib.request.urlopen(proxied_request, timeout=10) as upstream_response:
            body = upstream_response.read()
            status = upstream_response.status
            content_type = upstream_response.headers.get("Content-Type", "application/json")
    except urllib.error.HTTPError as e:
        # FastAPI側が返したエラーレスポンス（404, 422等）はそのまま透過する
        body = e.read()
        status = e.code
        content_type = e.headers.get("Content-Type", "application/json")
    except urllib.error.URLError as e:
        logger.error("FastAPIへの接続に失敗しました (%s): %s", target_url, e)
        return JsonResponse({"error": "FastAPIサービスに接続できませんでした"}, status=502)

    return HttpResponse(body, status=status, content_type=content_type)