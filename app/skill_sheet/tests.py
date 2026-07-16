import unittest
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import PersonalInfo, SkillSheetData


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
