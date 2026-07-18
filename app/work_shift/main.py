# app/work_shift/main.py
"""
FastAPI = 読み取り専任のBFF。

- GET /api/v1/shifts/snapshot : Django管理下のPostgreSQL(wsft_*)から、
  指定された「チーム＋年月」のシートを1回のレスポンスで返す。

- 表示対象メンバー・並び順の決定方法（重要な設計原則。9節参照）:
  「シフト表は月単位で作成・確定する」という大原則のもと、**過去分はマスターの変更の
  影響を受けるべきではない**。そのため、対象年月が「今日を含む月より前（過去月）」か
  「今日を含む月・それ以降（当月・将来月）」かで、表示ロジックを分岐させている。

  - 当月・将来月: 表示対象・並び順とも wsft_team_membership（生きたマスター）に従う。
    シフト入力の有無に関わらず、所属期間が対象月と重なっていれば表示される。
  - 過去月: 表示対象は「その月に wsft_shifts の実績が1件でもあるメンバーのみ」に限定し、
    TeamMembershipの現在の状態（所属終了・×による除外等）は一切参照しない。並び順も
    Shift.order（保存時点のTeamMembership.orderのスナップショット）に従う。

  ※ 月を「確定」する明示的な操作（提出・ロック等）は今回未実装。「今日の日付」だけで
    過去/当月・将来を判定する簡易的な運用（9節「今後の課題」参照）。

- 職員の表示名は "{name} 職員{n}" 形式、スポットワーカーの表示名は "{name} Spot{n}" 形式。
  nは種別ごとに独立して採番する（職員とスポットワーカーで別々に1,2,3...）。対象月に表示されている
  当該種別のメンバーだけを母集団に、当月・将来月ではTeamMembership.start_dateの早い順、過去月では
  Shift.orderの小さい順で採番する（募集枠は採番の対象外。表示は"Spot募集{slot_number}"固定）。

- 書き込み系API（シフト保存・メンバー追加・マスタCRUD）は Django 側 ( /shift/api/v1/ ) が
  直接担当する。

起動例:
    WSFT_DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/dbname \
    uvicorn app.work_shift.main:app --port 8090 --reload
"""
import calendar
import json
from collections import defaultdict
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import bindparam, text
from sqlalchemy.exc import SQLAlchemyError

from .db import engine
from .schemas import (
    DayInfo,
    EventContainer,
    MemberShift,
    ShiftSnapshotResponse,
    WorkShiftTypeItem,
)
from .services import generate_events_for_month, is_rule_effective

