# app/work_shift/views.py
"""
書き込み系APIは FastAPI を経由せず Django が直接受け持つ。
（FastAPI は GET /api/v1/shifts/snapshot の集計・整形専任のBFF）

DRF は導入せず、標準の Django（JsonResponse + 生JSON parse）で実装する。

認証・CSRF:
- 認証は urls.py の protected() が login_required を一律に適用する（個々のビューでは実装しない）。
- CSRFは CsrfViewMiddleware による標準の保護をそのまま使う（@csrf_exempt は使わない）。
  SPAは同一オリジン配信のため、フロント側（src/lib/api.ts の apiFetch）が
  X-CSRFToken ヘッダを付与すれば足りる。
"""
import json
from datetime import date, datetime
from functools import wraps

from django.db import transaction
from django.db.models import Max, ProtectedError, Q
from django.db.models.functions import TruncMonth
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from .models import (
    EventDefinition,
    Groupe,
    Member,
    RecruitmentSlot,
    Shift,
    ShiftRequirement,
    SpotWorker,
    Staff,
    Team,
    TeamMembership,
    WorkShiftType,
)


# ---------- 入力バリデーション共通処理 ----------
#
# 方針: 不正なリクエストで 500 を返さない（＝Djangoのエラーハンドラまで例外を上げない）。
# 「入力が悪い」ことを表す BadRequest のみを json_api デコレータが 400 へ変換する。
# 内部由来の例外（バグ）は握り潰さず、そのまま 500 として表面化させる。


class BadRequest(Exception):
    """クライアント入力の不正を表す例外。json_api デコレータが JsonResponse(400) へ変換する。"""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def json_api(view):
    """BadRequest を 400 レスポンスへ変換する。それ以外の例外は素通しする（バグを隠さないため）。"""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except BadRequest as exc:
            return JsonResponse({"error": exc.message}, status=400)

    return wrapped


def _json_body(request) -> dict:
    """リクエストbodyをJSON dictとして取得する。壊れたJSON・非dictは BadRequest。"""
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        raise BadRequest("invalid JSON")
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    return body


def _required(body: dict, *keys):
    """必須キーの存在を検証する。欠落していれば BadRequest。"""
    missing = [k for k in keys if k not in body]
    if missing:
        raise BadRequest(f"{', '.join(missing)} is required")


