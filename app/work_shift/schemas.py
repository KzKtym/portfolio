# app/work_shift/schemas.py
from pydantic import BaseModel
from typing import List, Dict, Optional


class DayInfo(BaseModel):
    date: str          # YYYY-MM-DD
    day_of_week: str   # MON, TUE ...


class EventRecord(BaseModel):
    date: str
    title: str


class TeamEvent(BaseModel):
    team_id: int
    records: List[EventRecord]


class EventContainer(BaseModel):
    facility: List[EventRecord]
    team_events: List[TeamEvent]


class MemberShift(BaseModel):
    # member_id は wsft_member.id（職員のStaff.idそのものではない点に注意。
    # 職員/スポットワーカー/募集枠のいずれかを指す汎用識別子のID）
    member_id: int
    # このメンバーが現在このチームに所属している wsft_team_membership.id。
    # 「×」ボタン押下時は、これをキーとしてDjangoへ送る（is_deletedを立てる対象を一意に特定するため）。
    # 過去月表示時（Shift実績のみからメンバーを復元するケース）は、対応するTeamMembership行が
    # 見つからないことがあり得るため Optional とする（その場合フロント側は削除操作を諦める）。
    membership_id: Optional[int] = None
    member_name: str  # 表示名。職員は "{name} 職員{n}"、スポット指名は "{name} Spot{n}"、募集枠は "Spot募集{n}"
    shifts: Dict[str, str]  # 例: {"2026-07-01": "日1"}


class WorkShiftTypeItem(BaseModel):
    # 勤務タイプマスタ1件分。サイドメニュー「デモ用管理」→「勤務タイプ」で管理する
    # （グループ単位）。「休」のように時刻を持たない種別は start_time/end_time が None になる。
    id: int
    name: str
    start_time: Optional[str] = None  # "HH:MM"
    is_overnight: bool = False        # 「翌」チェック。Trueならend_timeは翌日扱い
    end_time: Optional[str] = None    # "HH:MM"
    break_minutes: Optional[int] = None
    color: str                        # 例: "#7cb342"
    order: int = 0                    # 並び順（一覧・パネル・下部集計行で使用）


class ShiftSnapshotResponse(BaseModel):
    year_month: str
    team_id: int
    team_name: str
    group_id: int
    group_name: str
    days_in_month: List[DayInfo]
    events: EventContainer
    # 表示対象: TeamMembershipの所属期間が対象月と重なっているメンバー全員
    # （シフト入力の有無に関わらず表示され続ける。3.8節参照）
    member_shifts: List[MemberShift]
    # シフト種別ごとの日別の予定数（必要人数）。{勤務タイプ名: {日付: 必要人数}}
    # 「小計」行の分母。予定数タブ(F2)で編集可能（確定仕様）
    shift_type_requirements: Dict[str, Dict[str, int]]
    # 勤務タイプマスタ（対象チームが属するグループのもの）。セル編集プルダウン・下部集計行の
    # 種別一覧・表示色は、フロント側のハードコードではなくこちらを参照する
    work_shift_types: List[WorkShiftTypeItem]
