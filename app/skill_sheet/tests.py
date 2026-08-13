import json
import os
import unittest
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import BindingConfigError, CellBinding, PersonalInfo, SkillSheetData
from django.contrib.auth.models import User

from .forms import CellBindingForm, field_choices_by_model, model_choices
from .utils import load_config, resolve_secret


def _make_personal(registration_no="R001", age=40, gender="M", **kwargs):
    defaults = {
        "education": "○○大学 卒業",
        "nearest_station": "大阪駅",
    }
    defaults.update(kwargs)
    return PersonalInfo.objects.create(
        registration_no=registration_no, age=age, gender=gender, **defaults
    )


def _make_sheet(personal, project_name="案件A", start_month="202401", end_month="202412",
                duration=12, **kwargs):
    defaults = {"content": "開発業務"}
    defaults.update(kwargs)
    return SkillSheetData.objects.create(
        personal=personal,
        project_name=project_name,
        start_month=start_month,
        end_month=end_month,
        duration=duration,
        **defaults,
    )


# ═══════════════════════════════════════════════════════════════
# URL
# ═══════════════════════════════════════════════════════════════

class SkillSheetUrlResolveTest(SimpleTestCase):
    """skill_sheet のURL解決をテスト"""

    def test_reverse_index(self):
        """skill_sheet:index が /skill_sheet/ に解決される"""
        self.assertEqual(reverse("skill_sheet:index"), "/skill_sheet/")

    def test_reverse_detail(self):
        """skill_sheet:detail が解決される"""
        self.assertEqual(reverse("skill_sheet:detail", kwargs={"pk": 1}), "/skill_sheet/1/")


# ═══════════════════════════════════════════════════════════════
# モデル
# ═══════════════════════════════════════════════════════════════

class PersonalInfoModelTest(TestCase):
    """PersonalInfo モデルのテスト"""

    def test_str_uses_registration_no(self):
        """__str__ は 'ID:{id} - {登録No}'"""
        personal = _make_personal(registration_no="R001")

        self.assertEqual(str(personal), f"ID:{personal.id} - R001")

    def test_str_falls_back_to_default(self):
        """登録No が無ければ 'デフォルト' を表示する"""
        personal = _make_personal(registration_no=None)

        self.assertEqual(str(personal), f"ID:{personal.id} - デフォルト")

    def test_str_with_empty_registration_no(self):
        """登録No が空文字でも 'デフォルト' を表示する"""
        personal = _make_personal(registration_no="")

        self.assertEqual(str(personal), f"ID:{personal.id} - デフォルト")

    def test_gender_display(self):
        """get_gender_display で日本語表記が得られる"""
        self.assertEqual(_make_personal(gender="M").get_gender_display(), "男性")
        self.assertEqual(_make_personal(gender="F").get_gender_display(), "女性")
        self.assertEqual(_make_personal(gender="X").get_gender_display(), "その他")

    def test_optional_fields_default_to_none(self):
        """任意項目は未設定なら None"""
        personal = PersonalInfo.objects.create(age=30, education="高校", nearest_station="梅田")

        self.assertIsNone(personal.qualification)
        self.assertIsNone(personal.self_pr)
        self.assertIsNone(personal.gender)

    def test_created_at_is_set(self):
        """created_at が自動設定される"""
        personal = _make_personal()

        self.assertIsNotNone(personal.created_at)


class SkillSheetDataModelTest(TestCase):
    """SkillSheetData モデルのテスト"""

    def setUp(self):
        self.personal = _make_personal()

    def test_str(self):
        """__str__ は '案件名 (開始-終了)'"""
        sheet = _make_sheet(self.personal, project_name="案件A", start_month="202401", end_month="202412")

        self.assertEqual(str(sheet), "案件A (202401-202412)")

    def test_default_values(self):
        """remote と process1..7 のデフォルトは False、person1..3 は0"""
        sheet = _make_sheet(self.personal)

        self.assertFalse(sheet.remote)
        for i in range(1, 8):
            self.assertFalse(getattr(sheet, f"process{i}"), msg=f"process{i}")
        for i in range(1, 4):
            self.assertEqual(getattr(sheet, f"person{i}"), 0, msg=f"person{i}")

    def test_ordering_by_start_month_desc(self):
        """ordering は開始年月の降順"""
        old = _make_sheet(self.personal, project_name="古い", start_month="202301")
        new = _make_sheet(self.personal, project_name="新しい", start_month="202501")

        self.assertEqual(list(SkillSheetData.objects.all()), [new, old])

    def test_cascade_delete(self):
        """パーソナル情報の削除でスキルシートも削除される"""
        _make_sheet(self.personal)

        self.personal.delete()

        self.assertEqual(SkillSheetData.objects.count(), 0)

    def test_related_name(self):
        """related_name 'skill_sheets' で参照できる"""
        sheet = _make_sheet(self.personal)

        self.assertEqual(list(self.personal.skill_sheets.all()), [sheet])


# ═══════════════════════════════════════════════════════════════
# ビュー: index
# ═══════════════════════════════════════════════════════════════

class IndexViewTest(TestCase):
    """index のテスト"""

    def test_redirects_to_detail_pk_1(self):
        """デモ用に ID=1 の詳細へリダイレクトする"""
        response = self.client.get(reverse("skill_sheet:index"))

        self.assertRedirects(
            response,
            reverse("skill_sheet:detail", kwargs={"pk": 1}),
            fetch_redirect_response=False,
        )

    # NOTE: skill_sheet の各ビューは認証デコレータが無く、未ログインでもアクセス可能。
    #       現状の挙動を正としてテストしている。
    def test_anonymous_can_access(self):
        """未ログインでもアクセスできる（現状仕様）"""
        response = self.client.get(reverse("skill_sheet:index"))

        self.assertEqual(response.status_code, 302)


