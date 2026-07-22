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


# ---------------------------------------------------------------------------
# ログ: 異常系テストが出力するトレースバック・WARNING を抑制する。
#
# エラー経路のテストは意図的に例外や 404/405 を発生させるため、既定のままだと
# 成功時でも大量のトレースバックが流れ、成否の判別が困難になる。
# ログ出力そのものを検証するテストは assertLogs を使うため、この抑制の影響を受けない。
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'null': {'class': 'logging.NullHandler'},
    },
    'root': {
        'handlers': ['null'],
        'level': 'CRITICAL',
    },
    'loggers': {
        # 404 / 405 / 502 を返すことを検証するテストの WARNING・ERROR
        'django.request': {
            'handlers': ['null'],
            'level': 'CRITICAL',
            'propagate': False,
        },
        # 例外がログに残ることを検証するテストのトレースバック
        'app': {
            'handlers': ['null'],
            'level': 'CRITICAL',
            'propagate': False,
        },
    },
}
