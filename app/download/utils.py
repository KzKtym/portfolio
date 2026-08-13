import os
import re

from django.conf import settings

from app.common.config import load_app_config, resolve_secret  # noqa: F401  (再エクスポート)

APP_LABEL = 'download'


def load_config():
    """app/download/config.json を読み込む"""
    return load_app_config(APP_LABEL)


def get_draft_template_path(upload_type):
    """テンプレートファイルのパスを返す（./data/download/[アップロードタイプ].txt）"""
    return os.path.join(settings.BASE_DIR, 'data', 'download', f'{upload_type}.txt')


def render_draft_text(template_text, context):
    """
    テンプレート内の [key] を context の値で置換する。
    context に存在しないキーはそのまま残す。
    """

    def replace(match):
        key = match.group(1)
        if key in context and context[key] is not None:
            return str(context[key])
        return match.group(0)

    return re.sub(r'\[(\w+)\]', replace, template_text)