# ═══════════════════════════════════════════════════════════════
# ビュー: detail
# ═══════════════════════════════════════════════════════════════

class DetailViewTest(TestCase):
    """detail のテスト"""

    def setUp(self):
        self.personal = _make_personal()
        self.url = reverse("skill_sheet:detail", kwargs={"pk": self.personal.pk})

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_anonymous_can_access(self):
        """未ログインでもアクセスできる（現状仕様）"""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_uses_template(self):
        """skill_sheet/main.html が使われる"""
        response = self.client.get(self.url)

        self.assertTemplateUsed(response, "skill_sheet/main.html")

    def test_context_keys(self):
        """主要なコンテキストキーが揃っている"""
        response = self.client.get(self.url)

        for key in ("personal", "skill_sheets", "search_query", "keywords", "search_results"):
            self.assertIn(key, response.context, msg=f"context に {key} がない")

    def test_not_found_returns_404(self):
        """存在しないIDは404"""
        url = reverse("skill_sheet:detail", kwargs={"pk": 99999})

        self.assertEqual(self.client.get(url).status_code, 404)

    def test_sheets_sorted_by_start_month_desc(self):
        """スキルシートは開始年月の降順で並ぶ"""
        _make_sheet(self.personal, project_name="古い", start_month="202301")
        _make_sheet(self.personal, project_name="新しい", start_month="202501")

        response = self.client.get(self.url)

        names = [s["project_name"] for s in response.context["skill_sheets"]]
        self.assertEqual(names, ["新しい", "古い"])

    def test_no_is_sequential(self):
        """通し番号 no が1から振られる"""
        _make_sheet(self.personal, project_name="A", start_month="202501")
        _make_sheet(self.personal, project_name="B", start_month="202401")

        response = self.client.get(self.url)

        self.assertEqual([s["no"] for s in response.context["skill_sheets"]], [1, 2])

    def test_other_personals_sheets_are_excluded(self):
        """他のパーソナルのスキルシートは含まれない"""
        other = _make_personal(registration_no="R002")
        _make_sheet(other, project_name="他人の案件")
        _make_sheet(self.personal, project_name="自分の案件")

        response = self.client.get(self.url)

        names = [s["project_name"] for s in response.context["skill_sheets"]]
        self.assertEqual(names, ["自分の案件"])

    # ──────────────────────────────────────────────
    # パーソナル情報の整形
    # ──────────────────────────────────────────────

    def test_personal_age_format(self):
        """年齢は '満XX歳' 表記になる"""
        response = self.client.get(self.url)

        self.assertEqual(response.context["personal"]["age"], "満40歳")

    def test_personal_gender_display(self):
        """性別は日本語表記になる"""
        response = self.client.get(self.url)

        self.assertEqual(response.context["personal"]["gender"], "男性")

    def test_personal_gender_none_becomes_dash(self):
        """性別未設定は '-' になる"""
        personal = _make_personal(registration_no="R003", gender=None)

        response = self.client.get(reverse("skill_sheet:detail", kwargs={"pk": personal.pk}))

        self.assertEqual(response.context["personal"]["gender"], "-")

    def test_personal_null_fields_become_dash(self):
        """null の項目は '-' に変換される"""
        response = self.client.get(self.url)

        self.assertEqual(response.context["personal"]["qualification"], "-")
        self.assertEqual(response.context["personal"]["self_pr"], "-")

    # ──────────────────────────────────────────────
    # 年月・期間の整形
    # ──────────────────────────────────────────────

    def test_date_format(self):
        """開始年月・終了年月は 'YYYY/MM' 表記になる"""
        _make_sheet(self.personal, start_month="202401", end_month="202412")

        response = self.client.get(self.url)

        sheet = response.context["skill_sheets"][0]
        self.assertEqual(sheet["start_date"], "2024/01")
        self.assertEqual(sheet["end_date"], "2024/12")

    def test_duration_months_only(self):
        """12ヶ月以下は 'Xヶ月' 表記"""
        _make_sheet(self.personal, duration=6)

        response = self.client.get(self.url)

        self.assertEqual(response.context["skill_sheets"][0]["duration"], "6ヶ月")

    def test_duration_exactly_12_months(self):
        """ちょうど12ヶ月は '12ヶ月' 表記（境界値）"""
        _make_sheet(self.personal, duration=12)

        response = self.client.get(self.url)

        self.assertEqual(response.context["skill_sheets"][0]["duration"], "12ヶ月")

    def test_duration_years_only(self):
        """余りが無ければ 'X年' 表記"""
        _make_sheet(self.personal, duration=24)

        response = self.client.get(self.url)

        self.assertEqual(response.context["skill_sheets"][0]["duration"], "2年")

    def test_duration_years_and_months(self):
        """年と月の両方があれば 'X年Yヶ月' 表記"""
        _make_sheet(self.personal, duration=14)

        response = self.client.get(self.url)

        self.assertEqual(response.context["skill_sheets"][0]["duration"], "1年2ヶ月")

    # ──────────────────────────────────────────────
    # 工程・人員の整形
    # ──────────────────────────────────────────────

    def test_processes_joined(self):
        """担当工程が config.json の工程名で連結される"""
        _make_sheet(self.personal, process1=True, process4=True)

        response = self.client.get(self.url)

        self.assertEqual(
            response.context["skill_sheets"][0]["processes"], "■要件定義　■実装・単体テスト"
        )

    def test_no_process_becomes_dash(self):
        """担当工程が無ければ '-' になる"""
        _make_sheet(self.personal)

        response = self.client.get(self.url)

        self.assertEqual(response.context["skill_sheets"][0]["processes"], "-")

    def test_personnel_format(self):
        """人員が1名以上なら人員文字列が生成される"""
        _make_sheet(self.personal, person1=3, person2=5, person3=10)

        response = self.client.get(self.url)

        self.assertEqual(
            response.context["skill_sheets"][0]["personnel"],
            "チーム 3名　開発 5名　全体 10名",
        )

    def test_personnel_empty_when_zero(self):
        """person1=0 なら人員は空文字"""
        _make_sheet(self.personal, person1=0)

        response = self.client.get(self.url)

        self.assertEqual(response.context["skill_sheets"][0]["personnel"], "")

    def test_null_fields_become_dash(self):
        """null の項目は '-' に変換される"""
        _make_sheet(self.personal, lang=None, db=None, os=None, tools=None, remarks=None)

        response = self.client.get(self.url)

        sheet = response.context["skill_sheets"][0]
        for key in ("lang", "db", "os", "tools", "remarks"):
            self.assertEqual(sheet[key], "-", msg=key)


