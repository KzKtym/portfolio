"""テスト用の共通土台。

LoginRequiredMiddleware（settings.py）により、@login_not_required を付けていない
ビューはすべてログインが必要になった。画面・APIを叩くテストはログイン済みの
クライアントを前提とするため、その用意をここに集約する。

「未ログインだと弾かれること」自体の検証は app/common/tests.py にある
（各アプリで繰り返さない）。
"""
from django.contrib.auth.models import User
from django.test import TestCase

TEST_USERNAME = 'testclient'
TEST_PASSWORD = 'test-pass-1234'


class LoggedInTestCase(TestCase):
    """ログイン済みの self.client を持つ TestCase。

    setUp より前に走る _pre_setup でログインするため、各テストクラスの setUp を
    書き換えずに済む（super().setUp() の呼び忘れで壊れない）。
    ログインユーザーは self.test_user で参照できる。
    """

    def _pre_setup(self):
        super()._pre_setup()
        self.test_user = User.objects.create_user(
            username=TEST_USERNAME, password=TEST_PASSWORD
        )
        self.client.force_login(self.test_user)
