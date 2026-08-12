import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from accounts.models import LoginHistory
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .decorators import no_cache_no_index


def _make_user(username="testuser", password="test-pass-1234"):
    return User.objects.create_user(username=username, password=password)


def _write_temp_json(tmpdir, payload):
    """一時ディレクトリに config.json を書き出しパスを返す"""
    path = Path(tmpdir) / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class HomeUrlResolveTest(SimpleTestCase):
    """home のURL解決をテスト"""

    def test_reverse_home(self):
        """home:home が /home/ に解決される"""
        self.assertEqual(reverse("home:home"), "/home/")


class NoCacheNoIndexDecoratorTest(SimpleTestCase):
    """no_cache_no_index デコレータのテスト"""

    def setUp(self):
        self.factory = RequestFactory()

    def test_sets_no_store_and_robots_headers(self):
        """キャッシュ抑制ヘッダーと X-Robots-Tag が付与される"""

        @no_cache_no_index
        def view(request):
            return HttpResponse("ok")

        response = view(self.factory.get("/"))

        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_preserves_view_name(self):
        """functools.wraps により元のビュー名が保持される"""

        @no_cache_no_index
        def my_view(request):
            return HttpResponse("ok")

        self.assertEqual(my_view.__name__, "my_view")


class HomeViewAuthTest(TestCase):
    """HomeView の認証まわりのテスト"""

    def test_anonymous_redirects_to_login(self):
        """未ログイン時は /accounts/login/ へリダイレクト"""
        response = self.client.get(reverse("home:home"))

        self.assertRedirects(
            response,
            "/accounts/login/?next=/home/",
            fetch_redirect_response=False,
        )

    def test_logged_in_user_gets_200(self):
        """ログイン済みなら200"""
        self.client.force_login(_make_user())

        response = self.client.get(reverse("home:home"))

        self.assertEqual(response.status_code, 200)


class HomeViewContextTest(TestCase):
    """HomeView のコンテキストのテスト"""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.url = reverse("home:home")

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_uses_home_template(self):
        """home/home.html が使われる"""
        response = self.client.get(self.url)

        self.assertTemplateUsed(response, "home/home.html")

    def test_context_has_main_keys(self):
        """主要なコンテキストキーが揃っている"""
        response = self.client.get(self.url)

        for key in ("user", "current_time", "services", "system_infomation"):
            self.assertIn(key, response.context, msg=f"context に {key} がない")

    def test_context_user_is_request_user(self):
        """context['user'] がリクエストユーザー"""
        response = self.client.get(self.url)

        self.assertEqual(response.context["user"], self.user)

    def test_services_loaded_from_config_json(self):
        """同梱の config.json から services が読み込まれる"""
        response = self.client.get(self.url)

        services = response.context["services"]
        self.assertIsInstance(services, list)
        self.assertGreater(len(services), 0)
        for entry in services:
            self.assertIn("name", entry)
            self.assertIn("url_name", entry)

    def test_response_has_no_cache_headers(self):
        """no_cache_no_index が dispatch に適用されている"""
        response = self.client.get(self.url)

        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_access_is_logged(self):
        """アクセス時に INFO ログが出力される"""
        with self.assertLogs("app.home", level="INFO") as cm:
            self.client.get(self.url)

        self.assertTrue(any("ホームページアクセス: testuser" in line for line in cm.output))


class HomePreviousLoginTest(TestCase):
    """「最終ログイン」に前回ログイン日時が出ることのテスト"""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        # force_login は user_logged_in を発火し履歴を1件作る。各テストが
        # 履歴を明示的に組み立てられるよう、ここで消してまっさらにする。
        LoginHistory.objects.all().delete()
        self.url = reverse("home:home")

    def test_context_has_previous_login_key(self):
        """previous_login が context に必ず入る"""
        response = self.client.get(self.url)

        self.assertIn("previous_login", response.context)

    def test_none_when_only_current_login(self):
        """履歴が今回分の1件だけなら previous_login は None"""
        LoginHistory.objects.create(user=self.user, logged_in_at=timezone.now())

        response = self.client.get(self.url)

        self.assertIsNone(response.context["previous_login"])

    def test_shows_second_latest_not_current(self):
        """直近ではなく2番目に新しい（＝前回）ログイン日時を出す"""
        now = timezone.now()
        previous = now - timedelta(days=1)
        LoginHistory.objects.create(user=self.user, logged_in_at=previous)   # 前回
        LoginHistory.objects.create(user=self.user, logged_in_at=now)        # 今回

        response = self.client.get(self.url)

        self.assertEqual(response.context["previous_login"], previous)

    def test_other_users_history_is_ignored(self):
        """別ユーザーの履歴は混ざらない"""
        other = _make_user(username="other")
        LoginHistory.objects.create(user=other, logged_in_at=timezone.now())
        LoginHistory.objects.create(user=self.user, logged_in_at=timezone.now())

        response = self.client.get(self.url)

        self.assertIsNone(response.context["previous_login"])