class DetailSearchTest(TestCase):
    """detail の検索機能のテスト"""

    def setUp(self):
        self.personal = _make_personal()
        self.url = reverse("skill_sheet:detail", kwargs={"pk": self.personal.pk})
        self.py = _make_sheet(
            self.personal,
            project_name="Python案件",
            start_month="202501",
            end_month="202512",
            duration=12,
            lang="Python",
        )
        self.java = _make_sheet(
            self.personal,
            project_name="Java案件",
            start_month="202401",
            end_month="202412",
            duration=6,
            lang="Java",
        )

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_keyword_is_parsed(self):
        """キーワードが分割されてコンテキストに入る"""
        response = self.client.get(self.url, {"search": "Python"})

        self.assertEqual(response.context["keywords"], ["Python"])

    def test_search_matches_lang(self):
        """Lang項目にヒットする"""
        response = self.client.get(self.url, {"search": "Python"})

        self.assertEqual(response.context["search_results"]["Python"]["count"], 1)

    def test_search_matches_project_name(self):
        """案件名にヒットする"""
        response = self.client.get(self.url, {"search": "Java案件"})

        self.assertEqual(response.context["search_results"]["Java案件"]["count"], 1)

    def test_matched_sheet_is_highlighted(self):
        """ヒットした案件は highlighted=True になる"""
        response = self.client.get(self.url, {"search": "Python"})

        sheets = {s["project_name"]: s["highlighted"] for s in response.context["skill_sheets"]}
        self.assertTrue(sheets["Python案件"])
        self.assertFalse(sheets["Java案件"])

    def test_multiple_keywords_half_width_space(self):
        """半角スペース区切りで複数キーワード検索できる"""
        response = self.client.get(self.url, {"search": "Python Java"})

        self.assertEqual(response.context["keywords"], ["Python", "Java"])
        self.assertEqual(response.context["search_results"]["Python"]["count"], 1)
        self.assertEqual(response.context["search_results"]["Java"]["count"], 1)

    def test_multiple_keywords_full_width_space(self):
        """全角スペース区切りでも複数キーワード検索できる"""
        response = self.client.get(self.url, {"search": "Python　Java"})

        self.assertEqual(response.context["keywords"], ["Python", "Java"])

    def test_nfkc_normalization(self):
        """全角英字は NFKC 正規化されて検索される"""
        response = self.client.get(self.url, {"search": "Ｐｙｔｈｏｎ"})

        self.assertEqual(response.context["search_query"], "Python")
        self.assertEqual(response.context["search_results"]["Python"]["count"], 1)

    def test_project_no_is_overall_position(self):
        """検索結果の no は全体一覧での位置を指す"""
        response = self.client.get(self.url, {"search": "Java"})

        project = response.context["search_results"]["Java"]["projects"][0]
        self.assertEqual(project["no"], 2)

    def test_long_project_name_is_truncated(self):
        """40文字を超える案件名は切り詰められる"""
        _make_sheet(self.personal, project_name="X" * 50, start_month="202301", lang="Rust")

        response = self.client.get(self.url, {"search": "Rust"})

        project = response.context["search_results"]["Rust"]["projects"][0]
        self.assertEqual(project["name"], "X" * 40 + "...")

    # ──────────────────────────────────────────────
    # 実績合計の書式
    # ──────────────────────────────────────────────

    def test_total_duration_months_only(self):
        """合計が12ヶ月未満なら 'Xヶ月'"""
        response = self.client.get(self.url, {"search": "Java"})

        self.assertEqual(response.context["search_results"]["Java"]["duration"], "6ヶ月")

    def test_total_duration_years_only(self):
        """合計がちょうど年単位なら 'X年'"""
        response = self.client.get(self.url, {"search": "Python"})

        self.assertEqual(response.context["search_results"]["Python"]["duration"], "1年")

    def test_total_duration_years_and_months(self):
        """合計が年と月の混在なら 'X年Yヶ月'"""
        response = self.client.get(self.url, {"search": "案件"})

        # Python案件(12) + Java案件(6) = 18ヶ月
        self.assertEqual(response.context["search_results"]["案件"]["duration"], "1年6ヶ月")

    def test_no_hit_duration_is_zero_months(self):
        """ヒット0件なら '0ヶ月'"""
        response = self.client.get(self.url, {"search": "該当なし"})

        result = response.context["search_results"]["該当なし"]
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["duration"], "0ヶ月")

    # ──────────────────────────────────────────────
    # 境界値
    # ──────────────────────────────────────────────

    def test_no_search_query_gives_empty_results(self):
        """検索キーワード無しなら結果は空"""
        response = self.client.get(self.url)

        self.assertEqual(response.context["keywords"], [])
        self.assertEqual(response.context["search_results"], {})

    def test_whitespace_only_query_is_ignored(self):
        """空白のみの検索は無視される"""
        response = self.client.get(self.url, {"search": "   "})

        self.assertEqual(response.context["search_query"], "")
        self.assertEqual(response.context["search_results"], {})

    def test_nothing_highlighted_without_search(self):
        """検索していなければハイライトされない"""
        response = self.client.get(self.url)

        self.assertTrue(all(not s["highlighted"] for s in response.context["skill_sheets"]))


