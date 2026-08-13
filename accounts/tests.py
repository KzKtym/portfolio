from datetime import timedelta

from django.contrib.auth.models import AnonymousUser, User
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import lockout
from .middleware import SESSION_MEETING_KEY, get_client_ip
from .models import (
    LoginHistory,
    LoginLockout,
    MeetingAccess,
    generate_meeting_password,
    generate_meeting_token,
    hash_meeting_token,
)
from app.common.permissions import is_superuser
from .views import signup_permission_denied


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

    def test_reverse_guest_urls(self):
        """商談用アクセスのURLは短い /guest/ 配下に解決される"""
        self.assertEqual(reverse("guest:login"), "/guest/")
        self.assertEqual(reverse("guest:entry", args=["arykz3jo69k964j"]), "/guest/arykz3jo69k964j/")

    def test_reverse_password_reset_confirm(self):
        """パスワードリセット確認URLがトークン付きで解決される"""
        url = reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": "MQ", "token": "abc-def"},
        )
        self.assertEqual(url, "/accounts/reset/MQ/abc-def/")


class IsSuperuserTest(TestCase):
    """is_superuser が実ユーザーに対して期待どおり働くことのテスト。

    述語そのものの単体テストは app/common/tests.py 側にある。ここでは
    accounts のビューが実際に使う経路（Django の User モデル）で確認する。
    """

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


# ══════════════════════════════════════════════════
# ログイン失敗のロック
# ══════════════════════════════════════════════════


@override_settings(
    LOGIN_LOCK_THRESHOLD=3,
    LOGIN_LOCK_SECONDS=60,
    LOGIN_LOCK_MAX_SECONDS=600,
    MEETING_REVOKE_THRESHOLD=6,
)
class LockoutHelperTest(TestCase):
    """accounts/lockout.py のテスト"""

    def test_no_lock_before_threshold(self):
        """閾値未満ならロックされない"""
        for _ in range(2):
            lock = lockout.register_failure("user:x")

        self.assertEqual(lock.fail_count, 2)
        self.assertFalse(lock.is_locked())
        self.assertEqual(lockout.check_locked("user:x"), 0)

    def test_locks_at_threshold(self):
        """閾値ちょうどでロックがかかる"""
        for _ in range(3):
            lock = lockout.register_failure("user:x")

        self.assertTrue(lock.is_locked())
        self.assertGreater(lockout.check_locked("user:x"), 0)

    def test_lock_seconds_double_after_threshold(self):
        """閾値を超えるごとにロック秒数が倍になる"""
        self.assertEqual(lockout._lock_seconds(3), 60)
        self.assertEqual(lockout._lock_seconds(4), 120)
        self.assertEqual(lockout._lock_seconds(5), 240)

    def test_lock_seconds_capped(self):
        """倍化は上限で頭打ちになる"""
        self.assertEqual(lockout._lock_seconds(30), 600)

    def test_counter_does_not_recover_with_time(self):
        """時間経過ではカウンタが戻らない（ロック解除だけが進む）"""
        for _ in range(3):
            lockout.register_failure("user:x")
        lock = LoginLockout.objects.get(key="user:x")
        lock.locked_until = timezone.now() - timedelta(seconds=1)
        lock.save(update_fields=["locked_until"])

        self.assertEqual(lockout.check_locked("user:x"), 0)
        self.assertEqual(LoginLockout.objects.get(key="user:x").fail_count, 3)

    def test_success_resets_consecutive_count_only(self):
        """成功で連続カウンタとロックは消えるが、累計は残る"""
        for _ in range(3):
            lockout.register_failure("user:x")

        lockout.register_success("user:x")

        lock = LoginLockout.objects.get(key="user:x")
        self.assertEqual(lock.fail_count, 0)
        self.assertIsNone(lock.locked_until)
        self.assertEqual(lock.fail_total, 3)

    def test_should_revoke_at_total_threshold(self):
        """累計が失効閾値に達したら should_revoke が真"""
        for _ in range(5):
            lock = lockout.register_failure("meeting:1")
        self.assertFalse(lockout.should_revoke(lock))

        lock = lockout.register_failure("meeting:1")
        self.assertTrue(lockout.should_revoke(lock))

    @override_settings(LOGIN_LOCK_SCOPE="user_ip")
    def test_user_key_includes_ip_by_default(self):
        """既定のロック単位はユーザー名+IP"""
        self.assertEqual(lockout.user_key("taro", "203.0.113.5"), "user:taro@203.0.113.5")

    @override_settings(LOGIN_LOCK_SCOPE="user")
    def test_user_key_can_ignore_ip(self):
        """LOGIN_LOCK_SCOPE='user' ならIPを含めない"""
        self.assertEqual(lockout.user_key("taro", "203.0.113.5"), "user:taro")


