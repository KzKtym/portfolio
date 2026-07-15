"""
accounts アプリの設定
"""
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    verbose_name = 'アカウント管理'
    
    def ready(self):
        """アプリケーション初期化時に実行"""
        # シグナルハンドラーをインポート
        import accounts.middleware