class DetailConfigJsonTest(TestCase):
    """detail の config.json 読み込みのテスト"""

    def setUp(self):
        self.personal = _make_personal()
        self.url = reverse("skill_sheet:detail", kwargs={"pk": self.personal.pk})

    def test_process_names_loaded_from_config(self):
        """同梱の config.json から工程名が読み込まれる"""
        _make_sheet(self.personal, process7=True)

        response = self.client.get(self.url)

        self.assertEqual(response.context["skill_sheets"][0]["processes"], "■保守・運用")

    # TODO: フォールバック未実装。views.py::detail は config.json を try/except なしで
    #       open しているため、ファイル不在時に FileNotFoundError がそのまま送出される
    #       （app/home/views.py はフォールバック実装済み）。
    #       本体側でフォールバックを実装後、@unittest.skip を外すこと。
    @unittest.skip("TODO: フォールバック未実装（config.json 不在時）")
    def test_config_json_missing_falls_back(self):
        """config.json が無い場合でも画面が表示される"""
        _make_sheet(self.personal, process1=True)

        with mock.patch("builtins.open", side_effect=FileNotFoundError):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)


# ═══════════════════════════════════════════════════════════════
# セル同期: CellBinding モデル
# ═══════════════════════════════════════════════════════════════

API_PASSWORD = "test-api-password"


def _make_binding(name="personal_age", label="年齢", field_name="age",
                  record_id=1, writable=True, model_label="skill_sheet.PersonalInfo",
                  **kwargs):
    return CellBinding.objects.create(
        name=name, label=label, model_label=model_label,
        field_name=field_name, record_id=record_id, writable=writable, **kwargs
    )


class CellBindingModelTest(TestCase):
    """CellBinding の解決と読み書き"""

    def setUp(self):
        self.personal = _make_personal(age=40, self_pr="元の自己PR")

    def test_str_shows_name_and_label(self):
        """__str__ は '名称（表示名）'"""
        binding = _make_binding(record_id=self.personal.pk)

        self.assertEqual(str(binding), "personal_age（年齢）")

    def test_read_value(self):
        """read_value は対象レコードの値を返す"""
        binding = _make_binding(name="p_self_pr", field_name="self_pr",
                                record_id=self.personal.pk)

        self.assertEqual(binding.read_value(), "元の自己PR")

    def test_write_value_updates_db(self):
        """write_value は対象レコードを更新する"""
        binding = _make_binding(record_id=self.personal.pk)

        binding.write_value(45)

        self.personal.refresh_from_db()
        self.assertEqual(self.personal.age, 45)

    def test_write_value_coerces_type(self):
        """IntegerField に文字列を渡してもフィールドが解決する"""
        binding = _make_binding(record_id=self.personal.pk)

        binding.write_value("45")

        self.personal.refresh_from_db()
        self.assertEqual(self.personal.age, 45)

    def test_write_value_rejects_invalid(self):
        """解決できない値は ValidationError"""
        binding = _make_binding(record_id=self.personal.pk)

        with self.assertRaises(ValidationError):
            binding.write_value("四十五歳")

    def test_write_value_touches_updated_at(self):
        """auto_now の updated_at が更新される"""
        binding = _make_binding(record_id=self.personal.pk)
        before = self.personal.updated_at

        binding.write_value(45)

        self.personal.refresh_from_db()
        self.assertGreater(self.personal.updated_at, before)

    def test_field_type(self):
        """field_type はフィールドのクラス名"""
        binding = _make_binding(record_id=self.personal.pk)

        self.assertEqual(binding.field_type, "IntegerField")


