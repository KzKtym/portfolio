"""
app/common のテスト

実行: python manage.py test app.common --settings=config.settings_test

app/common は Django アプリではない（INSTALLED_APPS 未登録）ため、アプリラベルでは
指定できない。ドット付きモジュールパスで指定する。
"""
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase

from app.common.config import get_app_config_path, load_app_config, resolve_secret
from app.common.decorators import no_cache_no_index
from app.common.permissions import is_superuser


class _FakeUser:
    def __init__(self, is_superuser):
        self.is_superuser = is_superuser


# ══════════════════════════════════════════════
# decorators
# ══════════════════════════════════════════════

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


# ══════════════════════════════════════════════
# permissions
# ══════════════════════════════════════════════

class IsSuperuserTest(SimpleTestCase):
    """is_superuser のテスト"""

    def test_superuser_is_true(self):
        self.assertTrue(is_superuser(_FakeUser(is_superuser=True)))

    def test_normal_user_is_false(self):
        self.assertFalse(is_superuser(_FakeUser(is_superuser=False)))


# ══════════════════════════════════════════════
# config
# ══════════════════════════════════════════════

class GetAppConfigPathTest(SimpleTestCase):
    """get_app_config_path のテスト"""

    def test_points_into_the_app_directory(self):
        """アプリのディレクトリ直下の config.json を指す"""
        path = get_app_config_path("download")

        self.assertEqual(path.name, "config.json")
        self.assertEqual(path.parent.name, "download")

    def test_resolves_without_depending_on_base_dir(self):
        """settings.BASE_DIR ではなくアプリレジストリから解決される"""
        with self.settings(BASE_DIR="/nowhere"):
            path = get_app_config_path("download")

        self.assertTrue(path.exists())

    def test_unknown_label_raises(self):
        """未登録のアプリラベルは LookupError"""
        with self.assertRaises(LookupError):
            get_app_config_path("no_such_app")


