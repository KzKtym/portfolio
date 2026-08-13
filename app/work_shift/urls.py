# app/work_shift/urls.py
"""
work_shift アプリのURLconf。config/urls.py 側で以下のように include する:
    path("shift/", include("app.work_shift.urls"))

このモジュール自体を "/shift/" 直下に丸ごとマウントする構成に変更した（2026-07-07）。
従来は "/shift/api/v1/" をconfig/urls.py側で直接指定していたが、SPA本体（"/shift/"）も
同じ work_shift 名前空間（app_name="work_shift"）に含めたかったため、CRUD等のAPIパス側に
"api/v1/" プレフィックスを付け替え、ここに集約した（config.jsonの url_name: "work_shift:spa"
を解決できるようにするため）。

すべてのビューは login_required + キャッシュ禁止/クローラ拒否ヘッダー
（home.decorators.no_cache_no_index）でラップする。個々のビュー関数側では実装しない
（デモの公開範囲がごく少数であっても、ログイン必須画面として一律に扱う方針。確定仕様）。
"""
from django.contrib.auth.decorators import login_required
from django.urls import path

from app.common.decorators import no_cache_no_index

from . import spa_views, views

app_name = "work_shift"


def protected(view):
    """login_required + no_cache_no_index を一律に適用するための小さなヘルパー。"""
    return no_cache_no_index(login_required(view))


urlpatterns = [
    # SPA本体（Vueのビルド成果物をそのまま返す。spa_views.spa_index参照）
    path("", protected(spa_views.spa_index), name="spa"),

    # CSRFトークン発行（csrftoken クッキーのSet-Cookieのみが目的）。
    # npm run dev では index.html を Vite が配信し spa_index を通らないため、
    # フロントが書き込み前にこれを叩いてクッキーを得る（src/lib/api.ts 参照）。
    path("api/v1/csrf/", protected(spa_views.csrf_token), name="csrf-token"),

    # グループ CRUD（簡易画面用）
    path("api/v1/groupes/", protected(views.groupe_list_create), name="groupe-list-create"),
    path("api/v1/groupes/<int:groupe_id>/", protected(views.groupe_detail), name="groupe-detail"),

    # チーム（参照専用。名称変更(PUT)のみ📝ボタン用に追加。作成/削除は今回のスコープ外）
    path("api/v1/teams/", protected(views.team_list), name="team-list"),
    path("api/v1/teams/<int:team_id>/", protected(views.team_detail), name="team-detail"),
    path(
        "api/v1/teams/<int:team_id>/available-year-months/",
        protected(views.team_available_year_months),
        name="team-available-year-months",
    ),

    # 職員 CRUD（簡易画面用）
    path("api/v1/staffs/", protected(views.staff_list_create), name="staff-list-create"),
    path("api/v1/staffs/<int:staff_id>/", protected(views.staff_detail), name="staff-detail"),

    # 勤務タイプ CRUD（簡易画面用。サイドメニュー「デモ用管理」→「勤務タイプ」。グループ単位）
    path(
        "api/v1/work-shift-types/",
        protected(views.work_shift_type_list_create),
        name="work-shift-type-list-create",
    ),
    path(
        "api/v1/work-shift-types/<int:work_shift_type_id>/",
        protected(views.work_shift_type_detail),
        name="work-shift-type-detail",
    ),

    # スポットワーカー CRUD（簡易画面用。サイドメニュー「デモ用管理」→「スポット」）
    path("api/v1/spot-workers/", protected(views.spot_worker_list_create), name="spot-worker-list-create"),
    path(
        "api/v1/spot-workers/<int:spot_worker_id>/",
        protected(views.spot_worker_detail),
        name="spot-worker-detail",
    ),

    # 繰り返しイベント定義（履歴管理）
    path(
        "api/v1/event-definitions/",
        protected(views.event_definition_list_create),
        name="event-definition-list-create",
    ),
    path(
        "api/v1/event-definitions/<int:definition_id>/close/",
        protected(views.event_definition_close),
        name="event-definition-close",
    ),

    # メンバーを追加＋（職員/スポット指名タブ共通、およびスポット募集タブ）
    path("api/v1/team-memberships/", protected(views.team_membership_create), name="team-membership-create"),
    path(
        "api/v1/team-memberships/recruitment-slots/",
        protected(views.team_membership_create_recruitment_slots),
        name="team-membership-create-recruitment-slots",
    ),

    # シフト保存（保存ボタン押下時の一括反映。team_idはリクエスト直下に1つだけ持たせる）
    path("api/v1/shifts/save/", protected(views.shifts_bulk_save), name="shifts-bulk-save"),
    path(
        "api/v1/shift-requirements/save/",
        protected(views.shift_requirements_bulk_save),
        name="shift-requirements-bulk-save",
    ),

    # メンバー削除（×押下で即時反映。対象TeamMembership行のis_deletedを立てるだけ）
    path(
        "api/v1/team-memberships/<int:membership_id>/delete/",
        protected(views.team_membership_delete),
        name="team-membership-delete",
    ),

    # チーム内のメンバー並び順（＝ドラッグ。TeamMembership.orderへ統合済み）
    path(
        "api/v1/teams/<int:team_id>/member-order/",
        protected(views.team_member_order_update),
        name="team-member-order-update",
    ),
]