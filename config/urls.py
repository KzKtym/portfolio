"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    # home アプリ未実装のため、暫定で管理サイトへリダイレクト
    path('', RedirectView.as_view(url='/admin/', permanent=False)),

    path('admin/', admin.site.urls),

    # アカウント関連（ログイン・ログアウト・パスワード変更/リセット・サインアップ）
    path('accounts/', include('accounts.urls')),
]