class CellBindingValidationTest(TestCase):
    """CellBinding の登録時バリデーション"""

    def setUp(self):
        self.personal = _make_personal()

    def test_rejects_other_app_model(self):
        """skill_sheet 以外のアプリのモデルは指定できない"""
        binding = _make_binding(name="evil", model_label="auth.User",
                                field_name="is_superuser", record_id=1)

        with self.assertRaises(ValidationError):
            binding.clean()

    def test_rejects_unknown_field(self):
        """存在しないフィールドは指定できない"""
        binding = _make_binding(field_name="no_such_field", record_id=self.personal.pk)

        with self.assertRaises(ValidationError):
            binding.clean()

    def test_rejects_primary_key(self):
        """主キーは同期対象にできない"""
        binding = _make_binding(field_name="id", record_id=self.personal.pk)

        with self.assertRaises(ValidationError):
            binding.clean()

    def test_rejects_relation_field(self):
        """リレーションは同期対象にできない"""
        sheet = _make_sheet(self.personal)
        binding = _make_binding(model_label="skill_sheet.SkillSheetData",
                                field_name="personal", record_id=sheet.pk)

        with self.assertRaises(ValidationError):
            binding.clean()

    def test_rejects_missing_record(self):
        """存在しないレコードidは指定できない"""
        binding = _make_binding(record_id=self.personal.pk + 999)

        with self.assertRaises(ValidationError):
            binding.clean()

    def test_rejects_malformed_model_label(self):
        """model_label の書式不正は BindingConfigError"""
        binding = _make_binding(model_label="PersonalInfo", record_id=self.personal.pk)

        with self.assertRaises(BindingConfigError):
            binding.resolve_model()

    def test_rejects_non_ascii_name(self):
        """名称に全角は使えない"""
        binding = CellBinding(name="年齢", label="年齢",
                              model_label="skill_sheet.PersonalInfo",
                              field_name="age", record_id=self.personal.pk)

        with self.assertRaises(ValidationError) as cm:
            binding.full_clean()
        self.assertIn("name", cm.exception.error_dict)

    def test_accepts_ascii_name_with_symbols(self):
        """英字始まりで英数字と _ . - は使える"""
        binding = CellBinding(name="personal.age_1-a", label="年齢",
                              model_label="skill_sheet.PersonalInfo",
                              field_name="age", record_id=self.personal.pk)

        binding.full_clean()  # 例外が出なければ合格

    def test_rejects_name_starting_with_digit(self):
        """数字始まりは使えない"""
        binding = CellBinding(name="1age", label="年齢",
                              model_label="skill_sheet.PersonalInfo",
                              field_name="age", record_id=self.personal.pk)

        with self.assertRaises(ValidationError):
            binding.full_clean()


# ═══════════════════════════════════════════════════════════════
# セル同期API
# ═══════════════════════════════════════════════════════════════

class CellSyncApiUrlTest(SimpleTestCase):
    """セル同期APIのURL解決"""

    def test_reverse_api_cells(self):
        self.assertEqual(reverse("skill_sheet:api_cells"), "/skill_sheet/api/cells/")

    def test_reverse_api_bindings(self):
        self.assertEqual(reverse("skill_sheet:api_bindings"), "/skill_sheet/api/bindings/")


class CellSyncApiTestBase(TestCase):
    """api_password を環境変数で用意する共通土台"""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"SKILL_SHEET_API_PASSWORD": API_PASSWORD})
        patcher.start()
        self.addCleanup(patcher.stop)

        self.url = reverse("skill_sheet:api_cells")
        self.personal = _make_personal(age=40, self_pr="元の自己PR", education="○○大学 卒業")
        self.age = _make_binding(name="personal_age", label="年齢", field_name="age",
                                 record_id=self.personal.pk, writable=True)
        self.self_pr = _make_binding(name="personal_self_pr", label="自己PR",
                                     field_name="self_pr", record_id=self.personal.pk,
                                     writable=False)

    def post(self, url, payload, password=API_PASSWORD):
        body = dict(payload)
        if password is not None:
            body["api_password"] = password
        return self.client.post(url, data=json.dumps(body), content_type="application/json")


class CellSyncApiAuthTest(CellSyncApiTestBase):
    """認証"""

    def test_wrong_password_returns_401(self):
        """パスワード不一致は 401"""
        response = self.post(self.url, {"items": []}, password="wrong")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 1)

    def test_missing_password_returns_401(self):
        """パスワード未指定は 401"""
        response = self.post(self.url, {"items": []}, password=None)

        self.assertEqual(response.status_code, 401)

    def test_unconfigured_password_returns_500(self):
        """サーバー側にパスワードが設定されていなければ 500"""
        with mock.patch.dict(os.environ, {"SKILL_SHEET_API_PASSWORD": ""}):
            response = self.post(self.url, {"items": []})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], 1)

    def test_get_not_allowed(self):
        """GET は 405"""
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_broken_json_returns_400(self):
        """壊れたJSONは 400"""
        response = self.client.post(self.url, data="{", content_type="application/json")

        self.assertEqual(response.status_code, 400)


class CellSyncApiRequestShapeTest(CellSyncApiTestBase):
    """リクエスト構造の検証"""

    def test_items_must_be_list(self):
        response = self.post(self.url, {"items": {"name": "personal_age"}})

        self.assertEqual(response.status_code, 400)

    def test_items_must_not_be_empty(self):
        response = self.post(self.url, {"items": []})

        self.assertEqual(response.status_code, 400)

    def test_direction_must_be_push_or_pull(self):
        """none はクライアント側で除外される想定。APIは受け付けない"""
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "none"},
        ]})

        self.assertEqual(response.status_code, 400)

    def test_push_requires_value(self):
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "push"},
        ]})

        self.assertEqual(response.status_code, 400)


class CellSyncApiPullTest(CellSyncApiTestBase):
    """pull（DB → ローカル）"""

    def test_pull_returns_value(self):
        response = self.post(self.url, {"items": [
            {"name": "personal_self_pr", "direction": "pull"},
        ]})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["results"][0]["value"], "元の自己PR")
        self.assertEqual(body["results"][0]["status"], "ok")

    def test_pull_allowed_even_when_not_writable(self):
        """writable=False でも pull はできる"""
        self.assertFalse(self.self_pr.writable)

        response = self.post(self.url, {"items": [
            {"name": "personal_self_pr", "direction": "pull"},
        ]})

        self.assertEqual(response.status_code, 200)


