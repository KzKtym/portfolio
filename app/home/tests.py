import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from accounts.models import (
    LoginHistory,
    LoginLockout,
    MeetingAccess,
    hash_meeting_token,
)
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone



def _make_user(username="testuser", password="test-pass-1234", **kwargs):
    return User.objects.create_user(username=username, password=password, **kwargs)


def _make_superuser(username="admin", password="admin-pass-1234"):
    return User.objects.create_superuser(username=username, password=password)


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

        with mock.patch("app.common.config.get_app_config_path", return_value=path):
            response = self.client.get(self.url)

        self.assertEqual(response.context["services"], payload)

    # ──────────────────────────────────────────────
    # フォールバック
    # ──────────────────────────────────────────────

    def test_file_not_found_falls_back_to_empty_list(self):
        """config.json が存在しない場合 services は空リストになる"""
        missing = Path(self.tmpdir) / "not-exists.json"

        with mock.patch("app.common.config.get_app_config_path", return_value=missing):
            response = self.client.get(self.url)

        self.assertEqual(response.context["services"], [])

    def test_file_not_found_outputs_error_log(self):
        """config.json 不在時に ERROR ログが出力される"""
        missing = Path(self.tmpdir) / "not-exists.json"

        with mock.patch("app.common.config.get_app_config_path", return_value=missing):
            with self.assertLogs("app.home", level="ERROR") as cm:
                self.client.get(self.url)

        self.assertTrue(any("config.json が見つかりません" in line for line in cm.output))

    def test_invalid_json_falls_back_to_empty_list(self):
        """config.json が不正なJSONの場合 services は空リストになる"""
        broken = Path(self.tmpdir) / "broken.json"
        broken.write_text("{ this is not json", encoding="utf-8")

        with mock.patch("app.common.config.get_app_config_path", return_value=broken):
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


# ══════════════════════════════════════════════════
# サービス管理画面
# ══════════════════════════════════════════════════


class ServiceAdminUrlResolveTest(SimpleTestCase):
    """サービス管理のURL解決をテスト"""

    def test_reverse_index(self):
        """service_admin:index が /service_admin/ に解決される"""
        self.assertEqual(reverse("service_admin:index"), "/service_admin/")

    def test_reverse_notice_save(self):
        """お知らせ保存URLが解決される"""
        self.assertEqual(reverse("service_admin:notice_save"), "/service_admin/notice/save/")

    def test_reverse_notice_preview(self):
        """お知らせプレビューURLが解決される"""
        self.assertEqual(reverse("service_admin:notice_preview"), "/service_admin/notice/preview/")

    def test_reverse_meeting_endpoints(self):
        """商談用アクセスの各URLが解決される"""
        self.assertEqual(reverse("service_admin:meeting_issue"), "/service_admin/meeting/issue/")
        self.assertEqual(
            reverse("service_admin:meeting_revoke", args=[3]), "/service_admin/meeting/3/revoke/"
        )
        self.assertEqual(
            reverse("service_admin:meeting_reissue", args=[3]), "/service_admin/meeting/3/reissue/"
        )
        self.assertEqual(reverse("service_admin:issued_dismiss"), "/service_admin/issued/dismiss/")


class ServiceAdminAccessTest(TestCase):
    """サービス管理画面のアクセス制御のテスト"""

    def setUp(self):
        self.url = reverse("service_admin:index")

    def test_anonymous_redirects_to_login(self):
        """未ログイン時は /accounts/login/ へリダイレクト"""
        response = self.client.get(self.url)

        self.assertRedirects(
            response,
            "/accounts/login/?next=/service_admin/",
            fetch_redirect_response=False,
        )

    def test_general_user_is_redirected(self):
        """一般ユーザーは user_passes_test によりログインURLへリダイレクト"""
        self.client.force_login(_make_user())

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_superuser_gets_200(self):
        """管理者なら200で専用テンプレートが使われる"""
        self.client.force_login(_make_superuser())

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "home/service_admin.html")

    def test_response_has_no_cache_headers(self):
        """no_cache_no_index が dispatch に適用されている"""
        self.client.force_login(_make_superuser())

        response = self.client.get(self.url)

        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_home_shows_button_only_for_superuser(self):
        """/home/ のサービス管理ボタンは管理者にだけ出る"""
        self.client.force_login(_make_user())
        self.assertNotContains(self.client.get(reverse("home:home")), "/service_admin/")

        self.client.force_login(_make_superuser())
        self.assertContains(self.client.get(reverse("home:home")), "/service_admin/")


