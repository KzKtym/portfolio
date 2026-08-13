"""アプリごとの config.json を読むための共通ローダー。

各アプリが自前でパスを組み立てていたため、同じことをする4通りの書き方が並存していた
（os.path.dirname(__file__) / settings.BASE_DIR との文字列結合 / Path(__file__).parent.parent /
モジュール定数）。置き場所を1箇所に寄せて、呼び出し側はアプリラベルだけを渡す形にする。

パスは Django のアプリレジストリから引くため、app/ 配下という現在のディレクトリ構成に
依存しない。

なお app/rag_tr_tool は独自のパス解決を持つが、アプリ昇格リファクタが控えているため
ここでは統合していない。
"""
import json
from pathlib import Path

from decouple import config as env_config
from django.apps import apps

CONFIG_FILENAME = 'config.json'


def get_app_config_path(app_label):
    """アプリラベルから config.json の絶対パスを返す。"""
    return Path(apps.get_app_config(app_label).path) / CONFIG_FILENAME


def load_app_config(app_label):
    """<アプリのディレクトリ>/config.json を読み込んで dict を返す。

    ファイルが無い / 壊れている場合は例外をそのまま送出する。既定値で握りつぶすと
    設定漏れに気付けないため、扱いは呼び出し側の判断に委ねる。
    """
    with open(get_app_config_path(app_label), 'r', encoding='utf-8') as f:
        return json.load(f)


def resolve_secret(value):
    """'env:NAME' 形式なら環境変数 NAME の値を返す。それ以外はそのまま返す。

    設定ファイルに秘密情報を直書きせずに済ませるための仕組み。
    Excel 連携のローカルクライアント側でも同じ書式を使う。

    参照は os.environ ではなく decouple に任せる。decouple は os.environ を
    先に見てから .env を見るため、export でも .env でも同じように通る。
    os.environ だけを見ると、.env に書いた値は pipenv 経由で起動したときしか
    読めず（decouple は .env を os.environ に注入しない）、起動方法によって
    挙動が変わってしまう。
    """
    if isinstance(value, str) and value.startswith('env:'):
        return env_config(value[4:], default='')
    return value
