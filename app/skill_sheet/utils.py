import json
import os

from decouple import config as env_config


def load_config():
    """app/skill_sheet/config.json を読み込む"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def resolve_secret(value):
    """
    'env:NAME' 形式なら環境変数 NAME の値を返す。それ以外はそのまま返す。

    設定ファイルに秘密情報を直書きせずに済ませるための仕組み。
    ローカルクライアント側の設定ファイルでも同じ書式を使う。

    参照は os.environ ではなく decouple に任せる。decouple は os.environ を
    先に見てから .env を見るため、export でも .env でも同じように通る。
    os.environ だけを見ると、.env に書いた値は pipenv 経由で起動したときしか
    読めず（decouple は .env を os.environ に注入しない）、起動方法によって
    挙動が変わってしまう。
    """
    if isinstance(value, str) and value.startswith('env:'):
        return env_config(value[4:], default='')
    return value