class ServiceAdminUserListTest(TestCase):
    """ユーザー一覧の絞り込み・並び順のテスト"""

    def setUp(self):
        self.admin = _make_superuser()
        self.active = _make_user(username="active-user")
        self.inactive = _make_user(username="inactive-user", is_active=False)
        self.client.force_login(self.admin)
        self.url = reverse("service_admin:index")

    def test_default_filter_is_active(self):
        """既定は is_active=True のみ"""
        response = self.client.get(self.url)

        self.assertEqual(response.context["user_filter"], "active")
        usernames = [u.username for u in response.context["users"]]
        self.assertIn("active-user", usernames)
        self.assertNotIn("inactive-user", usernames)

    def test_all_filter_includes_inactive(self):
        """?users=all なら無効ユーザーも含む"""
        response = self.client.get(self.url, {"users": "all"})

        self.assertEqual(response.context["user_filter"], "all")
        usernames = [u.username for u in response.context["users"]]
        self.assertIn("inactive-user", usernames)

    def test_ordered_by_id_desc(self):
        """id の降順で並ぶ"""
        response = self.client.get(self.url, {"users": "all"})

        ids = [u.id for u in response.context["users"]]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_unknown_filter_falls_back_to_active(self):
        """未知の値は既定（active）にフォールバックする"""
        response = self.client.get(self.url, {"users": "../etc/passwd"})

        self.assertEqual(response.context["user_filter"], "active")


class ServiceAdminLoginHistoryTest(TestCase):
    """アクセスログの絞り込みのテスト"""

    def setUp(self):
        self.admin = _make_superuser()
        self.user_a = _make_user(username="user-a")
        self.user_b = _make_user(username="user-b")
        self.client.force_login(self.admin)
        LoginHistory.objects.all().delete()
        self.url = reverse("service_admin:index")

    def _add(self, user, days_ago):
        return LoginHistory.objects.create(
            user=user, logged_in_at=timezone.now() - timedelta(days=days_ago)
        )

    def test_default_filter_is_last_login(self):
        """既定は各ユーザーの最終ログイン1件のみ"""
        self._add(self.user_a, 3)
        latest_a = self._add(self.user_a, 1)
        latest_b = self._add(self.user_b, 2)

        response = self.client.get(self.url)

        self.assertEqual(response.context["log_filter"], "last")
        rows = list(response.context["login_histories"])
        self.assertEqual([r.id for r in rows], [latest_a.id, latest_b.id])

    def test_last3byu_returns_three_newest_per_user(self):
        """?logs=last3byu は各ユーザーの新しい順3件まで"""
        a_rows = [self._add(self.user_a, i) for i in range(5)]  # 5件（新しい順に i=0,1,2...）
        b_rows = [self._add(self.user_b, i) for i in range(2)]  # 2件だけのユーザー

        response = self.client.get(self.url, {"logs": "last3byu"})

        rows = list(response.context["login_histories"])
        self.assertEqual(response.context["log_filter"], "last3byu")
        # user-a は新しい3件のみ、user-b は全2件
        self.assertEqual(
            [r.id for r in rows],
            [a_rows[0].id, a_rows[1].id, a_rows[2].id, b_rows[0].id, b_rows[1].id],
        )

    def test_last3byu_groups_rows_by_user(self):
        """?logs=last3byu はユーザーごとにまとまって並ぶ（ユーザー名順）"""
        self._add(self.user_b, 1)
        self._add(self.user_a, 2)
        self._add(self.user_b, 3)
        self._add(self.user_a, 4)

        response = self.client.get(self.url, {"logs": "last3byu"})

        usernames = [r.user.username for r in response.context["login_histories"]]
        self.assertEqual(usernames, ["user-a", "user-a", "user-b", "user-b"])

    def test_last3byu_excludes_other_users_rows_from_the_limit(self):
        """3件の上限はユーザー単位（他ユーザーの件数に影響されない）"""
        for i in range(4):
            self._add(self.user_a, i)
        newest_b = self._add(self.user_b, 10)

        response = self.client.get(self.url, {"logs": "last3byu"})

        rows = list(response.context["login_histories"])
        self.assertIn(newest_b.id, [r.id for r in rows])
        self.assertEqual(len([r for r in rows if r.user_id == self.user_a.id]), 3)

    def test_tail20_returns_at_most_20_newest(self):
        """?logs=tail20 は最新20件まで"""
        for i in range(25):
            self._add(self.user_a, i)

        response = self.client.get(self.url, {"logs": "tail20"})

        rows = list(response.context["login_histories"])
        self.assertEqual(response.context["log_filter"], "tail20")
        self.assertEqual(len(rows), 20)
        timestamps = [r.logged_in_at for r in rows]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_unknown_filter_falls_back_to_last(self):
        """未知の値は既定（last）にフォールバックする"""
        response = self.client.get(self.url, {"logs": "dummy"})

        self.assertEqual(response.context["log_filter"], "last")


