"""
home アプリの設定
"""
from django.apps import AppConfig


class HomeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'app.home'
    verbose_name = 'ホーム画面'