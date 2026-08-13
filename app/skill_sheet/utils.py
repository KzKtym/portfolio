"""skill_sheet の設定読み込み。

実体は app/common/config.py にある。既存の呼び出し側（views / api_views /
binding_views / tests）が `from .utils import load_config, resolve_secret` で
参照しているため、アプリ内の入口としてこの薄いラッパーを残す。
"""
from app.common.config import load_app_config, resolve_secret  # noqa: F401  (再エクスポート)

APP_LABEL = 'skill_sheet'


def load_config():
    """app/skill_sheet/config.json を読み込む"""
    return load_app_config(APP_LABEL)
