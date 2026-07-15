"""
テスト実行専用の設定。

config.settings を継承し、テストに必要な最小限だけを上書きする。

    python manage.py test <app> --settings=config.settings_test
"""
from .settings import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# DB: テスト時のみ sqlite3（インメモリ）に切り替える
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db_test.sqlite3',  # noqa: F405
        'TEST': {
            'NAME': None,  # None = インメモリ（:memory:）
        },
    }
}


# ---------------------------------------------------------------------------
# 静的ファイル
# テストランナーは DEBUG=False で動くため、Manifest系ストレージのままだと
# テンプレートの {% static %} が staticfiles.json を要求して落ちる。
# collectstatic 不要の素のストレージに戻す。
# ---------------------------------------------------------------------------
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'


# ---------------------------------------------------------------------------
# パスワードハッシュ: テスト高速化のため MD5 に固定
# ---------------------------------------------------------------------------
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