class HomeViewServicesJsonTest(TestCase):
    """HomeView の config.json 読み込み（正常系／フォールバック）のテスト"""

    def setUp(self):
        self.client.force_login(_make_user())
        self.url = reverse("home:home")
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmpdir, ignore_errors=True))

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_services_from_patched_config(self):
        """差し替えた config.json の内容が services に入る"""
        payload = [{"name": "ダミー", "status": "on", "url_name": "home:home"}]
        path = _write_temp_json(self.tmpdir, payload)

        with mock.patch("app.home.views.SERVICES_JSON", path):
            response = self.client.get(self.url)

        self.assertEqual(response.context["services"], payload)

    # ──────────────────────────────────────────────
    # フォールバック
    # ──────────────────────────────────────────────

    def test_file_not_found_falls_back_to_empty_list(self):
        """config.json が存在しない場合 services は空リストになる"""
        missing = Path(self.tmpdir) / "not-exists.json"

        with mock.patch("app.home.views.SERVICES_JSON", missing):
            response = self.client.get(self.url)

        self.assertEqual(response.context["services"], [])

    def test_file_not_found_outputs_error_log(self):
        """config.json 不在時に ERROR ログが出力される"""
        missing = Path(self.tmpdir) / "not-exists.json"

        with mock.patch("app.home.views.SERVICES_JSON", missing):
            with self.assertLogs("app.home", level="ERROR") as cm:
                self.client.get(self.url)

        self.assertTrue(any("config.json が見つかりません" in line for line in cm.output))

    def test_invalid_json_falls_back_to_empty_list(self):
        """config.json が不正なJSONの場合 services は空リストになる"""
        broken = Path(self.tmpdir) / "broken.json"
        broken.write_text("{ this is not json", encoding="utf-8")

        with mock.patch("app.home.views.SERVICES_JSON", broken):
            with self.assertLogs("app.home", level="ERROR") as cm:
                response = self.client.get(self.url)

        self.assertEqual(response.context["services"], [])
        self.assertTrue(any("解析に失敗" in line for line in cm.output))


class HomeViewSystemInformationTest(TestCase):
    """HomeView のシステムお知らせ（Markdown）読み込みのテスト"""

    def setUp(self):
        self.client.force_login(_make_user())
        self.url = reverse("home:home")
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmpdir, ignore_errors=True))

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_markdown_is_converted_to_html(self):
        """Markdownファイルの内容がHTMLに変換される"""
        md = Path(self.tmpdir) / "system_information.md"
        md.write_text("# お知らせ\n\n本文です。", encoding="utf-8")

        with mock.patch("app.home.views.SYSTEM_INFO_MD", md):
            response = self.client.get(self.url)

        self.assertIn("<h1>", response.context["system_infomation"])
        self.assertIn("お知らせ", response.context["system_infomation"])

    # ──────────────────────────────────────────────
    # 境界値・フォールバック
    # ──────────────────────────────────────────────

    def test_empty_file_shows_placeholder(self):
        """空ファイルの場合はプレースホルダを表示"""
        md = Path(self.tmpdir) / "system_information.md"
        md.write_text("   \n  ", encoding="utf-8")

        with mock.patch("app.home.views.SYSTEM_INFO_MD", md):
            response = self.client.get(self.url)

        self.assertEqual(response.context["system_infomation"], "（お知らせ無し）")

    def test_file_not_found_shows_placeholder(self):
        """ファイル不在の場合はプレースホルダを表示し WARNING ログを出す"""
        missing = Path(self.tmpdir) / "not-exists.md"

        with mock.patch("app.home.views.SYSTEM_INFO_MD", missing):
            with self.assertLogs("app.home", level="WARNING") as cm:
                response = self.client.get(self.url)

        self.assertEqual(response.context["system_infomation"], "（お知らせ無し）")
        self.assertTrue(any("見つかりません" in line for line in cm.output))
