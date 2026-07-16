import json
import os
import re

from django.conf import settings


def load_config():
    """app/download/config.json を読み込む"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


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
