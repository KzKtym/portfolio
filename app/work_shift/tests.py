# app/work_shift/tests.py
"""
work_shift のテスト。

方針（PoC・公開デモという前提に基づく。詳細は設計判断の記録を参照）:
- 「仕様が変わっても不変な性質」に絞る。ビジネスロジックの精度は追わない。
    * 認証境界（全エンドポイントがログイン必須であること）
    * CSRF保護が効いていること
    * 不正入力で 500 を返さないこと
    * 純ロジック（services.py）の正しさ
    * データ整合性（PROTECT / CASCADE / unique_together）
- 意図的に書かないもの: __str__ / デフォルト値 / CRUDの詳細な戻り値検証
  （仕様変更のたびに壊れるだけで何も守らないため）
- main.py（FastAPI・別プロセス）/ db.py / schemas.py / seed_work_shift.py は対象外。

前提: Phase 2/3 修正後のコード
  - @csrf_exempt は存在しない（CsrfViewMiddleware の標準保護）
  - エラーレスポンスは {"error": "..."} に統一
  - 不正入力は 400（旧実装では 500 になっていた）

実行: python manage.py test app.work_shift --settings=config.settings_test
"""
import json
import urllib.error
from datetime import date
from unittest import mock

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from . import spa_views
from . import urls as work_shift_urls
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
from .services import generate_events_for_month, is_rule_effective


# ──────────────────────────────────────────────
# 共通ヘルパー
# ──────────────────────────────────────────────

def _make_user(username="tester", password="test-pass-1234"):
    return User.objects.create_user(username=username, password=password)


def _make_groupe(name="さくら"):
    return Groupe.objects.create(name=name)


def _make_team(group=None, name="1F"):
    return Team.objects.create(name=name, group=group or _make_groupe())


def _make_work_shift_type(group, name="日1", order=0, **kwargs):
    defaults = {"color": "#7cb342"}
    defaults.update(kwargs)
    return WorkShiftType.objects.create(group=group, name=name, order=order, **defaults)


def _make_staff(name="山田"):
    return Staff.objects.create(name=name)


def _make_spot_worker(name="鈴木"):
    return SpotWorker.objects.create(name=name)


def _make_member(kind=Member.KIND_STAFF, ref_id=1):
    return Member.objects.create(member_kind=kind, member_id=ref_id)


def _make_membership(team, member, start_date=None, end_date=None, **kwargs):
    return TeamMembership.objects.create(
        team=team,
        member=member,
        start_date=start_date or date(2026, 1, 1),
        end_date=end_date,
        **kwargs,
    )


def _all_url_names():
    """work_shift の urlpatterns から (name, url) を列挙する。

    URLを1本ずつ手で列挙せず走査することで、エンドポイントを追加したときに
    protected() の付け忘れを自動で検出できる（これが本テストの主目的）。
    """
    for pattern in work_shift_urls.urlpatterns:
        kwargs = {name: 1 for name in pattern.pattern.converters}
        yield pattern.name, reverse(f"work_shift:{pattern.name}", kwargs=kwargs)


# ═══════════════════════════════════════════════════════════════
# 認証境界
# ═══════════════════════════════════════════════════════════════

