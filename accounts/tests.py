from datetime import timedelta

from django.contrib.auth.models import AnonymousUser, User
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from .middleware import get_client_ip
from .models import LoginHistory
from .views import is_superuser, signup_permission_denied


def _make_user(username="testuser", password="test-pass-1234", **kwargs):
    return User.objects.create_user(username=username, password=password, **kwargs)


def _make_superuser(username="admin", password="admin-pass-1234"):
    return User.objects.create_superuser(username=username, password=password)


class AuthUrlResolveTest(SimpleTestCase):
    """accounts のURL解決をテスト"""

    def test_reverse_login(self):
        """accounts:login が /accounts/login/ に解決される"""
        self.assertEqual(reverse("accounts:login"), "/accounts/login/")

    def test_reverse_logout(self):
        """accounts:logout が解決される"""
        self.assertEqual(reverse("accounts:logout"), "/accounts/logout/")

    def test_reverse_signup(self):
        """accounts:signup が解決される"""
        self.assertEqual(reverse("accounts:signup"), "/accounts/signup/")

    def test_reverse_password_change(self):
        """パスワード変更系のURLが解決される"""
        self.assertEqual(reverse("accounts:password_change"), "/accounts/password_change/")
        self.assertEqual(reverse("accounts:password_change_done"), "/accounts/password_change/done/")

    def test_reverse_password_reset(self):
        """パスワードリセット系のURLが解決される"""
        self.assertEqual(reverse("accounts:password_reset"), "/accounts/password_reset/")
        self.assertEqual(reverse("accounts:password_reset_done"), "/accounts/password_reset/done/")
        self.assertEqual(reverse("accounts:password_reset_complete"), "/accounts/reset/done/")

    def test_reverse_password_reset_confirm(self):
        """パスワードリセット確認URLがトークン付きで解決される"""
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": "MQ", "token": "abc-def"},
        )
        self.assertEqual(url, "/accounts/reset/MQ/abc-def/")


class IsSuperuserTest(TestCase):
    """is_superuser のテスト"""

    def test_superuser_returns_true(self):
        """スーパーユーザーなら True"""
        self.assertTrue(is_superuser(_make_superuser()))

    def test_normal_user_returns_false(self):
        """一般ユーザーなら False"""
        self.assertFalse(is_superuser(_make_user()))


class LoginViewTest(TestCase):
    """ログインビューのテスト"""

    def setUp(self):
        self.user = _make_user()
        self.url = reverse("accounts:login")

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_get_renders_login_template(self):
        """GETでログイン画面が表示される"""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")

    def test_post_valid_credentials_redirects_to_home(self):
        """正しい資格情報でログインすると LOGIN_REDIRECT_URL へリダイレクト"""
        response = self.client.post(
            self.url,
            {"username": "testuser", "password": "test-pass-1234"},
        )

        self.assertRedirects(response, "/home/", fetch_redirect_response=False)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_post_respects_next_parameter(self):
        """nextパラメータが指定されていればそちらへリダイレクト"""
        response = self.client.post(
            f"{self.url}?next=/skill_sheet/",
            {"username": "testuser", "password": "test-pass-1234"},
        )

        self.assertRedirects(response, "/skill_sheet/", fetch_redirect_response=False)

    # ──────────────────────────────────────────────
    # エラー系
    # ──────────────────────────────────────────────

    def test_post_invalid_password_rerenders_form(self):
        """パスワードが誤っている場合は200で再表示され、ログインしない"""
        response = self.client.post(
            self.url,
            {"username": "testuser", "password": "wrong-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")
        self.assertNotIn("_auth_user_id", self.client.session)


class LogoutViewTest(TestCase):
    """ログアウトビューのテスト"""

    def setUp(self):
        self.user = _make_user()

    def test_post_logs_out_and_redirects(self):
        """POSTでログアウトし LOGOUT_REDIRECT_URL へリダイレクト"""
        self.client.force_login(self.user)

        response = self.client.post(reverse("accounts:logout"))

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)