def _parse_int(value, name) -> int:
    """整数へ変換する。変換できなければ BadRequest。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        raise BadRequest(f"{name} must be an integer")


def _parse_year_month(year_month):
    """"YYYY-MM" を (year, month) へ変換する。形式不正は BadRequest。"""
    try:
        year, month = (int(v) for v in str(year_month).split("-"))
        date(year, month, 1)
    except (TypeError, ValueError):
        raise BadRequest('year_month must be "YYYY-MM"')
    return year, month


def _ensure_exists(model, pk, name):
    """FK先の存在を検証する。存在しなければ BadRequest（未検証だとFK違反で500になるため）。"""
    if pk is None or not model.objects.filter(pk=pk).exists():
        raise BadRequest(f"{name}={pk} not found")


# ---------- グループ CRUD（簡易画面用） ----------

@require_http_methods(["GET", "POST"])
@json_api
def groupe_list_create(request):
    if request.method == "GET":
        groupes = Groupe.objects.all().order_by("id")
        return JsonResponse({
            "groupes": [{"id": g.id, "name": g.name} for g in groupes]
        })

    body = _json_body(request)
    _required(body, "name")
    groupe = Groupe.objects.create(name=body["name"])
    return JsonResponse({"id": groupe.id, "name": groupe.name}, status=201)


@require_http_methods(["GET", "PUT", "DELETE"])
@json_api
def groupe_detail(request, groupe_id: int):
    groupe = get_object_or_404(Groupe, pk=groupe_id)

    if request.method == "GET":
        return JsonResponse({"id": groupe.id, "name": groupe.name})

    if request.method == "PUT":
        body = _json_body(request)
        if "name" in body:
            groupe.name = body["name"]
        groupe.save()
        return JsonResponse({"id": groupe.id, "name": groupe.name})

    # DELETE: 配下にTeamが存在する場合はon_delete=PROTECTによりProtectedErrorになる。
    # 捕捉は ProtectedError に限定する（bare exceptだと無関係なバグまで
    # 「所属チームが存在する」という誤ったメッセージで隠してしまうため）。
    try:
        groupe.delete()
    except ProtectedError:
        return JsonResponse(
            {"error": "このグループには所属チームが存在するため削除できません。先にチームを削除してください。"},
            status=409,
        )
    return JsonResponse({"status": "deleted", "id": groupe_id})


# ---------- チーム（参照専用 + 名称変更のみ。作成/編集(名称以外)/削除は今回のスコープ外） ----------

@require_http_methods(["GET"])
@json_api
def team_list(request):
    teams = Team.objects.select_related("group").all().order_by("id")
    return JsonResponse({
        "teams": [
            {"id": t.id, "name": t.name, "group_id": t.group_id, "group_name": t.group.name}
            for t in teams
        ]
    })


@require_http_methods(["GET", "PUT"])
@json_api
def team_detail(request, team_id: int):
    team = get_object_or_404(Team, pk=team_id)

    if request.method == "GET":
        return JsonResponse({"id": team.id, "name": team.name, "group_id": team.group_id, "group_name": team.group.name})

    # PUT: 名称変更のみサポート（📝ボタン用）。グループの付け替え等は今回スコープ外
    body = _json_body(request)
    if "name" in body:
        team.name = body["name"]
        team.save(update_fields=["name"])
    return JsonResponse({"id": team.id, "name": team.name, "group_id": team.group_id, "group_name": team.group.name})


@require_http_methods(["GET"])
@json_api
def team_available_year_months(request, team_id: int):
    """
    年月プルダウン用。指定チームにシフト実績（wsft_shifts）が1件でも存在する年月を、
    古い月→新しい月の昇順で返す（TeamMembershipのみで実績のない月は含めない）。
    """
    get_object_or_404(Team, pk=team_id)
    year_months = (
        Shift.objects
        .filter(team=team_id, deleted_at__isnull=True)
        .annotate(ym=TruncMonth("date"))
        .values_list("ym", flat=True)
        .distinct()
        .order_by("ym")
    )
    return JsonResponse({"year_months": [ym.strftime("%Y-%m") for ym in year_months if ym is not None]})


# ---------- 勤務タイプ CRUD（サイドメニュー「デモ用管理」→「勤務タイプ」。グループ単位のマスタ） ----------

def _parse_time_or_none(value):
    """"HH:MM" 形式の文字列をdatetime.timeへ。空文字/Noneはそのまま None（「休」など時刻を持たない種別用）。"""
    if value in (None, ""):
        return None
    return datetime.strptime(value, "%H:%M").time()


def _serialize_work_shift_type(w: WorkShiftType) -> dict:
    return {
        "id": w.id,
        "group_id": w.group_id,
        "name": w.name,
        "start_time": w.start_time.strftime("%H:%M") if w.start_time else None,
        "is_overnight": w.is_overnight,
        "end_time": w.end_time.strftime("%H:%M") if w.end_time else None,
        "break_minutes": w.break_minutes,
        "color": w.color,
        "order": w.order,
    }


@require_http_methods(["GET", "POST"])
@json_api
def work_shift_type_list_create(request):
    if request.method == "GET":
        # group_id省略時は全件（デモ用途のため厳密なアクセス制御は行わない）
        group_id = request.GET.get("group_id")
        qs = WorkShiftType.objects.all().order_by("order", "id")
        if group_id:
            qs = qs.filter(group_id=group_id)
        return JsonResponse({"work_shift_types": [_serialize_work_shift_type(w) for w in qs]})

    body = _json_body(request)
    name = (body.get("name") or "").strip()
    group_id = body.get("group_id")
    if not name:
        return JsonResponse({"error": "name is required"}, status=400)
    if group_id is None:
        return JsonResponse({"error": "group_id is required"}, status=400)
    _ensure_exists(Groupe, group_id, "group_id")
    if WorkShiftType.objects.filter(group_id=group_id, name=name).exists():
        return JsonResponse({"error": f"「{name}」は既に登録されています"}, status=400)

    try:
        w = WorkShiftType.objects.create(
            group_id=group_id,
            name=name,
            start_time=_parse_time_or_none(body.get("start_time")),
            is_overnight=bool(body.get("is_overnight", False)),
            end_time=_parse_time_or_none(body.get("end_time")),
            break_minutes=body.get("break_minutes"),
            color=body.get("color") or "#7cb342",
            order=body.get("order", 0),
        )
    except ValueError:
        return JsonResponse({"error": "start_time/end_time は \"HH:MM\" 形式で指定してください"}, status=400)

    return JsonResponse(_serialize_work_shift_type(w), status=201)


@require_http_methods(["GET", "PUT", "DELETE"])
@json_api
def work_shift_type_detail(request, work_shift_type_id: int):
    w = get_object_or_404(WorkShiftType, pk=work_shift_type_id)

    if request.method == "GET":
        return JsonResponse(_serialize_work_shift_type(w))

    if request.method == "PUT":
        body = _json_body(request)
        if "name" in body:
            new_name = (body["name"] or "").strip()
            if not new_name:
                return JsonResponse({"error": "name is required"}, status=400)
            if WorkShiftType.objects.filter(group_id=w.group_id, name=new_name).exclude(pk=w.id).exists():
                return JsonResponse({"error": f"「{new_name}」は既に登録されています"}, status=400)
            w.name = new_name
        try:
            if "start_time" in body:
                w.start_time = _parse_time_or_none(body["start_time"])
            if "end_time" in body:
                w.end_time = _parse_time_or_none(body["end_time"])
        except ValueError:
            return JsonResponse({"error": "start_time/end_time は \"HH:MM\" 形式で指定してください"}, status=400)
        if "is_overnight" in body:
            w.is_overnight = bool(body["is_overnight"])
        if "break_minutes" in body:
            w.break_minutes = body["break_minutes"]
        if "color" in body:
            w.color = body["color"]
        if "order" in body:
            w.order = body["order"]
        w.save()
        return JsonResponse(_serialize_work_shift_type(w))

    # DELETE: 単純な削除（既存のwsft_shifts.shift_typeは文字列のまま残るため、
    # 過去に保存済みのシフト表示自体には影響しない。将来分の入力候補から消えるのみ）
    w.delete()
    return JsonResponse({"status": "deleted", "id": work_shift_type_id})


def _active_member_ref_ids(member_kind: int, team_id: int, year_month: str) -> set:
    """
    指定チーム・指定年月において、現在有効な所属（TeamMembershipの期間が対象月と重なり、
    かつ is_deleted=False）を持つメンバーの ref_id（Staff.id や SpotWorker.id）集合を返す。

    「メンバーを追加＋」の一覧から、既に追加済みのメンバーを除外するためのフィルタに使う。
    過去に所属していたが現在は対象外（end_date経過済み、または×でis_deleted=True）の人は
    含めない＝除外対象にならない（再度選択肢に表示される）。
    """
    import calendar as _calendar

    year, month = _parse_year_month(year_month)
    _, num_days = _calendar.monthrange(year, month)
    first_day = date(year, month, 1)
    last_day = date(year, month, num_days)

    member_ids = TeamMembership.objects.filter(
        team_id=team_id,
        is_deleted=False,
        start_date__lte=last_day,
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=first_day)
    ).values_list("member_id", flat=True)

    ref_ids = Member.objects.filter(
        id__in=list(member_ids), member_kind=member_kind
    ).values_list("member_id", flat=True)

    return set(ref_ids)


# ---------- 職員 CRUD（簡易画面用） ----------

@require_http_methods(["GET", "POST"])
@json_api
def staff_list_create(request):
    if request.method == "GET":
        staffs = Staff.objects.all().order_by("id")

        # 「メンバーを追加＋」からの呼び出し時のみ付与されるオプションのフィルタ用パラメータ。
        # 通常の職員CRUD画面（StaffCrud.vue）からの呼び出しでは指定されないため、全件表示のまま。
        exclude_active_team = request.GET.get("exclude_active_team")
        year_month = request.GET.get("year_month")
        if exclude_active_team and year_month:
            team_id = _parse_int(exclude_active_team, "exclude_active_team")
            excluded_ids = _active_member_ref_ids(Member.KIND_STAFF, team_id, year_month)
            staffs = staffs.exclude(id__in=excluded_ids)

        return JsonResponse({
            "staffs": [
                {"id": s.id, "name": s.name, "default_team": s.default_team}
                for s in staffs
            ]
        })

    body = _json_body(request)
    _required(body, "name")
    staff = Staff.objects.create(
        name=body["name"],
        default_team=body.get("default_team"),
    )
    return JsonResponse({"id": staff.id, "name": staff.name, "default_team": staff.default_team}, status=201)


@require_http_methods(["GET", "PUT", "DELETE"])
@json_api
def staff_detail(request, staff_id: int):
    staff = get_object_or_404(Staff, pk=staff_id)

    if request.method == "GET":
        return JsonResponse({"id": staff.id, "name": staff.name, "default_team": staff.default_team})

    if request.method == "PUT":
        body = _json_body(request)
        if "name" in body:
            staff.name = body["name"]
        if "default_team" in body:
            staff.default_team = body["default_team"]
        staff.save()
        return JsonResponse({"id": staff.id, "name": staff.name, "default_team": staff.default_team})

    staff.delete()
    return JsonResponse({"status": "deleted", "id": staff_id})


# ---------- スポットワーカー CRUD（簡易画面用。サイドメニュー「デモ用データ」→「スポット」） ----------

@require_http_methods(["GET", "POST"])
@json_api
def spot_worker_list_create(request):
    if request.method == "GET":
        workers = SpotWorker.objects.all().order_by("id")

        # 「メンバーを追加＋」からの呼び出し時のみ付与されるオプションのフィルタ用パラメータ。
        # 通常のスポットワーカーCRUD画面（SpotWorkerCrud.vue）からの呼び出しでは指定されない。
        exclude_active_team = request.GET.get("exclude_active_team")
        year_month = request.GET.get("year_month")
        if exclude_active_team and year_month:
            team_id = _parse_int(exclude_active_team, "exclude_active_team")
            excluded_ids = _active_member_ref_ids(Member.KIND_SPOT_WORKER, team_id, year_month)
            workers = workers.exclude(id__in=excluded_ids)

        return JsonResponse({
            "spot_workers": [{"id": w.id, "name": w.name} for w in workers]
        })

    body = _json_body(request)
    _required(body, "name")
    worker = SpotWorker.objects.create(name=body["name"])
    return JsonResponse({"id": worker.id, "name": worker.name}, status=201)


@require_http_methods(["GET", "PUT", "DELETE"])
@json_api
def spot_worker_detail(request, spot_worker_id: int):
    worker = get_object_or_404(SpotWorker, pk=spot_worker_id)

    if request.method == "GET":
        return JsonResponse({"id": worker.id, "name": worker.name})

    if request.method == "PUT":
        body = _json_body(request)
        if "name" in body:
            worker.name = body["name"]
        worker.save()
        return JsonResponse({"id": worker.id, "name": worker.name})

    worker.delete()
    return JsonResponse({"status": "deleted", "id": spot_worker_id})


# ---------- 繰り返しイベント定義（履歴管理） ----------

@require_http_methods(["GET", "POST"])
@json_api
def event_definition_list_create(request):
    if request.method == "GET":
        defs = EventDefinition.objects.all().order_by("-effective_from")
        return JsonResponse({
            "event_definitions": [
                {
                    "id": d.id,
                    "target_type": d.target_type,
                    "target_id": d.target_id,
                    "title": d.title,
                    "recurrence_type": d.recurrence_type,
                    "recurrence_days": d.recurrence_days,
                    "effective_from": d.effective_from,
                    "effective_until": d.effective_until,
                }
                for d in defs
            ]
        })

    body = _json_body(request)
    _required(body, "target_type", "title", "recurrence_type", "effective_from")
    definition = EventDefinition.objects.create(
        target_type=body["target_type"],
        target_id=body.get("target_id"),
        title=body["title"],
        recurrence_type=body["recurrence_type"],
        recurrence_days=body.get("recurrence_days", []),
        effective_from=body["effective_from"],
        effective_until=body.get("effective_until"),
    )
    return JsonResponse({"id": definition.id}, status=201)


@require_http_methods(["PATCH"])
@json_api
def event_definition_close(request, definition_id: int):
    definition = get_object_or_404(EventDefinition, pk=definition_id)
    body = _json_body(request)
    _required(body, "effective_until")
    definition.effective_until = body["effective_until"]
    definition.save(update_fields=["effective_until", "updated_at"])
    return JsonResponse({"id": definition.id, "effective_until": definition.effective_until})


# ---------- メンバーを追加＋（3タブ共通: 追加＝即座にTeamMembershipを作成） ----------

def _get_or_create_member(member_kind: int, member_id: int) -> Member:
    member, _ = Member.objects.get_or_create(member_kind=member_kind, member_id=member_id)
    return member


def _next_order(team_id: int) -> int:
    """このチームの現在の最大orderの次の値（＝末尾）を返す。"""
    max_order = TeamMembership.objects.filter(
        team_id=team_id, order__isnull=False
    ).aggregate(Max("order"))["order__max"]
    return (max_order if max_order is not None else -1) + 1


@require_http_methods(["POST"])
@json_api
def team_membership_create(request):
    """
    「メンバーを追加＋」の「職員」タブ・「スポット（指名）」タブから呼ばれる。
    指定されたStaff/SpotWorkerに対応するMemberを取得(無ければ作成)し、
    TeamMembership(start_date=当日, end_date=無期限)を即座に作成する。
    既に有効な所属が存在する場合は何もしない（重複作成しない）。

    request body: {"team_id": 1, "member_kind": 0, "member_id": 101}
    """
    body = _json_body(request)
    _required(body, "team_id", "member_kind", "member_id")
    team_id = body["team_id"]
    member_kind = body["member_kind"]
    member_id = body["member_id"]

    # team_id も検証する。未検証のままTeamMembershipを作るとFK違反で500になり、
    # Staff/SpotWorkerだけを検証していた従来の扱いと不統一だったため揃える。
    _ensure_exists(Team, team_id, "team id")

    if member_kind == Member.KIND_STAFF and not Staff.objects.filter(pk=member_id).exists():
        return JsonResponse({"error": f"staff id={member_id} not found"}, status=400)
    if member_kind == Member.KIND_SPOT_WORKER and not SpotWorker.objects.filter(pk=member_id).exists():
        return JsonResponse({"error": f"spot_worker id={member_id} not found"}, status=400)

    member = _get_or_create_member(member_kind, member_id)

    today = date.today()
    already_active = TeamMembership.objects.filter(team_id=team_id, member=member, is_deleted=False).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).exists()

    if not already_active:
        TeamMembership.objects.create(
            team_id=team_id, member=member, start_date=today, end_date=None,
            order=_next_order(team_id),
        )

    return JsonResponse({"status": "success", "member_id": member.id})


@require_http_methods(["POST"])
@json_api
def team_membership_create_recruitment_slots(request):
    """
    「メンバーを追加＋」の「スポット（募集）」タブから呼ばれる。
    指定人数分の RecruitmentSlot（team+year_month内で連番）を新規作成し、
    それぞれに対応するMember・TeamMembershipも即座に作成する。

    request body: {"team_id": 1, "year_month": "2026-07", "count": 3}
    """
    body = _json_body(request)
    _required(body, "team_id", "year_month", "count")
    team_id = body["team_id"]
    year_month = body["year_month"]
    count = _parse_int(body["count"], "count")

    if count <= 0:
        return JsonResponse({"error": "count must be positive"}, status=400)

    _ensure_exists(Team, team_id, "team id")
    _parse_year_month(year_month)

    today = date.today()
    created_slots = []

    with transaction.atomic():
        current_max = RecruitmentSlot.objects.filter(
            team_id=team_id, year_month=year_month
        ).order_by("-slot_number").values_list("slot_number", flat=True).first() or 0
        next_order = _next_order(team_id)

        for i in range(1, count + 1):
            slot = RecruitmentSlot.objects.create(
                team_id=team_id, year_month=year_month, slot_number=current_max + i
            )
            member = _get_or_create_member(Member.KIND_RECRUITMENT_SLOT, slot.id)
            TeamMembership.objects.create(
                team_id=team_id, member=member, start_date=today, end_date=None,
                order=next_order + (i - 1),
            )
            created_slots.append(slot.slot_number)

    return JsonResponse({"status": "success", "created_slot_numbers": created_slots})


# ---------- シフト保存（保存ボタン押下時の一括反映） ----------

@require_http_methods(["POST"])
@json_api
def shifts_bulk_save(request):
    """
    保存ボタン押下時に、フロントのメモリ上に溜まった変更差分をまとめて1回で受け取り、
    Django DB（wsft_shifts テーブル）へ反映する。FastAPI は経由しない。

    「1回の保存操作＝1チーム・1月のシートに対する変更」という業務制約に合わせ、
    team_id はリクエスト直下に1つだけ持たせる（各change項目には含めない）。

    request body:
    {
      "team_id": 3,
      "changes": [
        {"member_id": 55, "date": "2026-07-01", "shift_type": "日1"},
        ...
      ]
    }

    シフト値が空文字("")の変更は「未定に戻す」＝レコード削除として扱う。
    """
    body = _json_body(request)
    team_id = body.get("team_id")
    changes = body.get("changes", [])

    if team_id is None:
        return JsonResponse({"error": "team_id is required"}, status=400)
    if not changes:
        return JsonResponse({"error": "no changes"}, status=400)

    team = Team.objects.filter(pk=team_id).first()
    if team is None:
        return JsonResponse({"error": f"team_id={team_id} not found"}, status=400)

    # 勤務タイプマスタとの名称一致チェック用（対象チームが属するグループのマスタのみを許可）
    valid_shift_type_names = set(
        WorkShiftType.objects.filter(group_id=team.group_id).values_list("name", flat=True)
    )

    saved = 0
    errors = []

    with transaction.atomic():
        for change in changes:
            try:
                member_id = change["member_id"]
                shift_date = change["date"]
                shift_type = change["shift_type"]
            except KeyError:
                errors.append({"change": change, "error": "member_id/date/shift_type is required"})
                continue

            if not Member.objects.filter(pk=member_id).exists():
                errors.append({"change": change, "error": f"member_id={member_id} not found"})
                continue

            if shift_type != "" and shift_type not in valid_shift_type_names:
                errors.append({"change": change, "error": f"shift_type={shift_type!r} は勤務タイプマスタに存在しません"})
                continue

            if shift_type == "":
                # セルを「未定」に戻した場合はレコード削除として扱う
                Shift.objects.filter(member_id=member_id, date=shift_date).delete()
            else:
                # 保存時点のTeamMembership.orderをスナップショットしてShift.orderへ書き込む。
                # 過去月表示時は、生きたマスターではなくこの凍結値を使う（9節の設計原則）。
                membership = TeamMembership.objects.filter(
                    team_id=team_id, member_id=member_id, is_deleted=False
                ).filter(
                    Q(end_date__isnull=True) | Q(end_date__gte=shift_date)
                ).order_by("-start_date").first()
                order_snapshot = membership.order if membership else None

                Shift.objects.update_or_create(
                    member_id=member_id,
                    date=shift_date,
                    # 論理削除(deleted_at)済みの行に再度シフトを入力した場合、
                    # ここでdeleted_atがNoneに戻る（＝実質的な復元導線として機能する）
                    defaults={
                        "shift_type": shift_type,
                        "team": team_id,
                        "deleted_at": None,
                        "order": order_snapshot,
                    },
                )
            saved += 1

    return JsonResponse({"status": "success", "saved": saved, "errors": errors})


@require_http_methods(["POST"])
@json_api
def shift_requirements_bulk_save(request):
    """
    予定数タブ(F2)の保存ボタン押下時に、フロントのメモリ上に溜まった変更差分を
    まとめて1回で受け取り、Django DB（wsft_shift_requirements テーブル）へ反映する。
    shifts_bulk_save と同じ「案B」の考え方（team_idはリクエスト直下に1つだけ）。

    request body:
    {
      "team_id": 3,
      "changes": [
        {"work_shift_type_id": 12, "date": "2026-07-01", "required_count": 2},
        ...
      ]
    }
    """
    body = _json_body(request)
    team_id = body.get("team_id")
    changes = body.get("changes", [])

    if team_id is None:
        return JsonResponse({"error": "team_id is required"}, status=400)
    if not changes:
        return JsonResponse({"error": "no changes"}, status=400)

    team = Team.objects.filter(pk=team_id).first()
    if team is None:
        return JsonResponse({"error": f"team_id={team_id} not found"}, status=400)

    # 対象チームが属するグループの勤務タイプのみ許可
    valid_type_ids = set(
        WorkShiftType.objects.filter(group_id=team.group_id).values_list("id", flat=True)
    )

    saved = 0
    errors = []

    with transaction.atomic():
        for change in changes:
            try:
                work_shift_type_id = change["work_shift_type_id"]
                req_date = change["date"]
                required_count = change["required_count"]
            except KeyError:
                errors.append({"change": change, "error": "work_shift_type_id/date/required_count is required"})
                continue

            if work_shift_type_id not in valid_type_ids:
                errors.append({
                    "change": change,
                    "error": f"work_shift_type_id={work_shift_type_id} は対象グループの勤務タイプではありません",
                })
                continue

            ShiftRequirement.objects.update_or_create(
                team_id=team_id,
                date=req_date,
                work_shift_type_id=work_shift_type_id,
                defaults={"required_count": required_count},
            )
            saved += 1

    return JsonResponse({"status": "success", "saved": saved, "errors": errors})

@require_http_methods(["POST"])
@json_api
def team_membership_delete(request, membership_id: int):
    """
    「×」ボタン押下時に呼ばれる。指定されたTeamMembership行の is_deleted を True にする。

    - start_date/end_date（実際の所属期間の事実）には一切触れない
    - Shiftレコード（シフト実績の値）にも一切触れない。復元時にそのまま使えるよう温存する
    - 対象は「×」を押した行そのもの（membership_id）に限定する。同一メンバーが複数の
      TeamMembership区間を持っていても、他の区間には影響しない
    """
    membership = get_object_or_404(TeamMembership, pk=membership_id)
    membership.is_deleted = True
    membership.save(update_fields=["is_deleted"])
    return JsonResponse({"status": "success", "membership_id": membership.id})


# ---------- チーム内のメンバー並び順（＝ドラッグ。TeamMembership.orderへ統合） ----------

@require_http_methods(["POST"])
@json_api
def team_member_order_update(request, team_id: int):
    """
    ドラッグ確定時に、現在有効なTeamMembership行のorderをまとめて更新する。

    request body: {"member_order": [55, 61, 48, ...]}  (先頭が一番上に表示されるメンバー)

    注意: 過去月のシートで操作した場合でも、この処理は「現在有効な所属」のorderを
    書き換える（＝マスターに影響する）。過去月限定の並び替え（Shift.orderのみ更新）は
    今回未実装（9節「今後の課題」を参照）。
    """
    body = _json_body(request)
    member_order = body.get("member_order", [])
    today = date.today()

    with transaction.atomic():
        for index, member_id in enumerate(member_order):
            TeamMembership.objects.filter(
                team_id=team_id, member_id=member_id, is_deleted=False
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=today)
            ).update(order=index)

    return JsonResponse({"status": "success", "count": len(member_order)})