class AuthBoundaryTest(TestCase):
    """全エンドポイントがログイン必須であることを urlpatterns の走査で検証する"""

    def test_all_endpoints_require_login(self):
        """未ログインでは全エンドポイントがログイン画面へリダイレクトする"""
        checked = 0
        for name, url in _all_url_names():
            with self.subTest(name=name, url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 302, msg=f"{name} が302を返さない")
                self.assertTrue(
                    response["Location"].startswith("/accounts/login/"),
                    msg=f"{name} のリダイレクト先が想定外: {response['Location']}",
                )
            checked += 1

        # 走査自体が空振りしていないことの確認
        self.assertGreater(checked, 0)

    def test_urlpatterns_are_not_empty(self):
        """走査対象のURLが実際に存在する（テストの空振り防止）"""
        self.assertGreaterEqual(len(work_shift_urls.urlpatterns), 15)

    def test_fastapi_proxy_requires_login(self):
        """config/urls.py 側に登録されたプロキシもログイン必須"""
        response = self.client.get(reverse("work_shift_fastapi_proxy"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_login_redirect_preserves_next(self):
        """リダイレクトURLに next が付く"""
        response = self.client.get(reverse("work_shift:team-list"))

        self.assertIn("next=", response["Location"])


class NoCacheNoIndexHeaderTest(TestCase):
    """protected() が付与するキャッシュ抑制・クローラ拒否ヘッダーを検証する"""

    def setUp(self):
        self.client.force_login(_make_user())

    def test_api_has_no_cache_headers(self):
        """APIレスポンスにキャッシュ抑制ヘッダーが付く"""
        response = self.client.get(reverse("work_shift:team-list"))

        self.assertIn("no-store", response["Cache-Control"])

    def test_api_has_no_index_header(self):
        """APIレスポンスにクローラ拒否ヘッダーが付く"""
        response = self.client.get(reverse("work_shift:team-list"))

        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_spa_index_has_no_cache_headers(self):
        """SPA本体にもキャッシュ抑制ヘッダーが付く"""
        with mock.patch.object(spa_views, "_SPA_INDEX_HTML_PATH") as path:
            path.read_text.return_value = "<html></html>"
            response = self.client.get(reverse("work_shift:spa"))

        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")


# ═══════════════════════════════════════════════════════════════
# CSRF
# ═══════════════════════════════════════════════════════════════

class CsrfProtectionTest(TestCase):
    """CSRF保護が有効であることを検証する（@csrf_exempt の再混入を検出する）"""

    def setUp(self):
        # Djangoのテストクライアントは既定でCSRF検証を無効化するため、明示的に有効化する
        self.client = Client(enforce_csrf_checks=True)
        self.user = _make_user()
        self.client.force_login(self.user)

    def _csrf_token(self):
        """CSRFトークン発行エンドポイントを叩いてクッキーからトークンを取得する"""
        self.client.get(reverse("work_shift:csrf-token"))
        return self.client.cookies["csrftoken"].value

    # ──────────────────────────────────────────────
    # トークン発行
    # ──────────────────────────────────────────────

    def test_csrf_endpoint_sets_cookie(self):
        """/shift/api/v1/csrf/ が csrftoken クッキーを発行する"""
        response = self.client.get(reverse("work_shift:csrf-token"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", self.client.cookies)
        self.assertTrue(self.client.cookies["csrftoken"].value)

    def test_csrf_endpoint_rejects_post(self):
        """/shift/api/v1/csrf/ はGET専用（トークンを付けてもPOSTは405）"""
        token = self._csrf_token()
        response = self.client.post(
            reverse("work_shift:csrf-token"), HTTP_X_CSRFTOKEN=token
        )

        self.assertEqual(response.status_code, 405)

    def test_spa_index_sets_csrf_cookie(self):
        """SPA本体の配信時にも csrftoken クッキーが発行される（本番配信時の経路）"""
        with mock.patch.object(spa_views, "_SPA_INDEX_HTML_PATH") as path:
            path.read_text.return_value = "<html></html>"
            self.client.get(reverse("work_shift:spa"))

        self.assertIn("csrftoken", self.client.cookies)

    # ──────────────────────────────────────────────
    # 書き込みの保護
    # ──────────────────────────────────────────────

    def test_post_without_token_is_rejected(self):
        """トークン無しのPOSTは403"""
        response = self.client.post(
            reverse("work_shift:groupe-list-create"),
            data=json.dumps({"name": "新グループ"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Groupe.objects.count(), 0)

    def test_post_with_token_succeeds(self):
        """トークン有りのPOSTは成功する"""
        token = self._csrf_token()

        response = self.client.post(
            reverse("work_shift:groupe-list-create"),
            data=json.dumps({"name": "新グループ"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Groupe.objects.filter(name="新グループ").exists())

    def test_put_without_token_is_rejected(self):
        """トークン無しのPUTは403"""
        groupe = _make_groupe()

        response = self.client.put(
            reverse("work_shift:groupe-detail", kwargs={"groupe_id": groupe.id}),
            data=json.dumps({"name": "変更後"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        groupe.refresh_from_db()
        self.assertEqual(groupe.name, "さくら")

    def test_delete_without_token_is_rejected(self):
        """トークン無しのDELETEは403"""
        staff = _make_staff()

        response = self.client.delete(
            reverse("work_shift:staff-detail", kwargs={"staff_id": staff.id})
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Staff.objects.filter(pk=staff.pk).exists())

    def test_get_does_not_require_token(self):
        """GETはCSRF不要"""
        response = self.client.get(reverse("work_shift:team-list"))

        self.assertEqual(response.status_code, 200)


# ═══════════════════════════════════════════════════════════════
# 入力の頑健性（500を返さないこと）
# ═══════════════════════════════════════════════════════════════

class InputRobustnessTest(TestCase):
    """不正な入力に対して 500 ではなく 400 を返すことを検証する"""

    def setUp(self):
        self.client.force_login(_make_user())
        self.groupe = _make_groupe()
        self.team = _make_team(group=self.groupe)

    def _post(self, name, body, **kwargs):
        return self.client.post(
            reverse(f"work_shift:{name}", kwargs=kwargs),
            data=body if isinstance(body, str) else json.dumps(body),
            content_type="application/json",
        )

    # ──────────────────────────────────────────────
    # 壊れたJSON
    # ──────────────────────────────────────────────

    def test_broken_json_returns_400(self):
        """壊れたJSONは400"""
        response = self._post("groupe-list-create", "{invalid")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid JSON")

    def test_broken_json_on_all_write_endpoints(self):
        """主要な書き込みエンドポイントすべてで壊れたJSONが400になる"""
        targets = [
            ("groupe-list-create", {}),
            ("staff-list-create", {}),
            ("spot-worker-list-create", {}),
            ("work-shift-type-list-create", {}),
            ("event-definition-list-create", {}),
            ("team-membership-create", {}),
            ("team-membership-create-recruitment-slots", {}),
            ("shifts-bulk-save", {}),
            ("shift-requirements-bulk-save", {}),
            ("team-member-order-update", {"team_id": 1}),
        ]
        for name, kwargs in targets:
            with self.subTest(endpoint=name):
                response = self._post(name, "{invalid", **kwargs)

                self.assertEqual(response.status_code, 400, msg=f"{name} が400を返さない")

    def test_non_object_json_returns_400(self):
        """JSONの配列やスカラーは400（dictを期待している）"""
        response = self._post("groupe-list-create", "[1, 2, 3]")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "body must be a JSON object")

    # ──────────────────────────────────────────────
    # 必須キーの欠落
    # ──────────────────────────────────────────────

    def test_missing_name_returns_400(self):
        """name 欠落は400"""
        response = self._post("groupe-list-create", {})

        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.json()["error"])
        self.assertEqual(Groupe.objects.count(), 1)  # setUp の1件のみ

    def test_missing_staff_name_returns_400(self):
        """職員の name 欠落は400"""
        response = self._post("staff-list-create", {"default_team": 1})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Staff.objects.count(), 0)

    def test_missing_spot_worker_name_returns_400(self):
        """スポットワーカーの name 欠落は400"""
        response = self._post("spot-worker-list-create", {})

        self.assertEqual(response.status_code, 400)

    def test_missing_event_definition_keys_returns_400(self):
        """イベント定義の必須キー欠落は400"""
        response = self._post("event-definition-list-create", {"title": "会議"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(EventDefinition.objects.count(), 0)

    def test_missing_effective_until_returns_400(self):
        """世代クローズの effective_until 欠落は400"""
        definition = EventDefinition.objects.create(
            target_type="facility", title="会議", recurrence_type="weekly",
            recurrence_days=["MON"], effective_from="2026-01",
        )

        response = self.client.patch(
            reverse("work_shift:event-definition-close", kwargs={"definition_id": definition.id}),
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

    def test_missing_membership_keys_returns_400(self):
        """メンバー追加の必須キー欠落は400"""
        response = self._post("team-membership-create", {"team_id": self.team.id})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(TeamMembership.objects.count(), 0)

    # ──────────────────────────────────────────────
    # 存在しないFK
    # ──────────────────────────────────────────────

    def test_unknown_team_on_membership_returns_400(self):
        """存在しない team_id でのメンバー追加は400（FK違反による500ではない）"""
        staff = _make_staff()

        response = self._post(
            "team-membership-create",
            {"team_id": 99999, "member_kind": Member.KIND_STAFF, "member_id": staff.id},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("99999", response.json()["error"])
        self.assertEqual(TeamMembership.objects.count(), 0)

    def test_unknown_staff_returns_400(self):
        """存在しない職員IDは400"""
        response = self._post(
            "team-membership-create",
            {"team_id": self.team.id, "member_kind": Member.KIND_STAFF, "member_id": 99999},
        )

        self.assertEqual(response.status_code, 400)

    def test_unknown_spot_worker_returns_400(self):
        """存在しないスポットワーカーIDは400"""
        response = self._post(
            "team-membership-create",
            {"team_id": self.team.id, "member_kind": Member.KIND_SPOT_WORKER, "member_id": 99999},
        )

        self.assertEqual(response.status_code, 400)

    def test_unknown_team_on_recruitment_slots_returns_400(self):
        """募集枠作成で存在しない team_id は400"""
        response = self._post(
            "team-membership-create-recruitment-slots",
            {"team_id": 99999, "year_month": "2026-07", "count": 2},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(RecruitmentSlot.objects.count(), 0)

    def test_unknown_group_on_work_shift_type_returns_400(self):
        """存在しない group_id での勤務タイプ作成は400"""
        response = self._post(
            "work-shift-type-list-create", {"name": "日1", "group_id": 99999}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(WorkShiftType.objects.count(), 0)

    def test_unknown_team_on_shifts_save_returns_400(self):
        """シフト保存で存在しない team_id は400"""
        response = self._post(
            "shifts-bulk-save",
            {"team_id": 99999, "changes": [{"member_id": 1, "date": "2026-07-01", "shift_type": "日1"}]},
        )

        self.assertEqual(response.status_code, 400)

    # ──────────────────────────────────────────────
    # 型・書式の不正
    # ──────────────────────────────────────────────

    def test_non_numeric_count_returns_400(self):
        """count が数値でなければ400"""
        response = self._post(
            "team-membership-create-recruitment-slots",
            {"team_id": self.team.id, "year_month": "2026-07", "count": "abc"},
        )

        self.assertEqual(response.status_code, 400)

    def test_zero_count_returns_400(self):
        """count が0以下は400"""
        response = self._post(
            "team-membership-create-recruitment-slots",
            {"team_id": self.team.id, "year_month": "2026-07", "count": 0},
        )

        self.assertEqual(response.status_code, 400)

    def test_malformed_year_month_returns_400(self):
        """year_month の書式不正は400"""
        response = self._post(
            "team-membership-create-recruitment-slots",
            {"team_id": self.team.id, "year_month": "2026/07", "count": 1},
        )

        self.assertEqual(response.status_code, 400)

    def test_non_numeric_exclude_active_team_returns_400(self):
        """職員一覧の exclude_active_team が数値でなければ400"""
        response = self.client.get(
            reverse("work_shift:staff-list-create"),
            {"exclude_active_team": "abc", "year_month": "2026-07"},
        )

        self.assertEqual(response.status_code, 400)

    def test_malformed_year_month_on_staff_list_returns_400(self):
        """職員一覧の year_month の書式不正は400"""
        response = self.client.get(
            reverse("work_shift:staff-list-create"),
            {"exclude_active_team": str(self.team.id), "year_month": "bad"},
        )

        self.assertEqual(response.status_code, 400)

    def test_invalid_time_format_returns_400(self):
        """勤務タイプの時刻書式不正は400"""
        response = self._post(
            "work-shift-type-list-create",
            {"name": "日1", "group_id": self.groupe.id, "start_time": "9時"},
        )

        self.assertEqual(response.status_code, 400)

    # ──────────────────────────────────────────────
    # エラー形の統一
    # ──────────────────────────────────────────────

    def test_error_shape_is_unified(self):
        """400のレスポンスは常に {"error": "..."} 形式（status キーを持たない）"""
        cases = [
            ("groupe-list-create", {}, {}),
            ("staff-list-create", {}, {}),
            ("team-membership-create", {}, {}),
            ("shifts-bulk-save", {"team_id": None}, {}),
        ]
        for name, body, kwargs in cases:
            with self.subTest(endpoint=name):
                data = self._post(name, body, **kwargs).json()

                self.assertIn("error", data, msg=f"{name} に error キーがない")
                self.assertNotIn("status", data, msg=f"{name} に status キーが残っている")

    def test_no_changes_returns_unified_error(self):
        """changes が空のときも統一形式で400"""
        response = self._post("shifts-bulk-save", {"team_id": self.team.id, "changes": []})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
        self.assertNotIn("status", response.json())


# ═══════════════════════════════════════════════════════════════
# 純ロジック: services.py
# ═══════════════════════════════════════════════════════════════

class IsRuleEffectiveTest(SimpleTestCase):
    """is_rule_effective のテスト（"YYYY-MM" の半開区間 [from, until) 判定）"""

    # ──────────────────────────────────────────────
    # 無期限（until = None）
    # ──────────────────────────────────────────────

    def test_open_ended_after_from(self):
        """開始以降・無期限なら有効"""
        self.assertTrue(is_rule_effective("2026-07", "2026-01", None))

    def test_open_ended_before_from(self):
        """開始より前なら無効"""
        self.assertFalse(is_rule_effective("2025-12", "2026-01", None))

    # ──────────────────────────────────────────────
    # 境界値（半開区間）
    # ──────────────────────────────────────────────

    def test_same_month_as_from_is_effective(self):
        """開始月ちょうどは有効（区間に含む）"""
        self.assertTrue(is_rule_effective("2026-01", "2026-01", None))

    def test_same_month_as_until_is_not_effective(self):
        """終了月ちょうどは無効（半開区間なので含まない）"""
        self.assertFalse(is_rule_effective("2026-06", "2026-01", "2026-06"))

    def test_month_before_until_is_effective(self):
        """終了月の1つ前は有効"""
        self.assertTrue(is_rule_effective("2026-05", "2026-01", "2026-06"))

    def test_after_until_is_not_effective(self):
        """終了月より後は無効"""
        self.assertFalse(is_rule_effective("2026-07", "2026-01", "2026-06"))

    # ──────────────────────────────────────────────
    # 辞書順＝時系列となること
    # ──────────────────────────────────────────────

    def test_year_boundary(self):
        """年をまたぐ比較が正しい（ゼロ埋めによる辞書順比較）"""
        self.assertTrue(is_rule_effective("2026-01", "2025-12", "2026-02"))
        self.assertFalse(is_rule_effective("2025-11", "2025-12", "2026-02"))

    def test_single_digit_month_is_zero_padded(self):
        """1桁月がゼロ埋めされていれば 2026-09 < 2026-10 が成立する"""
        self.assertTrue(is_rule_effective("2026-09", "2026-01", "2026-10"))
        self.assertFalse(is_rule_effective("2026-10", "2026-01", "2026-10"))

    def test_empty_range(self):
        """from == until は常に無効（空区間）"""
        self.assertFalse(is_rule_effective("2026-01", "2026-01", "2026-01"))


class GenerateEventsForMonthTest(SimpleTestCase):
    """generate_events_for_month のテスト"""

    # ──────────────────────────────────────────────
    # 毎週ルール
    # ──────────────────────────────────────────────

    def test_weekly_single_day(self):
        """毎週月曜が正しく展開される"""
        records = generate_events_for_month(2026, 7, "朝礼", "weekly", ["MON"])

        # 2026年7月の月曜: 6, 13, 20, 27
        self.assertEqual([r.date for r in records],
                         ["2026-07-06", "2026-07-13", "2026-07-20", "2026-07-27"])

    def test_weekly_multiple_days(self):
        """複数曜日を指定できる"""
        records = generate_events_for_month(2026, 7, "会議", "weekly", ["MON", "WED"])

        self.assertEqual(len(records), 9)  # 月4回 + 水5回

    def test_records_are_sorted_by_date(self):
        """結果は日付昇順（1日から月末まで走査するため）"""
        records = generate_events_for_month(2026, 7, "会議", "weekly", ["WED", "MON"])

        dates = [r.date for r in records]
        self.assertEqual(dates, sorted(dates))

    def test_title_is_set(self):
        """全レコードにタイトルが入る"""
        records = generate_events_for_month(2026, 7, "朝礼", "weekly", ["MON"])

        self.assertTrue(all(r.title == "朝礼" for r in records))

    def test_date_is_iso_format(self):
        """日付は "YYYY-MM-DD" 形式"""
        records = generate_events_for_month(2026, 7, "朝礼", "weekly", ["MON"])

        self.assertEqual(records[0].date, "2026-07-06")

    # ──────────────────────────────────────────────
    # 月末の境界
    # ──────────────────────────────────────────────

    def test_month_end_31_days(self):
        """31日まである月の末日が含まれる"""
        records = generate_events_for_month(2026, 7, "x", "weekly", ["FRI"])

        # 2026-07-31 は金曜
        self.assertIn("2026-07-31", [r.date for r in records])

    def test_february_non_leap_year(self):
        """平年の2月は28日まで"""
        records = generate_events_for_month(2026, 2, "x", "weekly", ["SAT"])

        self.assertEqual([r.date for r in records],
                         ["2026-02-07", "2026-02-14", "2026-02-21", "2026-02-28"])

    def test_february_leap_year(self):
        """閏年の2月は29日まで含む"""
        records = generate_events_for_month(2028, 2, "x", "weekly", ["TUE"])

        self.assertIn("2028-02-29", [r.date for r in records])

    # ──────────────────────────────────────────────
    # 境界値・未実装
    # ──────────────────────────────────────────────

    def test_unknown_weekday_is_ignored(self):
        """未知の曜日コードは無視される"""
        records = generate_events_for_month(2026, 7, "x", "weekly", ["MON", "ZZZ"])

        self.assertEqual(len(records), 4)  # MONのみ

    def test_all_unknown_weekdays_gives_empty(self):
        """曜日コードが全て未知なら空"""
        self.assertEqual(generate_events_for_month(2026, 7, "x", "weekly", ["ZZZ"]), [])

    def test_empty_recurrence_days_gives_empty(self):
        """曜日指定が空なら空"""
        self.assertEqual(generate_events_for_month(2026, 7, "x", "weekly", []), [])

    def test_monthly_is_not_implemented(self):
        """monthly は未実装のため空を返す（今回スコープ外）"""
        self.assertEqual(generate_events_for_month(2026, 7, "x", "monthly", ["1"]), [])

    def test_unknown_recurrence_type_gives_empty(self):
        """未知の繰り返し種別は空"""
        self.assertEqual(generate_events_for_month(2026, 7, "x", "yearly", ["MON"]), [])


# ═══════════════════════════════════════════════════════════════
# データ整合性
# ═══════════════════════════════════════════════════════════════

class DataIntegrityTest(TestCase):
    """PROTECT / CASCADE / unique_together を検証する（データ破壊に直結するため）"""

    def setUp(self):
        self.groupe = _make_groupe()
        self.team = _make_team(group=self.groupe)

    # ──────────────────────────────────────────────
    # PROTECT
    # ──────────────────────────────────────────────

    def test_groupe_with_team_is_protected(self):
        """チームが属するグループは削除できない"""
        with self.assertRaises(ProtectedError):
            self.groupe.delete()

    def test_groupe_without_team_can_be_deleted(self):
        """チームが無いグループは削除できる"""
        empty = _make_groupe("空グループ")

        empty.delete()

        self.assertFalse(Groupe.objects.filter(pk=empty.pk).exists())

    # ──────────────────────────────────────────────
    # CASCADE
    # ──────────────────────────────────────────────

    def test_work_shift_type_cascades_from_groupe(self):
        """グループ削除で勤務タイプも消える"""
        empty = _make_groupe("空グループ")
        _make_work_shift_type(empty)

        empty.delete()

        self.assertEqual(WorkShiftType.objects.count(), 0)

    def test_membership_cascades_from_team(self):
        """チーム削除で所属も消える"""
        _make_membership(self.team, _make_member())

        self.team.delete()

        self.assertEqual(TeamMembership.objects.count(), 0)

    def test_shift_cascades_from_member(self):
        """メンバー削除でシフトも消える"""
        member = _make_member()
        Shift.objects.create(member=member, date=date(2026, 7, 1), shift_type="日1", team=self.team.id)

        member.delete()

        self.assertEqual(Shift.objects.count(), 0)

    # ──────────────────────────────────────────────
    # unique_together
    # ──────────────────────────────────────────────

    def test_member_kind_and_id_are_unique(self):
        """同一種別・同一参照IDのMemberは重複作成できない"""
        _make_member(Member.KIND_STAFF, 1)

        with self.assertRaises(IntegrityError):
            _make_member(Member.KIND_STAFF, 1)

    def test_same_ref_id_with_different_kind_is_allowed(self):
        """種別が違えば同じ参照IDでも作成できる（Staff.id と SpotWorker.id は独立）"""
        _make_member(Member.KIND_STAFF, 1)
        _make_member(Member.KIND_SPOT_WORKER, 1)

        self.assertEqual(Member.objects.count(), 2)

    def test_shift_member_and_date_are_unique(self):
        """同一メンバー・同一日のシフトは重複できない"""
        member = _make_member()
        Shift.objects.create(member=member, date=date(2026, 7, 1), shift_type="日1", team=self.team.id)

        with self.assertRaises(IntegrityError):
            Shift.objects.create(member=member, date=date(2026, 7, 1), shift_type="遅1", team=self.team.id)

    def test_recruitment_slot_number_is_unique_per_team_and_month(self):
        """チーム・年月内で募集枠の連番は一意"""
        RecruitmentSlot.objects.create(team=self.team, year_month="2026-07", slot_number=1)

        with self.assertRaises(IntegrityError):
            RecruitmentSlot.objects.create(team=self.team, year_month="2026-07", slot_number=1)

    def test_recruitment_slot_number_can_repeat_in_other_month(self):
        """年月が違えば同じ連番を使える"""
        RecruitmentSlot.objects.create(team=self.team, year_month="2026-07", slot_number=1)
        RecruitmentSlot.objects.create(team=self.team, year_month="2026-08", slot_number=1)

        self.assertEqual(RecruitmentSlot.objects.count(), 2)

    def test_shift_requirement_is_unique(self):
        """チーム・日付・勤務タイプの組み合わせは一意"""
        w = _make_work_shift_type(self.groupe)
        ShiftRequirement.objects.create(team=self.team, date=date(2026, 7, 1), work_shift_type=w, required_count=2)

        with self.assertRaises(IntegrityError):
            ShiftRequirement.objects.create(team=self.team, date=date(2026, 7, 1), work_shift_type=w, required_count=3)


class RecruitmentSlotNumberingTest(TestCase):
    """募集枠の連番採番を検証する（重複や欠番はシートの表示崩れに直結する）"""

    def setUp(self):
        self.client.force_login(_make_user())
        self.team = _make_team()
        self.url = reverse("work_shift:team-membership-create-recruitment-slots")

    def _create(self, count, year_month="2026-07"):
        return self.client.post(
            self.url,
            data=json.dumps({"team_id": self.team.id, "year_month": year_month, "count": count}),
            content_type="application/json",
        )

    def test_numbers_start_from_one(self):
        """最初の採番は1から"""
        response = self._create(3)

        self.assertEqual(response.json()["created_slot_numbers"], [1, 2, 3])

    def test_numbers_continue_from_max(self):
        """既存の最大値の次から続く"""
        self._create(2)

        response = self._create(2)

        self.assertEqual(response.json()["created_slot_numbers"], [3, 4])

    def test_numbering_is_per_year_month(self):
        """年月ごとに独立して採番される"""
        self._create(2, "2026-07")

        response = self._create(2, "2026-08")

        self.assertEqual(response.json()["created_slot_numbers"], [1, 2])

    def test_member_and_membership_are_created(self):
        """募集枠にMemberとTeamMembershipが同時に作られる"""
        self._create(2)

        self.assertEqual(Member.objects.filter(member_kind=Member.KIND_RECRUITMENT_SLOT).count(), 2)
        self.assertEqual(TeamMembership.objects.count(), 2)

    def test_order_is_sequential(self):
        """作成された所属のorderが連番になる"""
        self._create(3)

        orders = sorted(TeamMembership.objects.values_list("order", flat=True))
        self.assertEqual(orders, [0, 1, 2])


class ActiveMemberFilterTest(TestCase):
    """「メンバーを追加＋」の既追加メンバー除外を検証する

    Member.member_id（参照先のStaff.id等）と TeamMembership.member_id（Member.id）は
    別物であり、_active_member_ref_ids はこの2段変換を行う。取り違えやすい箇所のため検証する。
    """

    def setUp(self):
        self.client.force_login(_make_user())
        self.team = _make_team()
        self.staff = _make_staff("在籍者")
        self.member = _make_member(Member.KIND_STAFF, self.staff.id)
        self.url = reverse("work_shift:staff-list-create")

    def _list(self, **params):
        base = {"exclude_active_team": str(self.team.id), "year_month": "2026-07"}
        base.update(params)
        response = self.client.get(self.url, base)
        return [s["name"] for s in response.json()["staffs"]]

    def test_active_member_is_excluded(self):
        """対象月に有効な所属を持つ職員は除外される"""
        _make_membership(self.team, self.member, start_date=date(2026, 1, 1))

        self.assertNotIn("在籍者", self._list())

    def test_deleted_membership_is_not_excluded(self):
        """論理削除された所属は除外対象にならない（再選択できる）"""
        _make_membership(self.team, self.member, start_date=date(2026, 1, 1), is_deleted=True)

        self.assertIn("在籍者", self._list())

    def test_ended_membership_is_not_excluded(self):
        """対象月より前に終了した所属は除外対象にならない"""
        _make_membership(self.team, self.member,
                         start_date=date(2026, 1, 1), end_date=date(2026, 6, 30))

        self.assertIn("在籍者", self._list())

    def test_membership_ending_within_month_is_excluded(self):
        """対象月と期間が重なっていれば除外される（境界値）"""
        _make_membership(self.team, self.member,
                         start_date=date(2026, 1, 1), end_date=date(2026, 7, 1))

        self.assertNotIn("在籍者", self._list())

    def test_future_membership_is_excluded(self):
        """対象月の末日以前に開始する所属は除外される（境界値）"""
        _make_membership(self.team, self.member, start_date=date(2026, 7, 31))

        self.assertNotIn("在籍者", self._list())

    def test_membership_starting_after_month_is_not_excluded(self):
        """対象月より後に開始する所属は除外されない"""
        _make_membership(self.team, self.member, start_date=date(2026, 8, 1))

        self.assertIn("在籍者", self._list())

    def test_other_team_membership_is_not_excluded(self):
        """他チームの所属は除外対象にならない"""
        other = _make_team(name="2F")
        _make_membership(other, self.member, start_date=date(2026, 1, 1))

        self.assertIn("在籍者", self._list())

    def test_no_filter_params_returns_all(self):
        """フィルタ未指定なら全件返る（通常の職員CRUD画面からの呼び出し）"""
        _make_membership(self.team, self.member, start_date=date(2026, 1, 1))

        response = self.client.get(self.url)

        self.assertEqual(len(response.json()["staffs"]), 1)


# ═══════════════════════════════════════════════════════════════
# spa_views
# ═══════════════════════════════════════════════════════════════

class SpaIndexTest(TestCase):
    """spa_index のテスト

    ビルド成果物（app/work_shift/static/work_shift/index.html）の有無で期待値が
    反転しないよう、実ファイルシステムには依存させず両方をモックで検証する。
    """

    def setUp(self):
        self.client.force_login(_make_user())
        self.url = reverse("work_shift:spa")

    def test_returns_html_when_built(self):
        """ビルド成果物があればHTMLを返す"""
        with mock.patch.object(spa_views, "_SPA_INDEX_HTML_PATH") as path:
            path.read_text.return_value = "<html><body>SPA</body></html>"
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("SPA", response.content.decode())

    def test_returns_503_when_not_built(self):
        """ビルド成果物が無ければ503とガイダンスを返す"""
        with mock.patch.object(spa_views, "_SPA_INDEX_HTML_PATH") as path:
            path.read_text.side_effect = FileNotFoundError
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 503)
        self.assertIn("npm run build", response.content.decode())


class FastapiProxyTest(SimpleTestCase):
    """fastapi_proxy のテスト（実通信はせず urllib をモックする）"""

    def setUp(self):
        self.factory = RequestFactory()
        self.allowed_path = "/api/v1/shifts/snapshot"

    def _request(self, path=None, method="get", **params):
        return getattr(self.factory, method)(path or self.allowed_path, params)

    # ──────────────────────────────────────────────
    # ホワイトリスト・メソッド
    # ──────────────────────────────────────────────

    def test_disallowed_path_returns_403(self):
        """ホワイトリスト外のパスは403（SSRF対策の二重チェック）"""
        response = spa_views.fastapi_proxy(self._request("/api/v1/other"))

        self.assertEqual(response.status_code, 403)

    def test_non_get_returns_405(self):
        """GET以外は405"""
        response = spa_views.fastapi_proxy(self._request(method="post"))

        self.assertEqual(response.status_code, 405)

    def test_allowed_path_is_whitelisted(self):
        """許可パスの定義が1件であること（追加時の見落とし防止）"""
        self.assertEqual(spa_views._ALLOWED_FASTAPI_PATHS, {"/api/v1/shifts/snapshot"})

    # ──────────────────────────────────────────────
    # 中継
    # ──────────────────────────────────────────────

    def test_passes_through_response(self):
        """FastAPIのレスポンスをそのまま透過する"""
        upstream = mock.MagicMock()
        upstream.read.return_value = b'{"team_id": 1}'
        upstream.status = 200
        upstream.headers.get.return_value = "application/json"
        upstream.__enter__.return_value = upstream

        with mock.patch.object(spa_views.urllib.request, "urlopen", return_value=upstream):
            response = spa_views.fastapi_proxy(self._request())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'{"team_id": 1}')

    def test_forwards_query_string(self):
        """クエリ文字列を中継先へ引き継ぐ"""
        upstream = mock.MagicMock()
        upstream.read.return_value = b"{}"
        upstream.status = 200
        upstream.headers.get.return_value = "application/json"
        upstream.__enter__.return_value = upstream

        with mock.patch.object(spa_views.urllib.request, "urlopen", return_value=upstream) as urlopen:
            spa_views.fastapi_proxy(self._request(year_month="2026-07", team_id="1"))

        target_url = urlopen.call_args[0][0].full_url
        self.assertIn("year_month=2026-07", target_url)
        self.assertTrue(target_url.startswith("http://127.0.0.1:8090"))

    def test_http_error_is_passed_through(self):
        """FastAPI側のエラーレスポンス（404等）はそのまま透過する"""
        error = urllib.error.HTTPError(
            url="http://127.0.0.1:8090", code=404, msg="Not Found", hdrs=None, fp=None
        )
        error.read = mock.MagicMock(return_value=b'{"detail": "not found"}')
        error.headers = mock.MagicMock()
        error.headers.get.return_value = "application/json"

        with mock.patch.object(spa_views.urllib.request, "urlopen", side_effect=error):
            response = spa_views.fastapi_proxy(self._request())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, b'{"detail": "not found"}')

    def test_connection_error_returns_502(self):
        """FastAPIに接続できなければ502（FastAPI未起動時のデモ落ち防止）"""
        with mock.patch.object(
            spa_views.urllib.request, "urlopen", side_effect=urllib.error.URLError("refused")
        ):
            response = spa_views.fastapi_proxy(self._request())

        self.assertEqual(response.status_code, 502)
        self.assertIn("error", json.loads(response.content))


# ═══════════════════════════════════════════════════════════════
# スモーク（デモが落ちないことの確認。戻り値の詳細は追わない）
# ═══════════════════════════════════════════════════════════════

class SmokeTest(TestCase):
    """主要CRUDが成功系ステータスを返すことだけを確認する"""

    def setUp(self):
        self.client.force_login(_make_user())
        self.groupe = _make_groupe()
        self.team = _make_team(group=self.groupe)

    def _post(self, name, body, **kwargs):
        return self.client.post(
            reverse(f"work_shift:{name}", kwargs=kwargs),
            data=json.dumps(body),
            content_type="application/json",
        )

    # ──────────────────────────────────────────────
    # 一覧
    # ──────────────────────────────────────────────

    def test_list_endpoints_return_200(self):
        """主要な一覧APIが200を返す"""
        targets = [
            ("groupe-list-create", {}),
            ("team-list", {}),
            ("staff-list-create", {}),
            ("spot-worker-list-create", {}),
            ("work-shift-type-list-create", {}),
            ("event-definition-list-create", {}),
            ("team-available-year-months", {"team_id": self.team.id}),
        ]
        for name, kwargs in targets:
            with self.subTest(endpoint=name):
                response = self.client.get(reverse(f"work_shift:{name}", kwargs=kwargs))

                self.assertEqual(response.status_code, 200, msg=f"{name} が200を返さない")

    # ──────────────────────────────────────────────
    # 作成
    # ──────────────────────────────────────────────

    def test_create_groupe(self):
        """グループ作成が201"""
        self.assertEqual(self._post("groupe-list-create", {"name": "新"}).status_code, 201)

    def test_create_staff(self):
        """職員作成が201"""
        self.assertEqual(self._post("staff-list-create", {"name": "新人"}).status_code, 201)

    def test_create_work_shift_type(self):
        """勤務タイプ作成が201"""
        response = self._post(
            "work-shift-type-list-create",
            {"name": "夜勤", "group_id": self.groupe.id, "start_time": "18:00",
             "end_time": "08:00", "is_overnight": True, "color": "#123456"},
        )

        self.assertEqual(response.status_code, 201)

    def test_duplicate_work_shift_type_name_returns_400(self):
        """同一グループ内の勤務タイプ名の重複は400"""
        _make_work_shift_type(self.groupe, name="日1")

        response = self._post("work-shift-type-list-create", {"name": "日1", "group_id": self.groupe.id})

        self.assertEqual(response.status_code, 400)

    def test_add_member(self):
        """メンバー追加が200で所属が作られる"""
        staff = _make_staff()

        response = self._post(
            "team-membership-create",
            {"team_id": self.team.id, "member_kind": Member.KIND_STAFF, "member_id": staff.id},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(TeamMembership.objects.count(), 1)

    def test_add_member_twice_does_not_duplicate(self):
        """同じメンバーを2回追加しても所属は重複しない"""
        staff = _make_staff()
        body = {"team_id": self.team.id, "member_kind": Member.KIND_STAFF, "member_id": staff.id}

        self._post("team-membership-create", body)
        self._post("team-membership-create", body)

        self.assertEqual(TeamMembership.objects.count(), 1)

    # ──────────────────────────────────────────────
    # シフト保存
    # ──────────────────────────────────────────────

    def test_save_shift(self):
        """シフト保存が200でレコードが作られる"""
        _make_work_shift_type(self.groupe, name="日1")
        member = _make_member()

        response = self._post(
            "shifts-bulk-save",
            {"team_id": self.team.id,
             "changes": [{"member_id": member.id, "date": "2026-07-01", "shift_type": "日1"}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["saved"], 1)
        self.assertEqual(Shift.objects.count(), 1)

    def test_unknown_shift_type_is_reported_as_item_error(self):
        """マスタに無い勤務タイプは errors に積まれる（全体は200のまま）"""
        member = _make_member()

        response = self._post(
            "shifts-bulk-save",
            {"team_id": self.team.id,
             "changes": [{"member_id": member.id, "date": "2026-07-01", "shift_type": "存在しない"}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["saved"], 0)
        self.assertEqual(len(response.json()["errors"]), 1)
        self.assertEqual(Shift.objects.count(), 0)

    def test_empty_shift_type_deletes_record(self):
        """空文字のシフトは「未定に戻す」＝レコード削除"""
        member = _make_member()
        Shift.objects.create(member=member, date=date(2026, 7, 1), shift_type="日1", team=self.team.id)

        response = self._post(
            "shifts-bulk-save",
            {"team_id": self.team.id,
             "changes": [{"member_id": member.id, "date": "2026-07-01", "shift_type": ""}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Shift.objects.count(), 0)

    def test_save_shift_requirements(self):
        """予定数の保存が200"""
        w = _make_work_shift_type(self.groupe)

        response = self._post(
            "shift-requirements-bulk-save",
            {"team_id": self.team.id,
             "changes": [{"work_shift_type_id": w.id, "date": "2026-07-01", "required_count": 2}]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ShiftRequirement.objects.count(), 1)

    def test_requirement_of_other_group_is_rejected(self):
        """他グループの勤務タイプは errors に積まれ保存されない"""
        other = _make_work_shift_type(_make_groupe("別グループ"))

        response = self._post(
            "shift-requirements-bulk-save",
            {"team_id": self.team.id,
             "changes": [{"work_shift_type_id": other.id, "date": "2026-07-01", "required_count": 2}]},
        )

        self.assertEqual(response.json()["saved"], 0)
        self.assertEqual(ShiftRequirement.objects.count(), 0)

    # ──────────────────────────────────────────────
    # 削除・並び順
    # ──────────────────────────────────────────────

    def test_membership_delete_is_logical(self):
        """メンバー削除は論理削除でシフト実績は残る"""
        member = _make_member()
        membership = _make_membership(self.team, member)
        Shift.objects.create(member=member, date=date(2026, 7, 1), shift_type="日1", team=self.team.id)

        response = self.client.post(
            reverse("work_shift:team-membership-delete", kwargs={"membership_id": membership.id})
        )

        self.assertEqual(response.status_code, 200)
        membership.refresh_from_db()
        self.assertTrue(membership.is_deleted)
        self.assertEqual(Shift.objects.count(), 1)

    def test_member_order_update(self):
        """並び順の更新が反映される"""
        m1, m2 = _make_member(ref_id=1), _make_member(ref_id=2)
        ms1 = _make_membership(self.team, m1, order=0)
        ms2 = _make_membership(self.team, m2, order=1)

        response = self._post(
            "team-member-order-update", {"member_order": [m2.id, m1.id]},
            team_id=self.team.id,
        )

        self.assertEqual(response.status_code, 200)
        ms1.refresh_from_db()
        ms2.refresh_from_db()
        self.assertEqual((ms2.order, ms1.order), (0, 1))

    def test_groupe_delete_with_team_returns_409(self):
        """チームが属するグループの削除は409（ProtectedErrorの捕捉）"""
        response = self.client.delete(
            reverse("work_shift:groupe-detail", kwargs={"groupe_id": self.groupe.id})
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json())
        self.assertTrue(Groupe.objects.filter(pk=self.groupe.pk).exists())

    def test_available_year_months(self):
        """実績のある年月のみが昇順で返る"""
        member = _make_member()
        Shift.objects.create(member=member, date=date(2026, 7, 5), shift_type="日1", team=self.team.id)
        Shift.objects.create(member=member, date=date(2026, 6, 5), shift_type="日1", team=self.team.id)

        response = self.client.get(
            reverse("work_shift:team-available-year-months", kwargs={"team_id": self.team.id})
        )

        self.assertEqual(response.json()["year_months"], ["2026-06", "2026-07"])