@override_settings(LOGIN_LOCK_THRESHOLD=3, LOGIN_LOCK_SECONDS=60)
class LockedLoginViewTest(TestCase):
    """ID/PWログインのロックのテスト"""

    def setUp(self):
        self.user = _make_user(username="taro", password="right-pass-1234")
        self.url = reverse("accounts:login")

    def _fail(self):
        return self.client.post(self.url, {"username": "taro", "password": "wrong"})

    def test_failures_are_counted(self):
        """失敗が数えられる"""
        self._fail()

        lock = LoginLockout.objects.get()
        self.assertEqual(lock.fail_count, 1)
        self.assertEqual(lock.fail_total, 1)

    def test_correct_password_is_rejected_while_locked(self):
        """ロック中は正しいパスワードでもログインさせない"""
        for _ in range(3):
            self._fail()

        response = self.client.post(
            self.url, {"username": "taro", "password": "right-pass-1234"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_succeeds_before_threshold(self):
        """閾値未満なら正しいパスワードでログインできる"""
        self._fail()

        response = self.client.post(
            self.url, {"username": "taro", "password": "right-pass-1234"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)

    def test_success_clears_lock_counter(self):
        """成功すると連続カウンタが戻る"""
        self._fail()
        self.client.post(self.url, {"username": "taro", "password": "right-pass-1234"})

        self.assertEqual(LoginLockout.objects.get().fail_count, 0)

    def test_lock_is_logged(self):
        """ロック時に WARNING ログが出る"""
        self._fail()
        self._fail()
        with self.assertLogs("accounts", level="WARNING") as cm:
            self._fail()

        self.assertTrue(any("ログイン試行をロック" in line for line in cm.output))

    @override_settings(LOGIN_LOCK_SCOPE="user_ip")
    def test_other_ip_is_not_locked_out(self):
        """既定のスコープでは別IPからのログインは巻き添えにならない"""
        for _ in range(3):
            self._fail()

        response = self.client.post(
            self.url,
            {"username": "taro", "password": "right-pass-1234"},
            REMOTE_ADDR="203.0.113.9",
        )

        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(response.status_code, 302)


# ══════════════════════════════════════════════════
# 商談用アクセス
# ══════════════════════════════════════════════════


def _issue_access(user, issuer=None, label="A社 商談", days=30, **kwargs):
    """テスト用に商談用アクセスを1件発行し (access, 生トークン) を返す"""
    raw_token = generate_meeting_token()
    access = MeetingAccess.objects.create(
        label=label,
        user=user,
        issuer=issuer,
        token_hash=hash_meeting_token(raw_token),
        expires_at=timezone.now() + timedelta(days=days),
        **kwargs,
    )
    return access, raw_token


class MeetingAccessModelTest(TestCase):
    """MeetingAccess モデルのテスト"""

    def setUp(self):
        self.user = _make_user()

    def test_token_is_not_stored_in_plain_text(self):
        """生トークンはDBに残らない"""
        access, raw_token = _issue_access(self.user)

        self.assertNotEqual(access.token_hash, raw_token)
        self.assertEqual(access.token_hash, hash_meeting_token(raw_token))

    def test_hash_is_deterministic_and_unique(self):
        """同じトークンは同じハッシュ、違うトークンは違うハッシュ"""
        self.assertEqual(hash_meeting_token("abc"), hash_meeting_token("abc"))
        self.assertNotEqual(hash_meeting_token("abc"), hash_meeting_token("abd"))

    @override_settings(MEETING_TOKEN_LENGTH=32, MEETING_PASSWORD_LENGTH=16)
    def test_generated_values_have_configured_length(self):
        """桁数は設定値に従う"""
        self.assertEqual(len(generate_meeting_token()), 32)
        self.assertEqual(len(generate_meeting_password()), 16)

    def test_generated_password_excludes_ambiguous_chars(self):
        """紛らわしい文字（0/O/1/l/I）を含まない"""
        for _ in range(20):
            self.assertFalse(set(generate_meeting_password()) & set("0O1lI"))

    def test_available_when_fresh(self):
        """発行直後は利用可能"""
        access, _ = _issue_access(self.user)

        self.assertTrue(access.is_available())
        self.assertEqual(access.status, "有効")

    def test_not_available_after_expiry(self):
        """絶対期限を過ぎたら利用不可"""
        access, _ = _issue_access(self.user, days=-1)

        self.assertFalse(access.is_available())
        self.assertEqual(access.status, "期限切れ")

    @override_settings(MEETING_IDLE_DAYS=7)
    def test_not_available_after_idle_period(self):
        """無操作期限を過ぎたら利用不可"""
        access, _ = _issue_access(self.user)
        access.last_accessed_at = timezone.now() - timedelta(days=8)
        access.save(update_fields=["last_accessed_at"])

        self.assertFalse(access.is_available())
        self.assertEqual(access.status, "無操作期限切れ")

    @override_settings(MEETING_IDLE_DAYS=0)
    def test_idle_check_can_be_disabled(self):
        """MEETING_IDLE_DAYS=0 なら無操作期限は効かない"""
        access, _ = _issue_access(self.user)
        access.last_accessed_at = timezone.now() - timedelta(days=100)
        access.save(update_fields=["last_accessed_at"])

        self.assertTrue(access.is_available())

    def test_revoke_sets_reason_once(self):
        """失効は理由付きで記録され、二重に上書きされない"""
        access, _ = _issue_access(self.user)

        access.revoke(MeetingAccess.REVOKE_LOCKOUT)
        first_revoked_at = access.revoked_at
        access.revoke(MeetingAccess.REVOKE_MANUAL)

        self.assertEqual(access.revoked_at, first_revoked_at)
        self.assertEqual(access.revoked_reason, MeetingAccess.REVOKE_LOCKOUT)
        self.assertFalse(access.is_available())


class MeetingEntryTest(TestCase):
    """トークンURL着地のテスト"""

    def setUp(self):
        self.user = _make_user(password="meeting-pass-1234")
        self.access, self.raw_token = _issue_access(self.user)

    def _entry_url(self, token):
        return reverse("guest:entry", args=[token])

    def test_valid_token_redirects_without_token_in_url(self):
        """有効なトークンはURLにトークンを含まない画面へ302で飛ばす"""
        response = self.client.get(self._entry_url(self.raw_token))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("guest:login"))
        self.assertNotIn(self.raw_token, response["Location"])

    def test_valid_token_stores_access_in_session(self):
        """トークンはセッションへ移される"""
        self.client.get(self._entry_url(self.raw_token))

        self.assertEqual(self.client.session[SESSION_MEETING_KEY], self.access.id)

    def test_entry_does_not_log_in(self):
        """着地しただけではログインしない"""
        self.client.get(self._entry_url(self.raw_token))

        self.assertNotIn("_auth_user_id", self.client.session)

    def test_referrer_policy_header(self):
        """Referrer-Policy が付く（外部へURLを渡さない）"""
        response = self.client.get(self._entry_url(self.raw_token))

        self.assertEqual(response["Referrer-Policy"], "same-origin")

    def test_referrer_policy_is_not_no_referrer(self):
        """'no-referrer' は使わない。

        Chrome がフォーム送信時に Origin: null を送るようになり、
        パスワード入力のPOSTがCSRF検証で必ず弾かれるため。
        """
        self.client.get(self._entry_url(self.raw_token))

        response = self.client.get(reverse("guest:login"))

        self.assertNotEqual(response["Referrer-Policy"], "no-referrer")

    def test_unknown_token_returns_404(self):
        """存在しないトークンは404（理由は伏せる）"""
        response = self.client.get(self._entry_url("z" * 32))

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(SESSION_MEETING_KEY, self.client.session)

    def test_revoked_token_returns_404(self):
        """失効済みトークンは404"""
        self.access.revoke()

        response = self.client.get(self._entry_url(self.raw_token))

        self.assertEqual(response.status_code, 404)

    def test_expired_token_returns_404(self):
        """期限切れトークンは404"""
        self.access.expires_at = timezone.now() - timedelta(seconds=1)
        self.access.save(update_fields=["expires_at"])

        response = self.client.get(self._entry_url(self.raw_token))

        self.assertEqual(response.status_code, 404)


@override_settings(LOGIN_LOCK_THRESHOLD=3, LOGIN_LOCK_SECONDS=60, MEETING_REVOKE_THRESHOLD=5)
class MeetingLoginTest(TestCase):
    """商談用アクセスのパスワード入力のテスト"""

    def setUp(self):
        self.user = _make_user(password="meeting-pass-1234")
        self.access, self.raw_token = _issue_access(self.user)
        self.url = reverse("guest:login")

    def _land(self):
        """トークンURLを踏んでセッションを作る"""
        self.client.get(reverse("guest:entry", args=[self.raw_token]))

    def test_requires_session_from_token(self):
        """トークンを踏んでいなければ404"""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)

    def test_shows_password_form_after_landing(self):
        """着地後はパスワード入力画面が出る"""
        self._land()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/meeting_login.html")
        self.assertContains(response, self.access.label)

    def test_correct_password_logs_in(self):
        """正しいパスワードでログインし /home/ へ"""
        self._land()

        response = self.client.post(self.url, {"password": "meeting-pass-1234"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/home/")
        self.assertIn("_auth_user_id", self.client.session)

    def test_wrong_password_does_not_log_in(self):
        """誤ったパスワードではログインしない"""
        self._land()

        response = self.client.post(self.url, {"password": "wrong"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "パスワードが正しくありません")

    def test_failures_are_counted_per_access(self):
        """失敗はトークン単位で数えられる"""
        self._land()
        self.client.post(self.url, {"password": "wrong"})

        lock = LoginLockout.objects.get(key=self.access.lock_key)
        self.assertEqual(lock.fail_count, 1)

    def test_locked_after_threshold(self):
        """連続失敗が閾値に達するとロックされ、正しいパスワードも通らない"""
        self._land()
        for _ in range(3):
            self.client.post(self.url, {"password": "wrong"})

        response = self.client.post(self.url, {"password": "meeting-pass-1234"})

        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "制限されています")

    def test_revoked_after_total_threshold(self):
        """累計失敗が閾値に達するとトークンが失効する"""
        self._land()
        for _ in range(4):
            self.client.post(self.url, {"password": "wrong"})
            # ロックを都度解除して累計だけを進める
            LoginLockout.objects.filter(key=self.access.lock_key).update(locked_until=None)

        response = self.client.post(self.url, {"password": "wrong"})

        self.access.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertIsNotNone(self.access.revoked_at)
        self.assertEqual(self.access.revoked_reason, MeetingAccess.REVOKE_LOCKOUT)

    def test_success_updates_last_accessed_at(self):
        """成功時に最終アクセスが更新される"""
        self._land()

        self.client.post(self.url, {"password": "meeting-pass-1234"})

        self.access.refresh_from_db()
        self.assertIsNotNone(self.access.last_accessed_at)

    def test_login_history_records_meeting_access(self):
        """ログイン履歴にどの商談用アクセス経由かが残る"""
        self._land()

        self.client.post(self.url, {"password": "meeting-pass-1234"})

        history = LoginHistory.objects.latest("id")
        self.assertEqual(history.meeting_access_id, self.access.id)

    def test_session_key_is_consumed_after_login(self):
        """ログイン後はセッションからトークン情報が消える"""
        self._land()

        self.client.post(self.url, {"password": "meeting-pass-1234"})

        self.assertNotIn(SESSION_MEETING_KEY, self.client.session)

    def test_id_password_login_has_no_meeting_access(self):
        """通常のID/PWログインの履歴は商談用アクセスに紐づかない"""
        self.client.post(
            reverse("accounts:login"),
            {"username": self.user.username, "password": "meeting-pass-1234"},
        )

        history = LoginHistory.objects.latest("id")
        self.assertIsNone(history.meeting_access_id)
