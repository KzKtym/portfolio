"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from django.views.generic import TemplateView

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

    # ダミー画面: app/home/config.json の url_name "test_page:index" に対応
    path('test/', include(([path('', _test_page, name='index')], 'test_page'))),
]