class SignUpViewTest(TestCase):
    """SignUpView（管理者によるユーザー作成）のテスト"""

    def setUp(self):
        self.url = reverse("accounts:signup")
        self.superuser = _make_superuser()
        self.normal_user = _make_user()

    # ──────────────────────────────────────────────
    # 認可
    # ──────────────────────────────────────────────

    def test_anonymous_redirects_to_login(self):
        """未ログイン時はログインURLへリダイレクト"""
        response = self.client.get(self.url)

        self.assertRedirects(
            response,
            f"/accounts/login/?next={self.url}",
            fetch_redirect_response=False,
        )

    def test_normal_user_redirects_to_login(self):
        """一般ユーザーは user_passes_test によりログインURLへリダイレクト（403ではない）"""
        self.client.force_login(self.normal_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_superuser_can_access(self):
        """スーパーユーザーはサインアップ画面にアクセスできる"""
        self.client.force_login(self.superuser)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/signup.html")

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_post_creates_user_and_redirects_home(self):
        """POST成功でユーザーが作成され home:home へリダイレクト"""
        self.client.force_login(self.superuser)

        response = self.client.post(
            self.url,
            {
                "username": "newcomer",
                "password1": "very-strong-pass-9876",
                "password2": "very-strong-pass-9876",
            },
        )

        self.assertRedirects(response, reverse("home:home"), fetch_redirect_response=False)
        self.assertTrue(User.objects.filter(username="newcomer").exists())

    def test_post_success_adds_message_and_log(self):
        """POST成功時に成功メッセージとログが出力される"""
        self.client.force_login(self.superuser)

        with self.assertLogs("accounts", level="INFO") as cm:
            response = self.client.post(
                self.url,
                {
                    "username": "logged-user",
                    "password1": "very-strong-pass-9876",
                    "password2": "very-strong-pass-9876",
                },
                follow=False,
            )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("新規ユーザー作成" in line for line in cm.output))

    # ──────────────────────────────────────────────
    # エラー系
    # ──────────────────────────────────────────────

    def test_post_password_mismatch_does_not_create_user(self):
        """パスワード不一致時は200で再表示され、ユーザーは作成されない"""
        self.client.force_login(self.superuser)

        response = self.client.post(
            self.url,
            {
                "username": "ng-user",
                "password1": "very-strong-pass-9876",
                "password2": "different-pass-1234",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/signup.html")
        self.assertFalse(User.objects.filter(username="ng-user").exists())

    def test_post_duplicate_username_does_not_create_user(self):
        """ユーザー名重複時はユーザーが作成されない"""
        self.client.force_login(self.superuser)

        response = self.client.post(
            self.url,
            {
                "username": self.normal_user.username,
                "password1": "very-strong-pass-9876",
                "password2": "very-strong-pass-9876",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username=self.normal_user.username).count(), 1)

    def test_post_invalid_outputs_warning_log(self):
        """POST失敗時に警告ログが出力される"""
        self.client.force_login(self.superuser)

        with self.assertLogs("accounts", level="WARNING") as cm:
            self.client.post(
                self.url,
                {
                    "username": "ng-user2",
                    "password1": "very-strong-pass-9876",
                    "password2": "mismatch",
                },
            )

        self.assertTrue(any("ユーザー作成失敗" in line for line in cm.output))


class SignupPermissionDeniedViewTest(TestCase):
    """signup_permission_denied のテスト

    NOTE: このビューは accounts/urls.py に登録されていないため、
          reverse() ではなく直接呼び出しで検証する。
    """

    def setUp(self):
        self.factory = RequestFactory()

    def test_get_returns_403(self):
        """GETで403を返し専用テンプレートを使う"""
        request = self.factory.get("/dummy/")
        request.user = AnonymousUser()

        response = signup_permission_denied(request)

        self.assertEqual(response.status_code, 403)

    def test_post_returns_405(self):
        """GET以外は405を返す"""
        request = self.factory.post("/dummy/")
        request.user = AnonymousUser()

        response = signup_permission_denied(request)

        self.assertEqual(response.status_code, 405)


class GetClientIpTest(SimpleTestCase):
    """get_client_ip のテスト"""

    def setUp(self):
        self.factory = RequestFactory()

    def test_uses_remote_addr_by_default(self):
        """X-Forwarded-For が無ければ REMOTE_ADDR を使う"""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")

        self.assertEqual(get_client_ip(request), "10.0.0.1")

    def test_x_forwarded_for_takes_priority(self):
        """X-Forwarded-For があれば先頭のIPを優先する"""
        request = self.factory.get(
            "/",
            REMOTE_ADDR="10.0.0.1",
            HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.2",
        )

        self.assertEqual(get_client_ip(request), "203.0.113.5")

    def test_returns_none_when_nothing_set(self):
        """どちらも無い場合は None"""
        request = self.factory.get("/")
        request.META.pop("REMOTE_ADDR", None)

        self.assertIsNone(get_client_ip(request))


class AuthSignalLogTest(TestCase):
    """accounts/middleware.py のシグナルレシーバのテスト"""

    def setUp(self):
        self.user = _make_user()

    def test_login_success_is_logged(self):
        """ログイン成功時に INFO ログが出力される"""
        with self.assertLogs("accounts", level="INFO") as cm:
            self.client.post(
                reverse("accounts:login"),
                {"username": "testuser", "password": "test-pass-1234"},
            )

        self.assertTrue(any("ログイン成功: testuser" in line for line in cm.output))

    def test_login_failed_is_logged(self):
        """ログイン失敗時に WARNING ログが出力される"""
        with self.assertLogs("accounts", level="WARNING") as cm:
            self.client.post(
                reverse("accounts:login"),
                {"username": "testuser", "password": "wrong-password"},
            )

        self.assertTrue(any("ログイン失敗: testuser" in line for line in cm.output))

    def test_logout_is_logged(self):
        """ログアウト時に INFO ログが出力される"""
        self.client.force_login(self.user)

        with self.assertLogs("accounts", level="INFO") as cm:
            self.client.post(reverse("accounts:logout"))

        self.assertTrue(any("ログアウト: testuser" in line for line in cm.output))


class LoginHistoryRecordTest(TestCase):
    """ログイン成功時に LoginHistory が記録されることのテスト"""

    def setUp(self):
        self.user = _make_user()
        self.login_url = reverse("accounts:login")

    def _login(self, **extra):
        return self.client.post(
            self.login_url,
            {"username": "testuser", "password": "test-pass-1234"},
            **extra,
        )

    def test_login_creates_history_row(self):
        """ログイン成功で履歴が1件作られ、ユーザーが紐づく"""
        self._login()

        self.assertEqual(LoginHistory.objects.filter(user=self.user).count(), 1)

    def test_history_stores_ip_address(self):
        """REMOTE_ADDR が IPアドレスとして保存される"""
        self._login(REMOTE_ADDR="198.51.100.7")

        history = LoginHistory.objects.get(user=self.user)
        self.assertEqual(history.ip_address, "198.51.100.7")

    def test_history_uses_forwarded_ip(self):
        """X-Forwarded-For の先頭を優先して保存する"""
        self._login(HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.2", REMOTE_ADDR="10.0.0.2")

        history = LoginHistory.objects.get(user=self.user)
        self.assertEqual(history.ip_address, "203.0.113.9")

    def test_failed_login_creates_no_history(self):
        """ログイン失敗では履歴を作らない"""
        self.client.post(
            self.login_url,
            {"username": "testuser", "password": "wrong-password"},
        )

        self.assertEqual(LoginHistory.objects.count(), 0)

    def test_multiple_logins_accumulate(self):
        """ログインの度に履歴が積み上がる"""
        self._login()
        self.client.post(reverse("accounts:logout"))
        self._login()

        self.assertEqual(LoginHistory.objects.filter(user=self.user).count(), 2)


class PruneLoginHistoryCommandTest(TestCase):
    """prune_login_history 管理コマンドのテスト"""

    def setUp(self):
        self.user = _make_user()
        now = timezone.now()
        # 100日前（削除対象）と 10日前（保持）を1件ずつ用意する
        self.old = LoginHistory.objects.create(
            user=self.user, logged_in_at=now - timedelta(days=100)
        )
        self.recent = LoginHistory.objects.create(
            user=self.user, logged_in_at=now - timedelta(days=10)
        )

    def test_default_prunes_older_than_90_days(self):
        """既定 90日より前のみ削除される"""
        call_command("prune_login_history")

        remaining = list(LoginHistory.objects.all())
        self.assertEqual(remaining, [self.recent])

    def test_days_option_controls_cutoff(self):
        """--days で保持期間を変えられる（5日なら両方削除）"""
        call_command("prune_login_history", "--days", "5")

        self.assertEqual(LoginHistory.objects.count(), 0)

    def test_dry_run_deletes_nothing(self):
        """--dry-run は削除しない"""
        call_command("prune_login_history", "--dry-run")

        self.assertEqual(LoginHistory.objects.count(), 2)