class LoadAppConfigTest(SimpleTestCase):
    """load_app_config のテスト"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmpdir, True)

    def _patch_path(self, path):
        return mock.patch("app.common.config.get_app_config_path", return_value=path)

    def test_reads_json_content(self):
        """JSON の内容がそのまま dict で返る"""
        path = Path(self.tmpdir) / "config.json"
        path.write_text(json.dumps({"a": 1}), encoding="utf-8")

        with self._patch_path(path):
            self.assertEqual(load_app_config("download"), {"a": 1})

    def test_reads_utf8_content(self):
        """UTF-8 の日本語が化けない"""
        path = Path(self.tmpdir) / "config.json"
        path.write_text(json.dumps({"名前": "値"}, ensure_ascii=False), encoding="utf-8")

        with self._patch_path(path):
            self.assertEqual(load_app_config("download"), {"名前": "値"})

    def test_missing_file_raises(self):
        """ファイルが無ければ FileNotFoundError（既定値で握りつぶさない）"""
        with self._patch_path(Path(self.tmpdir) / "not-exists.json"):
            with self.assertRaises(FileNotFoundError):
                load_app_config("download")

    def test_broken_json_raises(self):
        """壊れた JSON は JSONDecodeError"""
        path = Path(self.tmpdir) / "config.json"
        path.write_text("{ not json", encoding="utf-8")

        with self._patch_path(path):
            with self.assertRaises(json.JSONDecodeError):
                load_app_config("download")


# ══════════════════════════════════════════════
# LoginRequiredMiddleware（settings.py で有効化）
# ══════════════════════════════════════════════

class LoginRequiredByDefaultTest(TestCase):
    """既定でログイン必須になっていること。

    アプリごとに login_required を付けて回る方式は付け漏れが起きる。実際に
    rag_tr_tool と skill_sheet が未認証で全公開されていた。
    ここでは「既定が閉じていること」と「開けたURLの一覧が意図どおりか」を押さえる。
    """

    def assertRedirectsToLogin(self, response, msg=None):
        self.assertIn(response.status_code, (301, 302), msg=msg)
        self.assertIn('/accounts/login/', response.headers.get('Location', ''), msg=msg)

    def test_app_screens_require_login(self):
        """各アプリの画面は未ログインだとログインへ誘導される"""
        for url in ('/home/', '/rag/projects/', '/skill_sheet/',
                    '/shift/', '/download/manage/', '/test/'):
            with self.subTest(url=url):
                self.assertRedirectsToLogin(self.client.get(url), msg=url)

    def test_mutating_endpoints_require_login(self):
        """更新系も同様（GETだけ塞いでも意味がない）"""
        for url in ('/rag/delete/', '/rag/update-name/1/'):
            with self.subTest(url=url):
                self.assertRedirectsToLogin(self.client.post(url), msg=url)

    def test_landing_page_is_open(self):
        """ランディングページだけは誰でも見える"""
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_login_page_is_open(self):
        self.assertEqual(self.client.get('/accounts/login/').status_code, 200)

    def test_password_authenticated_apis_are_open(self):
        """api_password で守るAPIはセッション認証の対象外。

        応答コードは環境変数の設定状況で変わる（未設定なら500、設定済みなら
        パスワード不一致で401）。ここで確かめたいのは「ログイン画面へ飛ばされない」
        ことなので、リダイレクトでないことだけを見る。
        """
        for url in ('/download/api/token/', '/skill_sheet/api/cells/'):
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertNotIn(response.status_code, (301, 302), msg=url)

    def test_open_url_set_is_exactly_as_intended(self):
        """@login_not_required を付けたURLの一覧を固定する。

        新しく開けたURLがあれば、この表明が落ちて気付ける。
        """
        from django.urls import get_resolver
        from django.urls.resolvers import URLPattern, URLResolver

        found = []

        def walk(patterns, prefix=''):
            for p in patterns:
                if isinstance(p, URLResolver):
                    walk(p.url_patterns, prefix + str(p.pattern))
                elif isinstance(p, URLPattern):
                    if getattr(p.callback, 'login_required', True) is False:
                        found.append(prefix + str(p.pattern))

        walk(get_resolver().url_patterns)

        self.assertEqual(sorted(found), sorted([
            '',                                  # ランディング
            'accounts/login/',
            'accounts/password_reset/',          # 以下4件は Django 標準が開けている
            'accounts/password_reset/done/',
            'accounts/reset/<uidb64>/<token>/',
            'accounts/reset/done/',
            'admin/login/',                      # Django admin 標準
            'download/<str:token>/',             # 顧客に渡すダウンロードURL
            'download/api/token/',               # api_password 認証
            'download/api/upload/',              # api_password 認証
            'guest/',                            # 商談用アクセス（パスワード入力）
            'guest/<str:token>/',                # 商談用アクセス（着地）
            'skill_sheet/api/bindings/',         # api_password 認証
            'skill_sheet/api/cells/',            # api_password 認証
        ]))


class ResolveSecretTest(SimpleTestCase):
    """resolve_secret の 'env:' 解決"""

    def test_plain_value_passes_through(self):
        """'env:' で始まらない値はそのまま返る"""
        self.assertEqual(resolve_secret("plain-value"), "plain-value")

    def test_reads_from_exported_environment(self):
        """export された環境変数を読む"""
        with mock.patch.dict(os.environ, {"COMMON_TEST_PW": "from-export"}):
            self.assertEqual(resolve_secret("env:COMMON_TEST_PW"), "from-export")

    def test_undefined_name_returns_empty_string(self):
        """未定義の環境変数は空文字（呼び出し側が未設定として弾ける）"""
        self.assertEqual(resolve_secret("env:COMMON_NOT_DEFINED_ANYWHERE"), "")

    def test_non_string_passes_through(self):
        """文字列以外はそのまま返る"""
        self.assertIsNone(resolve_secret(None))
        self.assertEqual(resolve_secret(30), 30)