class CellSyncApiPushTest(CellSyncApiTestBase):
    """push（ローカル → DB）"""

    def test_push_updates_db(self):
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "push", "value": 45},
        ]})

        self.assertEqual(response.status_code, 200)
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.age, 45)

    def test_push_coerces_string_to_integer(self):
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "push", "value": "45"},
        ]})

        self.assertEqual(response.status_code, 200)
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.age, 45)

    def test_push_rejects_invalid_value(self):
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "push", "value": "四十五歳"},
        ]})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 2)
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.age, 40)

    def test_push_error_message_includes_label(self):
        """エラーメッセージに表示名が入る（name だけだと探しにくい）"""
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "push", "value": "四十五歳"},
        ]})

        result = response.json()["results"][0]
        self.assertEqual(result["status"], "error")
        self.assertIn("年齢", result["error"])

    def test_push_to_read_only_binding_returns_403(self):
        """writable=False への push は 403"""
        response = self.post(self.url, {"items": [
            {"name": "personal_self_pr", "direction": "push", "value": "書き換え"},
        ]})

        self.assertEqual(response.status_code, 403)
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.self_pr, "元の自己PR")

    def test_read_only_violation_blocks_whole_request(self):
        """1件でも書き込み不可があれば、他の push も実行しない"""
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "push", "value": 45},
            {"name": "personal_self_pr", "direction": "push", "value": "書き換え"},
        ]})

        self.assertEqual(response.status_code, 403)
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.age, 40)


class CellSyncApiAtomicityTest(CellSyncApiTestBase):
    """push の原子性"""

    def setUp(self):
        super().setUp()
        self.education = _make_binding(name="personal_education", label="学歴",
                                       field_name="education",
                                       record_id=self.personal.pk, writable=True)

    def test_all_or_nothing(self):
        """後続が検証で落ちれば、先行して書いた分もロールバックされる"""
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "push", "value": 45},
            {"name": "personal_education", "direction": "push", "value": "あ" * 100},
        ]})

        self.assertEqual(response.status_code, 400)
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.age, 40)
        self.assertEqual(self.personal.education, "○○大学 卒業")

    def test_failed_request_marks_other_items_skipped(self):
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "push", "value": 45},
            {"name": "personal_education", "direction": "push", "value": "あ" * 100},
        ]})

        results = {r["name"]: r["status"] for r in response.json()["results"]}
        self.assertEqual(results["personal_age"], "skipped")
        self.assertEqual(results["personal_education"], "error")

    def test_mixed_push_and_pull_succeeds(self):
        """pull と push の混在"""
        response = self.post(self.url, {"items": [
            {"name": "personal_self_pr", "direction": "pull"},
            {"name": "personal_age", "direction": "push", "value": 45},
        ]})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["results"][0]["value"], "元の自己PR")
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.age, 45)

    def test_results_preserve_request_order(self):
        response = self.post(self.url, {"items": [
            {"name": "personal_self_pr", "direction": "pull"},
            {"name": "personal_age", "direction": "push", "value": 45},
        ]})

        names = [r["name"] for r in response.json()["results"]]
        self.assertEqual(names, ["personal_self_pr", "personal_age"])


class CellSyncApiNameResolutionTest(CellSyncApiTestBase):
    """名称の解決（このAPIの安全性の要）"""

    def test_unknown_name_returns_400(self):
        response = self.post(self.url, {"items": [
            {"name": "no_such_name", "direction": "pull"},
        ]})

        self.assertEqual(response.status_code, 400)
        self.assertIn("no_such_name", response.json()["error"])

    def test_unknown_name_lists_available_names(self):
        """探しやすいよう、利用可能な名称を返す"""
        response = self.post(self.url, {"items": [
            {"name": "no_such_name", "direction": "pull"},
        ]})

        self.assertIn("personal_age", response.json()["available"])

    def test_unknown_name_blocks_whole_request(self):
        """未登録が1件でもあれば、他の push も実行しない"""
        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "push", "value": 45},
            {"name": "no_such_name", "direction": "pull"},
        ]})

        self.assertEqual(response.status_code, 400)
        self.personal.refresh_from_db()
        self.assertEqual(self.personal.age, 40)

    def test_client_cannot_specify_table_or_field(self):
        """
        リクエストに model_label / field_name を混ぜても無視される。

        同期先は CellBinding だけが決める。クライアントが任意のテーブルを
        指定する経路が存在しないことの確認。
        """
        other = _make_personal(registration_no="R002", age=30)

        response = self.post(self.url, {"items": [{
            "name": "personal_age",
            "direction": "push",
            "value": 45,
            "model_label": "auth.User",
            "field_name": "is_superuser",
            "record_id": other.pk,
        }]})

        self.assertEqual(response.status_code, 200)
        self.personal.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.personal.age, 45)   # バインディングが指す先だけが更新される
        self.assertEqual(other.age, 30)

    def test_broken_binding_returns_500(self):
        """バインディングの指し先が消えていればサーバーエラー（利用者の入力の問題ではない）"""
        self.personal.delete()

        response = self.post(self.url, {"items": [
            {"name": "personal_age", "direction": "pull"},
        ]})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], 1)


class BindingListApiTest(CellSyncApiTestBase):
    """バインディング一覧API"""

    def setUp(self):
        super().setUp()
        self.list_url = reverse("skill_sheet:api_bindings")

    def test_lists_registered_bindings(self):
        response = self.post(self.list_url, {})

        self.assertEqual(response.status_code, 200)
        names = [b["name"] for b in response.json()["bindings"]]
        self.assertEqual(sorted(names), ["personal_age", "personal_self_pr"])

    def test_includes_label_writable_and_type(self):
        response = self.post(self.list_url, {})

        by_name = {b["name"]: b for b in response.json()["bindings"]}
        self.assertEqual(by_name["personal_age"]["label"], "年齢")
        self.assertTrue(by_name["personal_age"]["writable"])
        self.assertEqual(by_name["personal_age"]["type"], "IntegerField")
        self.assertFalse(by_name["personal_self_pr"]["writable"])

    def test_does_not_expose_table_or_field(self):
        """一覧に DB の構造情報を含めない"""
        response = self.post(self.list_url, {})

        payload = response.content.decode("utf-8")
        self.assertNotIn("PersonalInfo", payload)
        self.assertNotIn("record_id", payload)

    def test_requires_auth(self):
        response = self.post(self.list_url, {}, password="wrong")

        self.assertEqual(response.status_code, 401)


