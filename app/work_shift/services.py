# app/work_shift/services.py
from datetime import date
import calendar
from typing import List, Optional

from .schemas import EventRecord

# 曜日のマッピング定義（DBの文字列 ⇄ Pythonのweekday）
WEEKDAY_MAP = {
    "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6
}


def is_rule_effective(year_month: str, effective_from: str, effective_until: Optional[str]) -> bool:
    """
    履歴管理された繰り返しルールが、対象年月に有効かどうかを判定する。

    有効期間は "YYYY-MM" 文字列の半開区間 [effective_from, effective_until) で表現される。
    "YYYY-MM" のゼロ埋め形式は辞書順比較＝時系列比較となるため、文字列比較で判定できる。

    - effective_from <= year_month であること
    - effective_until が未設定（無期限）か、year_month < effective_until であること
    """
    if year_month < effective_from:
        return False
    if effective_until is not None and year_month >= effective_until:
        return False
    return True


def generate_events_for_month(
    year: int,
    month: int,
    title: str,
    recurrence_type: str,
    recurrence_days: List[str],
) -> List[EventRecord]:
    """
    繰り返しルールから、指定年月に発生する具体的なイベント日付リストを生成する
    """
    event_records = []

    # 対象月が何日まであるかを取得 (例: 2026年7月 -> 1日〜31日)
    _, num_days = calendar.monthrange(year, month)

    # 毎週ルールの展開
    if recurrence_type == "weekly":
        # ターゲットになるPythonの曜日数値のセットを作成 (例: [0, 2] -> 月, 水)
        target_weekdays = {WEEKDAY_MAP[d] for d in recurrence_days if d in WEEKDAY_MAP}

        # 1日〜月末までループして、曜日が一致する日を抽出
        for day in range(1, num_days + 1):
            current_date = date(year, month, day)
            if current_date.weekday() in target_weekdays:
                event_records.append(EventRecord(
                    date=current_date.isoformat(),  # "YYYY-MM-DD"
                    title=title
                ))

    # 毎月ルールの展開（「第〇曜日」等への拡張ポイント。今回スコープ外）
    elif recurrence_type == "monthly":
        pass

    return event_records