app = FastAPI(title="work_shift BFF (read-only)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

MEMBER_KIND_STAFF = 0
MEMBER_KIND_SPOT_WORKER = 1
MEMBER_KIND_RECRUITMENT_SLOT = 2


def _format_time_or_none(value):
    """DBから返るtime値（None/datetime.time/文字列いずれもあり得る）を "HH:MM" 文字列へ整形する。"""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    return str(value)[:5]


def _fetch_names_by_kind(conn, membership_rows):
    """membership_rows（member_kind/ref_idを含む行のリスト）から、種別ごとの表示用名前・属性を引く。"""
    if not membership_rows:
        return {}, {}, {}

    staff_ids = [r["ref_id"] for r in membership_rows if r["member_kind"] == MEMBER_KIND_STAFF]
    spot_ids = [r["ref_id"] for r in membership_rows if r["member_kind"] == MEMBER_KIND_SPOT_WORKER]
    slot_ids = [r["ref_id"] for r in membership_rows if r["member_kind"] == MEMBER_KIND_RECRUITMENT_SLOT]

    staff_names = {}
    if staff_ids:
        rows = conn.execute(
            text("SELECT id, name FROM wsft_staffs WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": staff_ids},
        ).mappings().all()
        staff_names = {r["id"]: r["name"] for r in rows}

    spot_worker_names = {}
    if spot_ids:
        rows = conn.execute(
            text("SELECT id, name FROM wsft_spot_worker WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": spot_ids},
        ).mappings().all()
        spot_worker_names = {r["id"]: r["name"] for r in rows}

    slot_numbers = {}
    if slot_ids:
        rows = conn.execute(
            text("SELECT id, slot_number FROM wsft_recruitment_slot WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": slot_ids},
        ).mappings().all()
        slot_numbers = {r["id"]: r["slot_number"] for r in rows}

    return staff_names, spot_worker_names, slot_numbers


@app.get("/api/v1/shifts/snapshot", response_model=ShiftSnapshotResponse)
def get_shift_snapshot(
    year_month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    team_id: int = Query(..., description="表示対象のチームID（シート＝チーム＋年月で一意）"),
):
    year, month = map(int, year_month.split("-"))
    _, num_days = calendar.monthrange(year, month)

    weekdays_str = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    days_in_month = [
        DayInfo(
            date=date(year, month, d).isoformat(),
            day_of_week=weekdays_str[date(year, month, d).weekday()],
        )
        for d in range(1, num_days + 1)
    ]

    first_day = date(year, month, 1).isoformat()
    last_day = date(year, month, num_days).isoformat()
    current_year_month = date.today().strftime("%Y-%m")
    is_past_month = year_month < current_year_month

    try:
        with engine.connect() as conn:
            # 1. チーム＋所属グループ情報（シート見出し用）
            team_row = conn.execute(
                text("""
                    SELECT t.id, t.name AS team_name, g.id AS group_id, g.name AS group_name
                    FROM wsft_teams t
                    JOIN wsft_groupe g ON g.id = t.group_id
                    WHERE t.id = :team_id
                """),
                {"team_id": team_id},
            ).mappings().first()

            if team_row is None:
                raise HTTPException(status_code=404, detail=f"team_id={team_id} が見つかりません")

            # 2. 施設イベント定義（対象年月に有効な世代のみ、粗くSQLで絞り込み）
            event_rows = conn.execute(
                text("""
                    SELECT title, recurrence_type, recurrence_days,
                           effective_from, effective_until
                    FROM wsft_event_definitions
                    WHERE target_type = 'facility'
                      AND effective_from <= :ym
                      AND (effective_until IS NULL OR effective_until > :ym)
                    ORDER BY id
                """),
                {"ym": year_month},
            ).mappings().all()

            # 3. 表示対象メンバーの決定（過去月か、当月・将来月かで分岐。上部docstring参照）
            if not is_past_month:
                # 当月・将来月: TeamMembership（生きたマスター）駆動。
                # 半開区間ではなく閉区間: start_date <= 月末 AND (end_date IS NULL OR end_date >= 月初)
                # is_deleted=True（×押下済み）の行は対象から除外する
                membership_rows = conn.execute(
                    text("""
                        SELECT tm.id AS membership_id, tm.member_id AS member_id,
                               tm.start_date AS sort_key, tm."order" AS member_order,
                               m.member_kind AS member_kind, m.member_id AS ref_id
                        FROM wsft_team_membership tm
                        JOIN wsft_member m ON m.id = tm.member_id
                        WHERE tm.team_id = :team_id
                          AND tm.start_date <= :last_day
                          AND (tm.end_date IS NULL OR tm.end_date >= :first_day)
                          AND NOT tm.is_deleted
                        ORDER BY tm.start_date, tm.member_id
                    """),
                    {"team_id": team_id, "first_day": first_day, "last_day": last_day},
                ).mappings().all()
            else:
                # 過去月: その月にShift実績が実在するメンバーのみ。TeamMembershipの現在状態は無視。
                # 並び順はShift.orderの凍結値を使う（同一メンバーの複数行がある場合はMAXを代表値とする）。
                # membership_idは「×」用に、関連する最新のTeamMembership行を参考値として引く
                # （見つからない場合はNULL＝フロント側は削除操作を諦める）。
                membership_rows = conn.execute(
                    text("""
                        SELECT
                            (SELECT tm.id FROM wsft_team_membership tm
                             WHERE tm.team_id = :team_id AND tm.member_id = s.member_id
                             ORDER BY tm.start_date DESC LIMIT 1) AS membership_id,
                            s.member_id AS member_id,
                            MAX(s."order") AS sort_key,
                            MAX(s."order") AS member_order,
                            m.member_kind AS member_kind,
                            m.member_id AS ref_id
                        FROM wsft_shifts s
                        JOIN wsft_member m ON m.id = s.member_id
                        WHERE s.team = :team_id
                          AND s.date BETWEEN :first_day AND :last_day
                          AND s.deleted_at IS NULL
                        GROUP BY s.member_id, m.member_kind, m.member_id
                    """),
                    {"team_id": team_id, "first_day": first_day, "last_day": last_day},
                ).mappings().all()

            staff_names, spot_worker_names, slot_numbers = _fetch_names_by_kind(conn, membership_rows)

            # 4. 当該チーム・当該月のシフト実績（論理削除されたものは除外）
            shift_rows = conn.execute(
                text("""
                    SELECT member_id, date, shift_type
                    FROM wsft_shifts
                    WHERE team = :team_id
                      AND date BETWEEN :first_day AND :last_day
                      AND deleted_at IS NULL
                """),
                {"team_id": team_id, "first_day": first_day, "last_day": last_day},
            ).mappings().all()

            # 4b. 勤務タイプマスタ（対象チームが属するグループのもの）。
            #     セル編集パネル・下部集計行の種別一覧・色は、これをフロントへそのまま渡す
            work_shift_type_rows = conn.execute(
                text("""
                    SELECT id, name, start_time, is_overnight, end_time, break_minutes, color, "order"
                    FROM wsft_work_shift_types
                    WHERE group_id = :group_id
                    ORDER BY "order", id
                """),
                {"group_id": team_row["group_id"]},
            ).mappings().all()

            # 4c. 予定数（勤務タイプ×日付ごとの必要人数。予定数タブF2で編集する値）。
            #     未保存の行がない日は0人として扱う（フロント側で埋める）。
            requirement_rows = conn.execute(
                text("""
                    SELECT r.date, r.required_count, w.name AS work_shift_type_name
                    FROM wsft_shift_requirements r
                    JOIN wsft_work_shift_types w ON w.id = r.work_shift_type_id
                    WHERE r.team_id = :team_id
                      AND r.date BETWEEN :first_day AND :last_day
                """),
                {"team_id": team_id, "first_day": first_day, "last_day": last_day},
            ).mappings().all()

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"データベースに接続できません。WSFT_DATABASE_URL を確認してください: {exc}",
        )

    # 5. 繰り返しルール → 具体日付への展開
    facility_events = []
    for rule in event_rows:
        if not is_rule_effective(year_month, rule["effective_from"], rule["effective_until"]):
            continue
        recurrence_days = rule["recurrence_days"] or []
        if isinstance(recurrence_days, str):
            recurrence_days = json.loads(recurrence_days)
        facility_events.extend(
            generate_events_for_month(
                year=year,
                month=month,
                title=rule["title"],
                recurrence_type=rule["recurrence_type"],
                recurrence_days=recurrence_days,
            )
        )

    # 6. 職員(Staff種別)・スポットワーカー(SpotWorker種別)それぞれの表示番号(n)を、
    #    種別ごとに独立して採番する（母集団が別。職員は「職員{n}」、スポットワーカーは「Spot{n}」）。
    #    当月・将来月: sort_key=start_date の早い順 / 過去月: sort_key=Shift.order の小さい順
    def _numbering_by_member_id(kind: int) -> dict:
        rows = [r for r in membership_rows if r["member_kind"] == kind]
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                r["sort_key"] is None,  # NULLを最後に回す
                r["sort_key"] if r["sort_key"] is not None else "",
                r["member_id"],
            ),
        )
        return {r["member_id"]: idx + 1 for idx, r in enumerate(rows_sorted)}

    staff_number_by_member_id = _numbering_by_member_id(MEMBER_KIND_STAFF)
    spot_worker_number_by_member_id = _numbering_by_member_id(MEMBER_KIND_SPOT_WORKER)

    # 7. 表示名の組み立て（種別ごとに書式が異なる）
    def build_display_name(member_id: int, member_kind: int, ref_id: int) -> str:
        if member_kind == MEMBER_KIND_STAFF:
            raw_name = staff_names.get(ref_id, f"(不明な職員 id={ref_id})")
            n = staff_number_by_member_id.get(member_id, "?")
            return f"{raw_name} 職員{n}"
        if member_kind == MEMBER_KIND_SPOT_WORKER:
            raw_name = spot_worker_names.get(ref_id, f"(不明なスポットワーカー id={ref_id})")
            n = spot_worker_number_by_member_id.get(member_id, "?")
            return f"{raw_name} Spot{n}"
        if member_kind == MEMBER_KIND_RECRUITMENT_SLOT:
            slot_number = slot_numbers.get(ref_id, "?")
            return f"Spot募集{slot_number}"
        return f"(不明なメンバー種別={member_kind})"

    # 8. member_id ごとの {日付: シフト種別} 辞書に整形
    shifts_by_member = defaultdict(dict)
    for row in shift_rows:
        d = row["date"]
        date_key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        shifts_by_member[row["member_id"]][date_key] = row["shift_type"]

    member_shifts = [
        MemberShift(
            member_id=r["member_id"],
            membership_id=r["membership_id"],
            member_name=build_display_name(r["member_id"], r["member_kind"], r["ref_id"]),
            shifts=shifts_by_member.get(r["member_id"], {}),
        )
        for r in membership_rows
    ]
    # 9. 並び順（member_order優先、未設定はmember_id昇順で末尾へ）
    order_by_member = {r["member_id"]: r["member_order"] for r in membership_rows}
    member_shifts.sort(
        key=lambda ms: (
            order_by_member.get(ms.member_id) if order_by_member.get(ms.member_id) is not None else float("inf"),
            ms.member_id,
        )
    )

    # 10. 勤務タイプマスタをレスポンス用に整形（時刻はNULL可。「休」等は None のまま渡す）
    work_shift_types = [
        WorkShiftTypeItem(
            id=r["id"],
            name=r["name"],
            start_time=_format_time_or_none(r["start_time"]),
            is_overnight=r["is_overnight"],
            end_time=_format_time_or_none(r["end_time"]),
            break_minutes=r["break_minutes"],
            color=r["color"],
            order=r["order"],
        )
        for r in work_shift_type_rows
    ]

    # 11. 予定数（勤務タイプ×日付ごとの必要人数）。未保存の日は0で埋めておく
    #     （「小計」行の分母。通常タブ(F1)・予定数タブ(F2)の双方がこの1つのデータを参照する）
    shift_type_requirements: dict = {
        w.name: {d.date: 0 for d in days_in_month} for w in work_shift_types
    }
    for row in requirement_rows:
        name = row["work_shift_type_name"]
        req_date = row["date"]
        date_str = req_date.isoformat() if hasattr(req_date, "isoformat") else str(req_date)
        if name in shift_type_requirements:
            shift_type_requirements[name][date_str] = row["required_count"]

    return ShiftSnapshotResponse(
        year_month=year_month,
        team_id=team_row["id"],
        team_name=team_row["team_name"],
        group_id=team_row["group_id"],
        group_name=team_row["group_name"],
        days_in_month=days_in_month,
        events=EventContainer(facility=facility_events, team_events=[]),
        member_shifts=member_shifts,
        shift_type_requirements=shift_type_requirements,
        work_shift_types=work_shift_types,
    )