# ═══════════════════════════════════════════════════════════════
# セル同期: 設定の読み込み
# ═══════════════════════════════════════════════════════════════

class ResolveSecretTest(SimpleTestCase):
    """api_password の 'env:' 解決"""

    def test_plain_value_is_returned_as_is(self):
        """env: が付かない値はそのまま返す"""
        self.assertEqual(resolve_secret("plain-value"), "plain-value")

    def test_env_prefix_reads_environment(self):
        """env:NAME は環境変数を引く"""
        with mock.patch.dict(os.environ, {"SKILL_SHEET_TEST_PW": "from-export"}):
            self.assertEqual(resolve_secret("env:SKILL_SHEET_TEST_PW"), "from-export")

    def test_undefined_env_returns_empty(self):
        """未設定なら空文字（API 側で 500 になる）"""
        self.assertEqual(resolve_secret("env:SKILL_SHEET_NOT_DEFINED_ANYWHERE"), "")

    def test_resolution_goes_through_decouple(self):
        """
        os.environ ではなく decouple 経由で引く。

        decouple は os.environ を先に見てから .env を見るため、export でも
        .env でも同じように通る。os.environ を直接見ると、.env に書いた値は
        pipenv 経由で起動したときしか読めず、起動方法で挙動が変わってしまう。
        """
        with mock.patch("app.common.config.env_config", return_value="from-dotenv") as m:
            self.assertEqual(resolve_secret("env:SOME_NAME"), "from-dotenv")

        m.assert_called_once_with("SOME_NAME", default="")

    def test_non_string_is_returned_as_is(self):
        self.assertIsNone(resolve_secret(None))


class LoadConfigTest(SimpleTestCase):
    """同梱の config.json"""

    def test_contains_api_password_key(self):
        """api_password キーが用意されている"""
        self.assertIn("api_password", load_config())

    def test_api_password_is_not_hardcoded(self):
        """秘密を直書きしない（リポジトリに含まれるファイルのため）"""
        self.assertTrue(load_config()["api_password"].startswith("env:"))


# ═══════════════════════════════════════════════════════════════
# セル同期定義の管理画面
# ═══════════════════════════════════════════════════════════════

class BindingScreenTestBase(TestCase):
    def setUp(self):
        self.personal = _make_personal()
        self.admin = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pw"
        )
        self.member = User.objects.create_user(username="member", password="pw")
        self.list_url = reverse("skill_sheet:binding_list")
        self.create_url = reverse("skill_sheet:binding_create")

    def login_admin(self):
        self.client.force_login(self.admin)

    def valid_post(self, **overrides):
        data = {
            "name": "personal_age",
            "label": "年齢",
            "description": "",
            "model_label": "skill_sheet.PersonalInfo",
            "field_name": "age",
            "record_id": self.personal.pk,
        }
        data.update(overrides)
        return data


class BindingScreenPermissionTest(BindingScreenTestBase):
    """管理者以外には見せない"""

    def test_anonymous_is_redirected(self):
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_non_superuser_is_redirected(self):
        self.client.force_login(self.member)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 302)

    def test_superuser_can_access(self):
        self.login_admin()

        self.assertEqual(self.client.get(self.list_url).status_code, 200)

    def test_create_and_edit_are_protected(self):
        binding = _make_binding(record_id=self.personal.pk)
        edit_url = reverse("skill_sheet:binding_edit", kwargs={"pk": binding.pk})
        self.client.force_login(self.member)

        self.assertEqual(self.client.get(self.create_url).status_code, 302)
        self.assertEqual(self.client.get(edit_url).status_code, 302)

    def test_non_superuser_cannot_create(self):
        """POST も弾く（画面を隠すだけでは足りない）"""
        self.client.force_login(self.member)

        self.client.post(self.create_url, self.valid_post())

        self.assertEqual(CellBinding.objects.count(), 0)


class BindingListTest(BindingScreenTestBase):
    def setUp(self):
        super().setUp()
        self.login_admin()

    def test_uses_template(self):
        response = self.client.get(self.list_url)

        self.assertTemplateUsed(response, "skill_sheet/binding_list.html")

    def test_lists_in_id_descending_order(self):
        _make_binding(name="first", record_id=self.personal.pk)
        _make_binding(name="second", record_id=self.personal.pk)

        response = self.client.get(self.list_url)

        names = [b.name for b in response.context["bindings"]]
        self.assertEqual(names, ["second", "first"])

    def test_empty_list_is_fine(self):
        response = self.client.get(self.list_url)

        self.assertEqual(list(response.context["bindings"]), [])