class ServiceAdminNoticeTest(TestCase):
    """お知らせ管理（表示・保存・プレビュー）のテスト"""

    def setUp(self):
        self.client.force_login(_make_superuser())
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmpdir, ignore_errors=True))
        self.md = Path(self.tmpdir) / "system_information.md"
        self.md.write_text("# 元のお知らせ", encoding="utf-8")

    def test_context_has_raw_text_and_html(self):
        """編集用の生テキストと表示用HTMLの両方が渡る"""
        with mock.patch("app.home.views.SYSTEM_INFO_MD", self.md):
            response = self.client.get(reverse("service_admin:index"))

        self.assertEqual(response.context["notice_text"], "# 元のお知らせ")
        self.assertIn("<h1>", response.context["notice_html"])

    def test_save_overwrites_file_and_redirects(self):
        """保存でファイルが上書きされ、一覧へリダイレクトする"""
        with mock.patch("app.home.views.SYSTEM_INFO_MD", self.md):
            response = self.client.post(
                reverse("service_admin:notice_save"), {"content": "* 新しいお知らせ"}
            )

        self.assertRedirects(response, reverse("service_admin:index"))
        self.assertEqual(self.md.read_text(encoding="utf-8"), "* 新しいお知らせ")

    def test_save_normalizes_crlf(self):
        """改行コードは LF に正規化して保存する"""
        with mock.patch("app.home.views.SYSTEM_INFO_MD", self.md):
            self.client.post(reverse("service_admin:notice_save"), {"content": "a\r\nb\rc"})

        self.assertEqual(self.md.read_text(encoding="utf-8"), "a\nb\nc")

    def test_save_leaves_no_temp_file(self):
        """一時ファイルは置換後に残らない"""
        with mock.patch("app.home.views.SYSTEM_INFO_MD", self.md):
            self.client.post(reverse("service_admin:notice_save"), {"content": "x"})

        self.assertEqual(
            [p.name for p in Path(self.tmpdir).iterdir()], ["system_information.md"]
        )

    def test_save_rejects_get(self):
        """保存はPOST限定"""
        response = self.client.get(reverse("service_admin:notice_save"))

        self.assertEqual(response.status_code, 405)

    def test_preview_returns_rendered_html(self):
        """プレビューは未保存の内容をHTML化して返す"""
        response = self.client.post(
            reverse("service_admin:notice_preview"), {"content": "# 見出し"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("<h1>", response.json()["html"])
        # 保存はされない
        self.assertEqual(self.md.read_text(encoding="utf-8"), "# 元のお知らせ")

    def test_preview_empty_shows_placeholder(self):
        """空入力のプレビューは代替文言"""
        response = self.client.post(reverse("service_admin:notice_preview"), {"content": "  "})

        self.assertEqual(response.json()["html"], "（お知らせ無し）")


class ServiceAdminNoticePermissionTest(TestCase):
    """お知らせ更新系エンドポイントの権限のテスト"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmpdir, ignore_errors=True))
        self.md = Path(self.tmpdir) / "system_information.md"
        self.md.write_text("original", encoding="utf-8")

    def test_general_user_cannot_save(self):
        """一般ユーザーの保存はリダイレクトされ、ファイルは変わらない"""
        self.client.force_login(_make_user())

        with mock.patch("app.home.views.SYSTEM_INFO_MD", self.md):
            response = self.client.post(
                reverse("service_admin:notice_save"), {"content": "hacked"}
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertEqual(self.md.read_text(encoding="utf-8"), "original")

    def test_anonymous_cannot_preview(self):
        """未ログインはプレビューも不可"""
        response = self.client.post(
            reverse("service_admin:notice_preview"), {"content": "# x"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


# ══════════════════════════════════════════════════
# サービス管理: 商談用アクセスの発行
# ══════════════════════════════════════════════════


class ServiceAdminMeetingIssueTest(TestCase):
    """商談用アクセスの発行（既存ユーザー）のテスト"""

    def setUp(self):
        self.admin = _make_superuser()
        self.target = _make_user(username="client-a")
        self.client.force_login(self.admin)
        self.url = reverse("service_admin:meeting_issue")
        self.payload = {
            "label": "A社 商談",
            "username": "client-a",
            "expire_days": "10",
            "regenerate_password": "on",
        }

    def test_creates_access_with_hashed_token(self):
        """発行するとトークンはハッシュで保存される"""
        response = self.client.post(self.url, self.payload)

        access = MeetingAccess.objects.get()
        self.assertRedirects(response, reverse("service_admin:index"))
        self.assertEqual(access.label, "A社 商談")
        self.assertEqual(access.user, self.target)
        self.assertEqual(access.issuer, self.admin)
        self.assertEqual(len(access.token_hash), 40)

    def test_issued_url_is_short_guest_path(self):
        """発行URLは /guest/<token>/ の形式"""
        self.client.post(self.url, self.payload)

        issued = self.client.session["service_admin_issued"]
        self.assertRegex(issued["url"], r"^http://testserver/guest/[a-z0-9]+/$")

    def test_issued_url_matches_stored_hash(self):
        """画面に出すURLのトークンが保存済みハッシュと対応する"""
        self.client.post(self.url, self.payload)

        issued = self.client.session["service_admin_issued"]
        raw_token = issued["url"].rstrip("/").rsplit("/", 1)[-1]
        self.assertEqual(MeetingAccess.objects.get().token_hash, hash_meeting_token(raw_token))

    @override_settings(MEETING_TOKEN_LENGTH=15)
    def test_token_length_follows_setting(self):
        """トークン桁数は設定値に従う（既定15桁）"""
        self.client.post(self.url, self.payload)

        raw_token = self.client.session["service_admin_issued"]["url"].rstrip("/").rsplit("/", 1)[-1]
        self.assertEqual(len(raw_token), 15)

    def test_password_is_regenerated_when_checked(self):
        """パスワード再生成ありなら新しいパスワードが有効になる"""
        self.client.post(self.url, self.payload)

        issued = self.client.session["service_admin_issued"]
        self.target.refresh_from_db()
        self.assertTrue(issued["password"])
        self.assertTrue(self.target.check_password(issued["password"]))

    def test_password_kept_when_not_checked(self):
        """再生成なしなら既存パスワードのまま"""
        payload = dict(self.payload)
        payload.pop("regenerate_password")

        self.client.post(self.url, payload)

        self.target.refresh_from_db()
        self.assertEqual(self.client.session["service_admin_issued"]["password"], "")
        self.assertTrue(self.target.check_password("test-pass-1234"))

    @override_settings(MEETING_EXPIRE_DAYS=30)
    def test_expire_days_is_capped_by_setting(self):
        """有効日数は設定の上限を超えられない"""
        payload = dict(self.payload, expire_days="9999")

        self.client.post(self.url, payload)

        access = MeetingAccess.objects.get()
        self.assertLessEqual(access.expires_at, timezone.now() + timedelta(days=30, seconds=5))

    def test_missing_label_is_rejected(self):
        """商談名が無ければ発行しない"""
        payload = dict(self.payload, label="")

        response = self.client.post(self.url, payload, follow=True)

        self.assertEqual(MeetingAccess.objects.count(), 0)
        self.assertContains(response, "商談名・相手先を入力してください")

    def test_unknown_user_is_rejected(self):
        """存在しないユーザーには発行しない"""
        payload = dict(self.payload, username="nobody")

        response = self.client.post(self.url, payload, follow=True)

        self.assertEqual(MeetingAccess.objects.count(), 0)
        self.assertContains(response, "対象ユーザーが見つかりません")

    def test_general_user_cannot_issue(self):
        """一般ユーザーは発行できない"""
        self.client.force_login(_make_user(username="normal"))

        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertEqual(MeetingAccess.objects.count(), 0)


class ServiceAdminMeetingIssueNewUserTest(TestCase):
    """発行フォームからのユーザー新規作成のテスト"""

    def setUp(self):
        self.admin = _make_superuser()
        self.client.force_login(self.admin)
        self.url = reverse("service_admin:meeting_issue")
        self.payload = {
            "label": "B社 商談",
            "username": "__new__",
            "new_username": "client-b",
            "expire_days": "10",
        }

    def test_creates_user_and_access_together(self):
        """ユーザー作成と発行が1回の操作で完了する"""
        response = self.client.post(self.url, self.payload)

        self.assertRedirects(response, reverse("service_admin:index"))
        user = User.objects.get(username="client-b")
        self.assertEqual(MeetingAccess.objects.get().user, user)

    def test_password_is_generated_for_new_user(self):
        """新規ユーザーのパスワードは自動生成され、そのまま使える"""
        self.client.post(self.url, self.payload)

        issued = self.client.session["service_admin_issued"]
        user = User.objects.get(username="client-b")
        self.assertTrue(issued["password"])
        self.assertTrue(user.check_password(issued["password"]))

    def test_duplicate_username_is_rejected(self):
        """既存と重複するユーザー名は作成せず発行もしない"""
        _make_user(username="client-b")

        response = self.client.post(self.url, self.payload, follow=True)

        self.assertEqual(MeetingAccess.objects.count(), 0)
        self.assertContains(response, "ユーザー作成に失敗しました")

    def test_invalid_username_is_rejected(self):
        """ユーザー名の形式が不正なら作成しない"""
        payload = dict(self.payload, new_username="bad name!")

        self.client.post(self.url, payload)

        self.assertEqual(User.objects.filter(username="bad name!").count(), 0)
        self.assertEqual(MeetingAccess.objects.count(), 0)

    def test_empty_username_is_rejected(self):
        """ユーザー名が空なら作成しない"""
        payload = dict(self.payload, new_username="")

        self.client.post(self.url, payload)

        self.assertEqual(MeetingAccess.objects.count(), 0)


class ServiceAdminIssuedPanelTest(TestCase):
    """発行結果パネルの表示・破棄のテスト"""

    def setUp(self):
        self.admin = _make_superuser()
        _make_user(username="client-a")
        self.client.force_login(self.admin)
        self.client.post(
            reverse("service_admin:meeting_issue"),
            {"label": "A社 商談", "username": "client-a", "expire_days": "10",
             "regenerate_password": "on"},
        )

    def test_panel_survives_reload(self):
        """閉じるまで再読み込みしても残る（控え損ねの救済）"""
        first = self.client.get(reverse("service_admin:index"))
        second = self.client.get(reverse("service_admin:index"))

        self.assertIsNotNone(first.context["issued"])
        self.assertIsNotNone(second.context["issued"])

    def test_dismiss_clears_panel(self):
        """「閉じる」でセッションから消える"""
        response = self.client.post(reverse("service_admin:issued_dismiss"))

        self.assertRedirects(response, reverse("service_admin:index"))
        self.assertIsNone(
            self.client.get(reverse("service_admin:index")).context["issued"]
        )

    def test_panel_shows_url_and_password(self):
        """URLとパスワードが画面に出る"""
        issued = self.client.session["service_admin_issued"]

        response = self.client.get(reverse("service_admin:index"))

        self.assertContains(response, issued["url"])
        self.assertContains(response, issued["password"])

    def test_general_user_cannot_dismiss(self):
        """一般ユーザーは操作できない"""
        self.client.force_login(_make_user(username="normal"))

        response = self.client.post(reverse("service_admin:issued_dismiss"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class ServiceAdminMeetingReissueTest(TestCase):
    """再発行のテスト"""

    def setUp(self):
        self.admin = _make_superuser()
        self.target = _make_user(username="client-a")
        self.client.force_login(self.admin)
        self.client.post(
            reverse("service_admin:meeting_issue"),
            {"label": "A社 商談", "username": "client-a", "expire_days": "10",
             "regenerate_password": "on"},
        )
        self.old = MeetingAccess.objects.get()
        self.old_issued = dict(self.client.session["service_admin_issued"])
        self.url = reverse("service_admin:meeting_reissue", args=[self.old.id])

    def test_creates_new_access_and_revokes_old(self):
        """新しいアクセスを作り、元のトークンは失効する"""
        response = self.client.post(self.url)

        self.old.refresh_from_db()
        self.assertRedirects(response, reverse("service_admin:index"))
        self.assertEqual(MeetingAccess.objects.count(), 2)
        self.assertIsNotNone(self.old.revoked_at)

    def test_new_access_keeps_label_and_user(self):
        """商談名とユーザーは引き継ぐ"""
        self.client.post(self.url)

        new = MeetingAccess.objects.exclude(id=self.old.id).get()
        self.assertEqual(new.label, self.old.label)
        self.assertEqual(new.user, self.old.user)

    def test_url_and_password_are_new(self):
        """URLもパスワードも新しい値になる"""
        self.client.post(self.url)

        issued = self.client.session["service_admin_issued"]
        self.target.refresh_from_db()
        self.assertNotEqual(issued["url"], self.old_issued["url"])
        self.assertNotEqual(issued["password"], self.old_issued["password"])
        self.assertTrue(self.target.check_password(issued["password"]))

    def test_old_link_stops_working(self):
        """再発行後、以前のURLは使えない"""
        self.client.post(self.url)

        guest = self.client_class()
        self.assertEqual(guest.get(self.old_issued["url"]).status_code, 404)

    def test_general_user_cannot_reissue(self):
        """一般ユーザーは再発行できない"""
        self.client.force_login(_make_user(username="normal"))

        self.client.post(self.url)

        self.assertEqual(MeetingAccess.objects.count(), 1)

    def test_unknown_id_returns_404(self):
        """存在しないIDは404"""
        response = self.client.post(reverse("service_admin:meeting_reissue", args=[9999]))

        self.assertEqual(response.status_code, 404)


class ServiceAdminMeetingRevokeTest(TestCase):
    """商談用アクセスの失効のテスト"""

    def setUp(self):
        self.admin = _make_superuser()
        self.target = _make_user(username="client-a")
        self.access = MeetingAccess.objects.create(
            label="A社 商談",
            user=self.target,
            issuer=self.admin,
            token_hash=hash_meeting_token("dummy-token"),
            expires_at=timezone.now() + timedelta(days=10),
        )
        self.url = reverse("service_admin:meeting_revoke", args=[self.access.id])

    def test_superuser_can_revoke(self):
        """管理者は失効できる"""
        self.client.force_login(self.admin)

        response = self.client.post(self.url)

        self.access.refresh_from_db()
        self.assertRedirects(response, reverse("service_admin:index"))
        self.assertIsNotNone(self.access.revoked_at)
        self.assertEqual(self.access.revoked_reason, MeetingAccess.REVOKE_MANUAL)

    def test_general_user_cannot_revoke(self):
        """一般ユーザーは失効できない"""
        self.client.force_login(_make_user(username="normal"))

        self.client.post(self.url)

        self.access.refresh_from_db()
        self.assertIsNone(self.access.revoked_at)

    def test_unknown_id_returns_404(self):
        """存在しないIDは404"""
        self.client.force_login(self.admin)

        response = self.client.post(reverse("service_admin:meeting_revoke", args=[9999]))

        self.assertEqual(response.status_code, 404)


class ServiceAdminMeetingListTest(TestCase):
    """商談用アクセス一覧のテスト"""

    def setUp(self):
        self.admin = _make_superuser()
        self.target = _make_user(username="client-a")
        self.client.force_login(self.admin)
        self.access = MeetingAccess.objects.create(
            label="A社 商談",
            user=self.target,
            token_hash=hash_meeting_token("dummy-token"),
            expires_at=timezone.now() + timedelta(days=10),
        )

    def test_context_lists_accesses(self):
        """一覧に発行済みアクセスが並ぶ"""
        response = self.client.get(reverse("service_admin:index"))

        self.assertEqual(
            [a.id for a in response.context["meeting_accesses"]], [self.access.id]
        )

    def test_lock_counter_is_attached(self):
        """各行に失敗カウンタが添えられる"""
        LoginLockout.objects.create(key=self.access.lock_key, fail_count=2, fail_total=7)

        response = self.client.get(reverse("service_admin:index"))

        access = response.context["meeting_accesses"][0]
        self.assertEqual(access.lock.fail_count, 2)
        self.assertEqual(access.lock.fail_total, 7)

    def test_lock_is_none_without_failures(self):
        """失敗が無ければ lock は None"""
        response = self.client.get(reverse("service_admin:index"))

        self.assertIsNone(response.context["meeting_accesses"][0].lock)


class ServiceAdminMeetingEndToEndTest(TestCase):
    """発行 → 着地 → パスワード入力 の一連の流れのテスト"""

    def test_new_user_flow_works(self):
        """ユーザー新規作成つきの発行から、相手がログインするまで通る"""
        self.client.force_login(_make_superuser())

        self.client.post(
            reverse("service_admin:meeting_issue"),
            {
                "label": "A社 商談",
                "username": "__new__",
                "new_username": "client-a",
                "expire_days": "10",
            },
        )
        issued = self.client.session["service_admin_issued"]

        # 相手側（別セッション）でURLを踏み、パスワードを入力する
        guest = self.client_class()
        landing = guest.get(issued["url"])
        self.assertEqual(landing.status_code, 302)
        self.assertEqual(landing["Location"], "/guest/")

        response = guest.post(landing["Location"], {"password": issued["password"]})

        self.assertEqual(response["Location"], "/home/")
        self.assertIn("_auth_user_id", guest.session)
        self.assertEqual(
            LoginHistory.objects.latest("id").meeting_access,
            MeetingAccess.objects.get(),
        )
