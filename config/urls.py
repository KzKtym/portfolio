"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
"""
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.urls import path, include
from django.views.generic import TemplateView

from app.common.decorators import no_cache_no_index
from app.work_shift import spa_views as work_shift_spa_views

# サービスカード遷移先のダミー画面（"Test page." を表示するだけ）
_test_page = lambda request: HttpResponse("Test page.")

urlpatterns = [
    path('admin/', admin.site.urls),

    # Top page (未ログイン時のランディングページ)
    path('', TemplateView.as_view(template_name='home/index.html'), name='index'),

    # アカウント関連
    path('accounts/', include('accounts.urls')),

    # ホーム（ログイン後）
    path('home/', include('app.home.urls')),

    # サービス管理（管理者のみ）。実体は home アプリのビュー。
    path('service_admin/', include('app.home.urls_service_admin')),

    # 商談用アクセス（ゲスト）。相手に渡すURLなので短くする。実体は accounts のビュー。
    path('guest/', include('accounts.urls_guest')),

    # アプリケーション
    path('test/', include(([path('', _test_page, name='index')], 'test_page'))),
    path('skill_sheet/', include('app.skill_sheet.urls')),
    path('download/', include('app.download.urls')),
    path("rag/", include("app.rag_tr_tool.web.urls")),

    # シフト作成（デモ版）: SPA本体・書き込みAPIは app/work_shift/urls.py 側（app_name="work_shift"）
    # に集約。ここでは include するだけ（config.json の url_name: "work_shift:spa" が解決される）。
    path('shift/', include('app.work_shift.urls')),

    # FastAPI（読み取り専任BFF, 127.0.0.1:8090固定・別プロセス）への中継用プロキシ。
    # ビルド済みSPAが呼び出す相対パス fetch("/api/v1/shifts/snapshot") を、フロント側の改修なしに
    # 同一オリジン(:8000)で受けるための窓口。許可パスはこの1件のみ（SSRF対策のホワイトリスト。
    # spa_views.fastapi_proxy 側にも二重チェックあり）。
    path(
        'api/v1/shifts/snapshot',
        no_cache_no_index(login_required(work_shift_spa_views.fastapi_proxy)),
        name='work_shift_fastapi_proxy',
    ),
]
