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
from django.test import RequestFactory, SimpleTestCase

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