class BindingCreateTest(BindingScreenTestBase):
    def setUp(self):
        super().setUp()
        self.login_admin()

    def test_get_shows_form(self):
        response = self.client.get(self.create_url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "skill_sheet/binding_form.html")
        self.assertTrue(response.context["is_new"])

    def test_post_creates_binding(self):
        response = self.client.post(self.create_url, self.valid_post())

        self.assertRedirects(response, self.list_url)
        binding = CellBinding.objects.get(name="personal_age")
        self.assertEqual(binding.field_name, "age")
        self.assertEqual(binding.record_id, self.personal.pk)

    def test_writable_defaults_to_false(self):
        """チェックを付けなければ読み取り専用のまま"""
        self.client.post(self.create_url, self.valid_post())

        self.assertFalse(CellBinding.objects.get(name="personal_age").writable)

    def test_writable_can_be_set(self):
        self.client.post(self.create_url, self.valid_post(writable="on"))

        self.assertTrue(CellBinding.objects.get(name="personal_age").writable)

    def test_rejects_missing_record(self):
        response = self.client.post(
            self.create_url, self.valid_post(record_id=self.personal.pk + 999)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CellBinding.objects.count(), 0)
        self.assertTrue(response.context["form"].non_field_errors())

    def test_rejects_field_of_another_model(self):
        """モデルとフィールドの組み合わせが不正なら弾く"""
        response = self.client.post(
            self.create_url, self.valid_post(field_name="project_name")
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CellBinding.objects.count(), 0)

    def test_rejects_non_ascii_name(self):
        response = self.client.post(self.create_url, self.valid_post(name="年齢"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.context["form"].errors)

    def test_rejects_duplicate_name(self):
        _make_binding(name="personal_age", record_id=self.personal.pk)

        response = self.client.post(self.create_url, self.valid_post())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CellBinding.objects.count(), 1)


class BindingEditTest(BindingScreenTestBase):
    def setUp(self):
        super().setUp()
        self.login_admin()
        self.binding = _make_binding(record_id=self.personal.pk, writable=False)
        self.url = reverse("skill_sheet:binding_edit", kwargs={"pk": self.binding.pk})

    def test_get_shows_current_values(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["is_new"])
        self.assertEqual(response.context["form"].initial["field_name"], "age")

    def test_post_updates(self):
        response = self.client.post(
            self.url, self.valid_post(label="満年齢", writable="on")
        )

        self.assertRedirects(response, self.list_url)
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.label, "満年齢")
        self.assertTrue(self.binding.writable)

    def test_does_not_create_a_new_row(self):
        self.client.post(self.url, self.valid_post(label="満年齢"))

        self.assertEqual(CellBinding.objects.count(), 1)

    def test_missing_pk_returns_404(self):
        url = reverse("skill_sheet:binding_edit", kwargs={"pk": self.binding.pk + 999})

        self.assertEqual(self.client.get(url).status_code, 404)


class BindingFormChoicesTest(TestCase):
    """ドロップダウンの中身"""

    def test_model_choices_are_skill_sheet_only(self):
        labels = [value for value, _ in model_choices() if value]

        self.assertIn("skill_sheet.PersonalInfo", labels)
        self.assertTrue(all(v.startswith("skill_sheet.") for v in labels))

    def test_cell_binding_itself_is_not_selectable(self):
        """定義テーブル自身を同期対象にはできない"""
        labels = [value for value, _ in model_choices()]

        self.assertNotIn("skill_sheet.CellBinding", labels)

    def test_field_choices_exclude_auto_fields(self):
        fields = [n for n, _ in field_choices_by_model()["skill_sheet.PersonalInfo"]]

        self.assertIn("age", fields)
        self.assertNotIn("id", fields)
        self.assertNotIn("created_at", fields)
        self.assertNotIn("updated_at", fields)

    def test_field_choices_exclude_relations(self):
        fields = [n for n, _ in field_choices_by_model()["skill_sheet.SkillSheetData"]]

        self.assertIn("project_name", fields)
        self.assertNotIn("personal", fields)

    def test_form_field_map_covers_every_model(self):
        form = CellBindingForm()

        self.assertEqual(
            sorted(form.field_map),
            ["skill_sheet.PersonalInfo", "skill_sheet.SkillSheetData"],
        )


class BindingSampleConfigTest(BindingScreenTestBase):
    """画面下部に出す設定ファイルの雛形"""

    def setUp(self):
        super().setUp()
        self.login_admin()
        patcher = mock.patch.dict(os.environ, {"SKILL_SHEET_API_PASSWORD": API_PASSWORD})
        patcher.start()
        self.addCleanup(patcher.stop)

    def sample(self):
        response = self.client.get(self.list_url)
        return json.loads(response.context["sample_config"])

    def test_endpoint_matches_this_server(self):
        sample = self.sample()

        self.assertEqual(sample["endpoint"], "http://testserver/skill_sheet/api/cells/")

    def test_api_password_is_resolved(self):
        self.assertEqual(self.sample()["api_password"], API_PASSWORD)

    def test_pairs_are_in_id_descending_order(self):
        _make_binding(name="first", record_id=self.personal.pk)
        _make_binding(name="second", record_id=self.personal.pk)

        pairs = self.sample()["books"][0]["pairs"]

        self.assertEqual([p["name"] for p in pairs], ["second", "first"])

    def test_sheet_and_cell_are_blank(self):
        _make_binding(record_id=self.personal.pk)

        pair = self.sample()["books"][0]["pairs"][0]

        self.assertEqual(pair["sheet"], "")
        self.assertEqual(pair["cell"], "")

    def test_fixed_book_settings(self):
        book = self.sample()["books"][0]

        self.assertEqual(book["path"], "C:/xxx.xlsx")
        self.assertEqual(book["direction"], "pull")
        self.assertIs(book["save_after_pull"], False)

    def test_is_valid_json_even_without_bindings(self):
        self.assertEqual(self.sample()["books"][0]["pairs"], [])

    def test_unresolved_password_shows_the_setting(self):
        """解決できないときは設定値そのものを出す（どこを直すか分かるように）"""
        with mock.patch.dict(os.environ, {"SKILL_SHEET_API_PASSWORD": ""}):
            sample = self.sample()

        self.assertEqual(sample["api_password"], "env:SKILL_SHEET_API_PASSWORD")
