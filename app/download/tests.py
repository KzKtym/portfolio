import os
import shutil
import string
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import DownloadToken, DownloadUser, generate_token, upload_to_download
from .utils import get_draft_template_path, load_config, render_draft_text, resolve_secret
from .views import (
    _build_absolute_url,
    _calc_expiration,
    _get_client_ip,
    _upload_limit_title,
)


# ──────────────────────────────────────────────
# 共通ヘルパー
# ──────────────────────────────────────────────

def _make_user(username="testuser", password="test-pass-1234"):
    return User.objects.create_user(username=username, password=password)


def _make_superuser(username="admin", password="admin-pass-1234"):
    return User.objects.create_superuser(username=username, password=password)


def _make_token(issuer=None, upload_deadline=None, download_expire_date=None, **kwargs):
    now = timezone.now()
    return DownloadToken.objects.create(
        issuer=issuer,
        upload_deadline=upload_deadline or (now + timedelta(minutes=30)),
        download_expire_date=download_expire_date or (now.date() + timedelta(days=10)),
        **kwargs,
    )


def _make_download_user(owner=None, user_id="dluser", password="dl-pass-1234", **kwargs):
    return DownloadUser.objects.create(
        owner=owner, user_id=user_id, password=make_password(password), **kwargs
    )


def _attach_file(token_obj, filename="sample.zip", content=b"dummy-content"):
    """トークンにアップロード済みファイルを紐づける"""
    token_obj.uploaded_file.save(filename, ContentFile(content), save=False)
    token_obj.uploaded_at = timezone.now()
    token_obj.save()
    return token_obj


def _temp_media(testcase):
    """MEDIA_ROOT を一時ディレクトリへ差し替える（テスト終了時に削除）"""
    tmpdir = tempfile.mkdtemp()
    testcase.addCleanup(shutil.rmtree, tmpdir, True)
    patcher = override_settings(MEDIA_ROOT=tmpdir)
    patcher.enable()
    testcase.addCleanup(patcher.disable)
    return tmpdir


def _temp_base_dir(testcase):
    """BASE_DIR を一時ディレクトリへ差し替える（案内文テンプレート用）"""
    tmpdir = tempfile.mkdtemp()
    testcase.addCleanup(shutil.rmtree, tmpdir, True)
    patcher = override_settings(BASE_DIR=tmpdir)
    patcher.enable()
    testcase.addCleanup(patcher.disable)
    return tmpdir


def _write_draft_template(base_dir, upload_type, text):
    """一時 BASE_DIR 配下に data/download/<upload_type>.txt を書き出す"""
    path = Path(base_dir) / "data" / "download" / f"{upload_type}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


API_PASSWORD = "test-download-api-pass"


def _api_password():
    """API テストが送る api_password。

    config.json は 'env:DOWNLOAD_API_PASSWORD' を持つだけなので、ビューが
    resolve_secret で引く先の環境変数を各テストで用意する（_use_api_password）。
    """
    return API_PASSWORD


def _use_api_password(testcase):
    """DOWNLOAD_API_PASSWORD をテストの間だけ環境変数に置く"""
    patcher = mock.patch.dict(os.environ, {"DOWNLOAD_API_PASSWORD": API_PASSWORD})
    patcher.start()
    testcase.addCleanup(patcher.stop)


# ═══════════════════════════════════════════════════════════════
# URL
# ═══════════════════════════════════════════════════════════════

class DownloadUrlResolveTest(SimpleTestCase):
    """download のURL解決をテスト"""

    def test_reverse_api(self):
        """API系のURLが解決される"""
        self.assertEqual(reverse("download:api_issue_token"), "/download/api/token/")
        self.assertEqual(reverse("download:api_upload"), "/download/api/upload/")

    def test_reverse_manage(self):
        """管理画面系のURLが解決される"""
        self.assertEqual(reverse("download:manage"), "/download/manage/")
        self.assertEqual(reverse("download:manage_issue_token"), "/download/manage/issue/")

    def test_reverse_download(self):
        """ダウンロード実行画面のURLが解決される"""
        self.assertEqual(reverse("download:download", kwargs={"token": "abc"}), "/download/abc/")

    def test_reverse_draft_and_test_download(self):
        """下書き・テストダウンロードのURLが解決される"""
        self.assertEqual(
            reverse("download:draft", kwargs={"token": "abc"}), "/download/manage/draft/abc/"
        )
        self.assertEqual(
            reverse("download:test_download", kwargs={"token": "abc"}),
            "/download/manage/test/abc/",
        )


# ═══════════════════════════════════════════════════════════════
# モデル
# ═══════════════════════════════════════════════════════════════

class GenerateTokenTest(SimpleTestCase):
    """generate_token のテスト"""

    def test_length_is_32(self):
        """32桁のトークンを生成する"""
        self.assertEqual(len(generate_token()), 32)

    def test_uses_lowercase_and_digits_only(self):
        """英小文字と数字のみで構成される"""
        allowed = set(string.ascii_lowercase + string.digits)

        self.assertTrue(set(generate_token()) <= allowed)

    def test_tokens_are_unique(self):
        """生成のたびに異なる値になる"""
        self.assertNotEqual(generate_token(), generate_token())


class UploadToDownloadTest(SimpleTestCase):
    """upload_to_download のテスト"""

    def test_returns_download_dir_path(self):
        """download/ 配下のパスを返す"""
        self.assertEqual(upload_to_download(None, "a.zip"), os.path.join("download", "a.zip"))


class DownloadTokenModelTest(TestCase):
    """DownloadToken モデルのテスト"""

    def setUp(self):
        _temp_media(self)

    # ──────────────────────────────────────────────
    # 基本
    # ──────────────────────────────────────────────

    def test_str_returns_token(self):
        """__str__ はトークン文字列を返す"""
        token_obj = _make_token()

        self.assertEqual(str(token_obj), token_obj.token)

    def test_token_is_auto_generated(self):
        """token は未指定なら自動生成される"""
        token_obj = _make_token()

        self.assertEqual(len(token_obj.token), 32)

    def test_defaults(self):
        """is_deleted のデフォルトは False、アップロード情報は未設定"""
        token_obj = _make_token()

        self.assertFalse(token_obj.is_deleted)
        self.assertIsNone(token_obj.title)
        self.assertIsNone(token_obj.uploaded_at)
        self.assertIsNone(token_obj.downloaded_at)

    def test_ordering_by_issued_at_desc(self):
        """ordering は発行日時の降順"""
        first = _make_token()
        second = _make_token()

        self.assertEqual(list(DownloadToken.objects.all()), [second, first])

    def test_issuer_set_null_on_user_delete(self):
        """発行者ユーザーが削除されても issuer は NULL になりトークンは残る"""
        user = _make_user()
        token_obj = _make_token(issuer=user)

        user.delete()
        token_obj.refresh_from_db()

        self.assertIsNone(token_obj.issuer)

    # ──────────────────────────────────────────────
    # is_upload_expired
    # ──────────────────────────────────────────────

    def test_upload_not_expired(self):
        """アップロード期限内なら False"""
        token_obj = _make_token(upload_deadline=timezone.now() + timedelta(minutes=10))

        self.assertFalse(token_obj.is_upload_expired)

    def test_upload_expired(self):
        """アップロード期限を過ぎていれば True"""
        token_obj = _make_token(upload_deadline=timezone.now() - timedelta(minutes=1))

        self.assertTrue(token_obj.is_upload_expired)

    # ──────────────────────────────────────────────
    # is_download_expired
    # ──────────────────────────────────────────────

    def test_download_not_expired(self):
        """ダウンロード期限内なら False"""
        token_obj = _make_token(download_expire_date=timezone.now().date() + timedelta(days=1))

        self.assertFalse(token_obj.is_download_expired)

    def test_download_expired(self):
        """ダウンロード期限を過ぎていれば True"""
        token_obj = _make_token(download_expire_date=timezone.now().date() - timedelta(days=1))

        self.assertTrue(token_obj.is_download_expired)

    def test_download_expire_on_same_day_is_not_expired(self):
        """期限当日は期限切れではない（境界値）"""
        token_obj = _make_token(download_expire_date=timezone.now().date())

        self.assertFalse(token_obj.is_download_expired)

    # ──────────────────────────────────────────────
    # is_uploaded
    # ──────────────────────────────────────────────

    def test_is_uploaded_false_without_file(self):
        """ファイル未設定なら False"""
        self.assertFalse(_make_token().is_uploaded)

    def test_is_uploaded_true_with_file(self):
        """ファイルがあれば True"""
        token_obj = _attach_file(_make_token())

        self.assertTrue(token_obj.is_uploaded)


class DownloadUserModelTest(TestCase):
    """DownloadUser モデルのテスト"""

    def test_str_returns_user_id(self):
        """__str__ は user_id を返す"""
        self.assertEqual(str(_make_download_user(user_id="taro")), "taro")

    def test_user_id_is_unique(self):
        """user_id は一意"""
        from django.db import IntegrityError

        _make_download_user(user_id="taro")

        with self.assertRaises(IntegrityError):
            _make_download_user(user_id="taro")

    def test_optional_fields_default_to_none(self):
        """user_name / comment は未設定なら None"""
        user = _make_download_user()

        self.assertIsNone(user.user_name)
        self.assertIsNone(user.comment)

    def test_owner_set_null_on_user_delete(self):
        """登録ユーザーが削除されても owner は NULL になりレコードは残る"""
        user = _make_user()
        dl_user = _make_download_user(owner=user)

        user.delete()
        dl_user.refresh_from_db()

        self.assertIsNone(dl_user.owner)


# ═══════════════════════════════════════════════════════════════
# utils.py
# ═══════════════════════════════════════════════════════════════

class LoadConfigTest(SimpleTestCase):
    """load_config のテスト"""

    def test_loads_bundled_config(self):
        """同梱の config.json が読み込まれる"""
        config = load_config()

        for key in (
            "api_password",
            "upload_limit_minutes",
            "download_expire_days",
            "list_default_days",
        ):
            self.assertIn(key, config, msg=f"config に {key} がない")

    def test_values_are_int(self):
        """期限系の設定値は整数"""
        config = load_config()

        self.assertIsInstance(config["upload_limit_minutes"], int)
        self.assertIsInstance(config["download_expire_days"], int)

    def test_api_password_is_not_hardcoded(self):
        """api_password は環境変数参照であって平文ではない

        config.json は git 追跡下にあるため、直書きするとリポジトリに秘密が残る。
        """
        self.assertTrue(load_config()["api_password"].startswith("env:"))


class DownloadResolveSecretTest(SimpleTestCase):
    """api_password の 'env:' 解決（download 経路）"""

    def test_resolves_configured_password(self):
        """config.json の env: 参照が環境変数の値に解決される"""
        with mock.patch.dict(os.environ, {"DOWNLOAD_API_PASSWORD": "from-export"}):
            self.assertEqual(resolve_secret(load_config()["api_password"]), "from-export")

    def test_undefined_resolves_to_empty(self):
        """環境変数が未設定なら空文字（認証は500で弾かれる）"""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_secret("env:DOWNLOAD_NOT_DEFINED"), "")


class GetDraftTemplatePathTest(SimpleTestCase):
    """get_draft_template_path のテスト"""

    def test_builds_data_download_path(self):
        """data/download/<タイプ>.txt のパスを返す"""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, True)

        with override_settings(BASE_DIR=tmpdir):
            path = get_draft_template_path("normal")

        self.assertEqual(path, os.path.join(tmpdir, "data", "download", "normal.txt"))


class RenderDraftTextTest(SimpleTestCase):
    """render_draft_text のテスト"""

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_replaces_placeholder(self):
        """[key] が context の値で置換される"""
        result = render_draft_text("こんにちは [user_name] 様", {"user_name": "山田"})

        self.assertEqual(result, "こんにちは 山田 様")

    def test_replaces_multiple_placeholders(self):
        """複数のプレースホルダを置換できる"""
        result = render_draft_text(
            "[title] / [download_url]", {"title": "資料", "download_url": "http://x/"}
        )

        self.assertEqual(result, "資料 / http://x/")

    def test_same_placeholder_replaced_everywhere(self):
        """同じプレースホルダは全て置換される"""
        result = render_draft_text("[a]-[a]", {"a": "X"})

        self.assertEqual(result, "X-X")

    def test_non_string_value_is_stringified(self):
        """文字列以外の値は str 化される"""
        result = render_draft_text("期限: [download_expire_date]", {"download_expire_date": 20260731})

        self.assertEqual(result, "期限: 20260731")

    # ──────────────────────────────────────────────
    # 境界値
    # ──────────────────────────────────────────────

    def test_unknown_key_is_kept(self):
        """context に無いキーはそのまま残る"""
        result = render_draft_text("[unknown] です", {"user_name": "山田"})

        self.assertEqual(result, "[unknown] です")

    def test_none_value_is_kept(self):
        """値が None ならプレースホルダはそのまま残る"""
        result = render_draft_text("[a] です", {"a": None})

        self.assertEqual(result, "[a] です")

    def test_non_word_bracket_is_not_replaced(self):
        """英数字以外を含む括弧は置換対象外"""
        result = render_draft_text("[a-b] です", {"a-b": "X"})

        self.assertEqual(result, "[a-b] です")


# ═══════════════════════════════════════════════════════════════
# views.py: 内部ヘルパー
# ═══════════════════════════════════════════════════════════════

class CalcExpirationTest(SimpleTestCase):
    """_calc_expiration のテスト"""

    def test_upload_deadline_adds_minutes(self):
        """アップロード期限は現在時刻 + upload_limit_minutes"""
        now = timezone.now()

        upload_deadline, _ = _calc_expiration(now, {"upload_limit_minutes": 30})

        self.assertEqual(upload_deadline, now + timedelta(minutes=30))

    def test_download_expire_date_from_next_day(self):
        """ダウンロード期限は翌日 + download_expire_days"""
        now = timezone.now()

        _, expire_date = _calc_expiration(now, {"download_expire_days": 10})

        self.assertEqual(expire_date, (now + timedelta(days=1)).date() + timedelta(days=10))

    def test_defaults_when_config_is_empty(self):
        """設定が無ければ既定値（30分 / 7日）を使う"""
        now = timezone.now()

        upload_deadline, expire_date = _calc_expiration(now, {})

        self.assertEqual(upload_deadline, now + timedelta(minutes=30))
        self.assertEqual(expire_date, (now + timedelta(days=1)).date() + timedelta(days=7))


class UploadLimitTitleTest(SimpleTestCase):
    """_upload_limit_title のテスト"""

    def test_format(self):
        """'(Up Limit hh:mm:ss)' 形式で返す"""
        deadline = timezone.localtime(timezone.now()).replace(hour=13, minute=45, second=30)

        self.assertEqual(_upload_limit_title(deadline), "(Up Limit 13:45:30)")


class GetClientIpTest(SimpleTestCase):
    """_get_client_ip のテスト"""

    def setUp(self):
        self.factory = RequestFactory()

    def test_uses_remote_addr_by_default(self):
        """X-Forwarded-For が無ければ REMOTE_ADDR を使う"""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")

        self.assertEqual(_get_client_ip(request), "10.0.0.1")

    def test_x_forwarded_for_takes_priority(self):
        """X-Forwarded-For があれば先頭のIPを優先し空白を除去する"""
        request = self.factory.get(
            "/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR=" 203.0.113.5 , 10.0.0.2"
        )

        self.assertEqual(_get_client_ip(request), "203.0.113.5")

    def test_returns_empty_when_nothing_set(self):
        """どちらも無い場合は空文字"""
        request = self.factory.get("/")
        request.META.pop("REMOTE_ADDR", None)

        self.assertEqual(_get_client_ip(request), "")


class BuildAbsoluteUrlTest(SimpleTestCase):
    """_build_absolute_url のテスト"""

    def test_builds_absolute_uri(self):
        """絶対URLを組み立てる"""
        request = RequestFactory().get("/", HTTP_HOST="testserver")

        url = _build_absolute_url(request, "download:download", token="abc")

        self.assertEqual(url, "http://testserver/download/abc/")


# ═══════════════════════════════════════════════════════════════
# API: トークン発行
# ═══════════════════════════════════════════════════════════════

class ApiIssueTokenTest(TestCase):
    """api_issue_token のテスト"""

    def setUp(self):
        _use_api_password(self)
        self.url = reverse("download:api_issue_token")

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_creates_token(self):
        """トークンが発行される（201）"""
        response = self.client.post(self.url, {"api_password": _api_password()})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], 0)
        self.assertEqual(DownloadToken.objects.count(), 1)

    def test_response_contains_urls(self):
        """レスポンスにダウンロードURL・下書きURLが含まれる"""
        response = self.client.post(self.url, {"api_password": _api_password()})

        data = response.json()
        self.assertIn(data["token"], data["download_url"])
        self.assertIn(data["token"], data["draft_url"])

    def test_title_is_upload_limit(self):
        """タイトルの初期値は '(Up Limit hh:mm:ss)'"""
        self.client.post(self.url, {"api_password": _api_password()})

        token_obj = DownloadToken.objects.first()
        self.assertTrue(token_obj.title.startswith("(Up Limit "))

    def test_expiration_follows_config(self):
        """期限が config.json の設定に従う"""
        config = load_config()

        self.client.post(self.url, {"api_password": _api_password()})

        token_obj = DownloadToken.objects.first()
        expected = (token_obj.issued_at + timedelta(days=1)).date() + timedelta(
            days=config["download_expire_days"]
        )
        self.assertEqual(token_obj.download_expire_date, expected)

    def test_issuer_is_null_without_auth_user(self):
        """auth_user 未指定なら issuer は NULL"""
        self.client.post(self.url, {"api_password": _api_password()})

        self.assertIsNone(DownloadToken.objects.first().issuer)

    def test_issuer_from_auth_user(self):
        """auth_user 指定で発行者が記録される"""
        user = _make_user()

        self.client.post(
            self.url, {"api_password": _api_password(), "auth_user": user.username}
        )

        self.assertEqual(DownloadToken.objects.first().issuer, user)

    # ──────────────────────────────────────────────
    # 認証・エラー系
    # ──────────────────────────────────────────────

    def test_missing_api_password_returns_401(self):
        """api_password 未指定は401"""
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], 1)

    def test_wrong_api_password_returns_401(self):
        """api_password が誤っていれば401"""
        response = self.client.post(self.url, {"api_password": "wrong"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(DownloadToken.objects.count(), 0)

    def test_unconfigured_api_password_returns_500(self):
        """api_password が設定されていなければ500"""
        with mock.patch("app.download.views.load_config", return_value={"api_password": ""}):
            response = self.client.post(self.url, {"api_password": "x"})

        self.assertEqual(response.status_code, 500)

    def test_unknown_auth_user_returns_400(self):
        """存在しない auth_user は400（code=4）"""
        response = self.client.post(
            self.url, {"api_password": _api_password(), "auth_user": "nobody"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 4)

    def test_inactive_auth_user_returns_400(self):
        """無効化されたユーザーは400（code=4）"""
        user = _make_user()
        user.is_active = False
        user.save()

        response = self.client.post(
            self.url, {"api_password": _api_password(), "auth_user": user.username}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 4)

    def test_get_returns_405(self):
        """GETは405"""
        self.assertEqual(self.client.get(self.url).status_code, 405)


# ═══════════════════════════════════════════════════════════════
# API: アップロード
# ═══════════════════════════════════════════════════════════════

class ApiUploadTest(TestCase):
    """api_upload のテスト"""

    def setUp(self):
        _use_api_password(self)
        _temp_media(self)
        self.url = reverse("download:api_upload")
        self.token_obj = _make_token()

    def _post(self, **extra):
        payload = {"api_password": _api_password(), "token": self.token_obj.token}
        payload.update(extra)
        return self.client.post(self.url, payload)

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_upload_with_file(self):
        """ファイル付きアップロードが成功する（code=0）"""
        upload = ContentFile(b"zip-content", name="report.zip")

        response = self._post(file=upload, title="月次資料", upload_type="normal")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 0)
        self.token_obj.refresh_from_db()
        self.assertTrue(self.token_obj.is_uploaded)
        self.assertEqual(self.token_obj.title, "月次資料")

    def test_upload_without_file_creates_zip(self):
        """ファイル省略時は <token>.zip が作成される"""
        response = self._post(title="資料")

        self.assertEqual(response.json()["code"], 0)
        self.token_obj.refresh_from_db()
        self.assertIn(f"{self.token_obj.token}.zip", self.token_obj.uploaded_file.name)

    def test_user_id_becomes_target_user(self):
        """user_id が target_user に格納される"""
        self._post(user_id="taro")

        self.token_obj.refresh_from_db()
        self.assertEqual(self.token_obj.target_user, "taro")

    def test_target_user_alias(self):
        """target_user の別名でも指定できる"""
        self._post(target_user="jiro")

        self.token_obj.refresh_from_db()
        self.assertEqual(self.token_obj.target_user, "jiro")

    def test_user_id_takes_priority_over_target_user(self):
        """user_id と target_user が両方あれば user_id が優先される"""
        self._post(user_id="taro", target_user="jiro")

        self.token_obj.refresh_from_db()
        self.assertEqual(self.token_obj.target_user, "taro")

    def test_uploaded_at_is_set(self):
        """アップロード日時が記録される"""
        self._post()

        self.token_obj.refresh_from_db()
        self.assertIsNotNone(self.token_obj.uploaded_at)

    def test_response_contains_urls(self):
        """レスポンスにダウンロードURL・下書きURLが含まれる"""
        response = self._post(upload_type="normal")

        data = response.json()
        self.assertIn(self.token_obj.token, data["download_url"])
        self.assertIn(self.token_obj.token, data["draft_url"])

    # ──────────────────────────────────────────────
    # 業務エラー（code）
    # ──────────────────────────────────────────────

    def test_already_uploaded_returns_code_3(self):
        """既にアップロード済みなら code=3（200）"""
        _attach_file(self.token_obj)

        response = self._post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["code"], 3)

    def test_expired_upload_returns_code_2(self):
        """アップロード期限切れは code=2（400）"""
        self.token_obj.upload_deadline = timezone.now() - timedelta(minutes=1)
        self.token_obj.save()

        response = self._post()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 2)

    def test_save_error_returns_code_1(self):
        """保存に失敗したら code=1（500）"""
        with mock.patch(
            "django.db.models.fields.files.FieldFile.save", side_effect=OSError("disk full")
        ):
            response = self._post()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], 1)

    # ──────────────────────────────────────────────
    # 認証・エラー系
    # ──────────────────────────────────────────────

    def test_wrong_api_password_returns_401(self):
        """api_password が誤っていれば401"""
        response = self.client.post(
            self.url, {"api_password": "wrong", "token": self.token_obj.token}
        )

        self.assertEqual(response.status_code, 401)

    def test_missing_token_returns_400(self):
        """token 未指定は400"""
        response = self.client.post(self.url, {"api_password": _api_password()})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "token is required")

    def test_unknown_token_returns_404(self):
        """存在しないトークンは404"""
        response = self.client.post(
            self.url, {"api_password": _api_password(), "token": "x" * 32}
        )

        self.assertEqual(response.status_code, 404)

    def test_deleted_token_returns_404(self):
        """論理削除済みのトークンは404"""
        self.token_obj.is_deleted = True
        self.token_obj.save()

        response = self._post()

        self.assertEqual(response.status_code, 404)

    def test_get_returns_405(self):
        """GETは405"""
        self.assertEqual(self.client.get(self.url).status_code, 405)


# ═══════════════════════════════════════════════════════════════
# ビュー: ダウンロード実行画面
# ═══════════════════════════════════════════════════════════════

class DownloadViewTest(TestCase):
    """download_view のテスト"""

    def setUp(self):
        _temp_media(self)
        self.token_obj = _attach_file(_make_token())
        self.url = reverse("download:download", kwargs={"token": self.token_obj.token})
        self.dl_user = _make_download_user(password="dl-pass-1234")

    # ──────────────────────────────────────────────
    # GET
    # ──────────────────────────────────────────────

    def test_get_renders_template(self):
        """GETでダウンロード画面が表示される"""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "download/main.html")

    def test_get_has_no_cache_headers(self):
        """キャッシュ抑制ヘッダーが付与される"""
        response = self.client.get(self.url)

        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_is_expired_false_when_valid(self):
        """期限内かつアップロード済みなら is_expired=False"""
        response = self.client.get(self.url)

        self.assertFalse(response.context["is_expired"])

    def test_is_expired_true_when_not_uploaded(self):
        """未アップロードなら is_expired=True"""
        token_obj = _make_token()

        response = self.client.get(
            reverse("download:download", kwargs={"token": token_obj.token})
        )

        self.assertTrue(response.context["is_expired"])

    def test_is_expired_true_when_download_expired(self):
        """ダウンロード期限切れなら is_expired=True"""
        self.token_obj.download_expire_date = timezone.now().date() - timedelta(days=1)
        self.token_obj.save()

        response = self.client.get(self.url)

        self.assertTrue(response.context["is_expired"])

    def test_unknown_token_returns_404(self):
        """存在しないトークンは404"""
        url = reverse("download:download", kwargs={"token": "x" * 32})

        self.assertEqual(self.client.get(url).status_code, 404)

    def test_deleted_token_returns_404(self):
        """論理削除済みのトークンは404"""
        self.token_obj.is_deleted = True
        self.token_obj.save()

        self.assertEqual(self.client.get(self.url).status_code, 404)

    # ──────────────────────────────────────────────
    # POST（正常系）
    # ──────────────────────────────────────────────

    def test_post_correct_password_returns_file(self):
        """パスワードが一致したらファイルが返る"""
        response = self.client.post(self.url, {"password": "dl-pass-1234"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(b"".join(response.streaming_content), b"dummy-content")

    def test_post_records_downloaded_at_and_ip(self):
        """ダウンロード日時とIPアドレスが記録される"""
        response = self.client.post(
            self.url, {"password": "dl-pass-1234"}, HTTP_X_FORWARDED_FOR="203.0.113.5"
        )
        response.close()

        self.token_obj.refresh_from_db()
        self.assertIsNotNone(self.token_obj.downloaded_at)
        self.assertEqual(self.token_obj.download_user, "203.0.113.5")

    def test_post_matches_any_registered_user(self):
        """登録済みのいずれかのユーザーのパスワードと一致すればよい"""
        _make_download_user(user_id="other", password="other-pass-9999")

        response = self.client.post(self.url, {"password": "other-pass-9999"})

        self.assertEqual(response.status_code, 200)
        response.close()

    # ──────────────────────────────────────────────
    # POST（エラー系）
    # ──────────────────────────────────────────────

    def test_post_wrong_password_shows_error(self):
        """パスワードが誤っていればエラーメッセージを表示する"""
        response = self.client.post(self.url, {"password": "wrong"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "download/main.html")
        self.assertEqual(response.context["error"], "パスワードが正しくありません。")

    def test_post_wrong_password_does_not_record(self):
        """パスワード不一致ならダウンロード日時は記録されない"""
        self.client.post(self.url, {"password": "wrong"})

        self.token_obj.refresh_from_db()
        self.assertIsNone(self.token_obj.downloaded_at)

    def test_post_expired_shows_error(self):
        """期限切れならエラーメッセージを表示する"""
        self.token_obj.download_expire_date = timezone.now().date() - timedelta(days=1)
        self.token_obj.save()

        response = self.client.post(self.url, {"password": "dl-pass-1234"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["error"], "このダウンロードは期限切れ、または無効です。"
        )

    def test_post_no_registered_user_shows_error(self):
        """許可ユーザーが1件も無ければエラーになる"""
        DownloadUser.objects.all().delete()

        response = self.client.post(self.url, {"password": "dl-pass-1234"})

        self.assertEqual(response.context["error"], "パスワードが正しくありません。")


# ═══════════════════════════════════════════════════════════════
# ビュー: テストダウンロード
# ═══════════════════════════════════════════════════════════════

class TestDownloadViewTest(TestCase):
    """test_download_view のテスト"""

    def setUp(self):
        _temp_media(self)
        self.user = _make_user()
        self.token_obj = _attach_file(_make_token(issuer=self.user))
        self.url = reverse("download:test_download", kwargs={"token": self.token_obj.token})

    # ──────────────────────────────────────────────
    # 認証・認可
    # ──────────────────────────────────────────────

    def test_anonymous_redirects_to_login(self):
        """未ログイン時はログインURLへリダイレクト"""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_owner_can_download(self):
        """発行者本人はダウンロードできる"""
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"dummy-content")

    def test_other_user_gets_403(self):
        """他ユーザーは403"""
        self.client.force_login(_make_user("other"))

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_superuser_can_download(self):
        """スーパーユーザーはダウンロードできる"""
        self.client.force_login(_make_superuser())

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        response.close()

    # ──────────────────────────────────────────────
    # 挙動
    # ──────────────────────────────────────────────

    def test_does_not_record_download(self):
        """テストダウンロードでは downloaded_at を記録しない"""
        self.client.force_login(self.user)

        response = self.client.get(self.url)
        response.close()

        self.token_obj.refresh_from_db()
        self.assertIsNone(self.token_obj.downloaded_at)

    def test_has_no_cache_headers(self):
        """キャッシュ抑制ヘッダーが付与される"""
        self.client.force_login(self.user)

        response = self.client.get(self.url)
        response.close()

        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_not_uploaded_returns_404(self):
        """未アップロードなら404"""
        token_obj = _make_token(issuer=self.user)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("download:test_download", kwargs={"token": token_obj.token})
        )

        self.assertEqual(response.status_code, 404)

    def test_deleted_token_returns_404(self):
        """論理削除済みのトークンは404"""
        self.token_obj.is_deleted = True
        self.token_obj.save()
        self.client.force_login(self.user)

        self.assertEqual(self.client.get(self.url).status_code, 404)


# ═══════════════════════════════════════════════════════════════
# ビュー: 案内文の下書き
# ═══════════════════════════════════════════════════════════════

class DraftViewTest(TestCase):
    """draft_view のテスト"""

    def setUp(self):
        _temp_media(self)
        self.base_dir = _temp_base_dir(self)
        self.user = _make_user()
        self.client.force_login(self.user)
        self.token_obj = _attach_file(
            _make_token(issuer=self.user, title="月次資料", upload_type="normal", target_user="taro")
        )
        self.url = reverse("download:draft", kwargs={"token": self.token_obj.token})

    # ──────────────────────────────────────────────
    # 認証・認可
    # ──────────────────────────────────────────────

    def test_anonymous_redirects_to_login(self):
        """未ログイン時はログインURLへリダイレクト"""
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_other_user_gets_403(self):
        """他ユーザーは403"""
        self.client.force_login(_make_user("other"))

        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_superuser_can_access(self):
        """スーパーユーザーはアクセスできる"""
        self.client.force_login(_make_superuser())

        self.assertEqual(self.client.get(self.url).status_code, 200)

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_uses_template(self):
        """download/draft.html が使われる"""
        _write_draft_template(self.base_dir, "normal", "本文")

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "download/draft.html")

    def test_context_keys(self):
        """主要なコンテキストキーが揃っている"""
        _write_draft_template(self.base_dir, "normal", "本文")

        response = self.client.get(self.url)

        for key in ("token_obj", "draft_text", "template_error", "download_url", "test_download_url"):
            self.assertIn(key, response.context, msg=f"context に {key} がない")

    def test_placeholders_are_replaced(self):
        """テンプレートのプレースホルダが置換される"""
        _write_draft_template(
            self.base_dir, "normal", "[user_name] 様\n[title]\n[download_url]\n[download_expire_date]"
        )
        _make_download_user(owner=self.user, user_id="taro", user_name="山田太郎")

        response = self.client.get(self.url)

        draft_text = response.context["draft_text"]
        self.assertIn("山田太郎 様", draft_text)
        self.assertIn("月次資料", draft_text)
        self.assertIn(self.token_obj.token, draft_text)
        self.assertIn(str(self.token_obj.download_expire_date), draft_text)

    def test_user_name_falls_back_to_user_id(self):
        """user_name 未設定なら user_id が使われる"""
        _write_draft_template(self.base_dir, "normal", "[user_name] 様")
        _make_download_user(owner=self.user, user_id="taro", user_name=None)

        response = self.client.get(self.url)

        self.assertIn("taro 様", response.context["draft_text"])

    def test_user_name_falls_back_to_target_user(self):
        """許可ユーザーが未登録なら target_user がそのまま使われる"""
        _write_draft_template(self.base_dir, "normal", "[user_name] 様")

        response = self.client.get(self.url)

        self.assertIn("taro 様", response.context["draft_text"])

    def test_no_template_error_when_ok(self):
        """テンプレートが読めれば template_error は None"""
        _write_draft_template(self.base_dir, "normal", "本文")

        response = self.client.get(self.url)

        self.assertIsNone(response.context["template_error"])

    # ──────────────────────────────────────────────
    # エラー系
    # ──────────────────────────────────────────────

    def test_missing_upload_type_shows_error(self):
        """upload_type 未設定ならエラーメッセージを表示する"""
        token_obj = _make_token(issuer=self.user, upload_type=None)

        response = self.client.get(
            reverse("download:draft", kwargs={"token": token_obj.token})
        )

        self.assertEqual(response.context["draft_text"], "")
        self.assertIn("アップロードタイプが未設定", response.context["template_error"])

    def test_missing_template_file_shows_error(self):
        """テンプレートファイルが無ければエラーメッセージを表示する"""
        response = self.client.get(self.url)

        self.assertEqual(response.context["draft_text"], "")
        self.assertIn("テンプレートファイルが見つかりません", response.context["template_error"])

    def test_deleted_token_returns_404(self):
        """論理削除済みのトークンは404"""
        self.token_obj.is_deleted = True
        self.token_obj.save()

        self.assertEqual(self.client.get(self.url).status_code, 404)


# ═══════════════════════════════════════════════════════════════
# ビュー: 管理画面
# ═══════════════════════════════════════════════════════════════

class ManageViewTest(TestCase):
    """manage_view のテスト"""

    def setUp(self):
        _temp_media(self)
        self.user = _make_user()
        self.client.force_login(self.user)
        self.url = reverse("download:manage")

    # ──────────────────────────────────────────────
    # 認証
    # ──────────────────────────────────────────────

    def test_anonymous_redirects_to_login(self):
        """未ログイン時はログインURLへリダイレクト"""
        self.client.logout()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_uses_template(self):
        """download/manage.html が使われる"""
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "download/manage.html")

    def test_context_keys(self):
        """主要なコンテキストキーが揃っている"""
        response = self.client.get(self.url)

        for key in ("tokens", "users", "mode", "config", "now"):
            self.assertIn(key, response.context, msg=f"context に {key} がない")

    def test_has_no_cache_headers(self):
        """キャッシュ抑制ヘッダーが付与される"""
        response = self.client.get(self.url)

        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    # ──────────────────────────────────────────────
    # 表示モード
    # ──────────────────────────────────────────────

    def test_default_mode_filters_by_days(self):
        """既定モードは直近 list_default_days 日分に絞られる"""
        config = load_config()
        old = _make_token(issuer=self.user)
        DownloadToken.objects.filter(pk=old.pk).update(
            issued_at=timezone.now() - timedelta(days=config["list_default_days"] + 1)
        )
        recent = _make_token(issuer=self.user)

        response = self.client.get(self.url)

        self.assertEqual([t.id for t in response.context["tokens"]], [recent.id])

    def test_all_mode_shows_all_undeleted(self):
        """mode=all なら期間に関わらず未削除のものを全て表示する"""
        config = load_config()
        old = _make_token(issuer=self.user)
        DownloadToken.objects.filter(pk=old.pk).update(
            issued_at=timezone.now() - timedelta(days=config["list_default_days"] + 1)
        )

        response = self.client.get(self.url, {"mode": "all"})

        self.assertIn(old.id, [t.id for t in response.context["tokens"]])

    def test_all_mode_excludes_deleted(self):
        """mode=all では論理削除済みは含まれない"""
        deleted = _make_token(issuer=self.user, is_deleted=True)

        response = self.client.get(self.url, {"mode": "all"})

        self.assertNotIn(deleted.id, [t.id for t in response.context["tokens"]])

    def test_all_deleted_mode_includes_deleted(self):
        """mode=all_deleted なら論理削除済みも含まれる"""
        deleted = _make_token(issuer=self.user, is_deleted=True)

        response = self.client.get(self.url, {"mode": "all_deleted"})

        self.assertIn(deleted.id, [t.id for t in response.context["tokens"]])

    def test_tokens_sorted_by_issued_at_desc(self):
        """トークンは発行日時の降順で並ぶ"""
        first = _make_token(issuer=self.user)
        second = _make_token(issuer=self.user)

        response = self.client.get(self.url)

        self.assertEqual([t.id for t in response.context["tokens"]], [second.id, first.id])

    # ──────────────────────────────────────────────
    # 表示範囲（発行者スコープ）
    # ──────────────────────────────────────────────

    def test_shows_only_own_tokens(self):
        """一般ユーザーは自分が発行したトークンのみ表示される"""
        mine = _make_token(issuer=self.user)
        _make_token(issuer=_make_user("other"))

        response = self.client.get(self.url)

        self.assertEqual([t.id for t in response.context["tokens"]], [mine.id])

    def test_api_issued_token_is_hidden_from_normal_user(self):
        """発行者NULL（API発行）のトークンは一般ユーザーには表示されない"""
        _make_token(issuer=None)

        response = self.client.get(self.url)

        self.assertEqual(len(response.context["tokens"]), 0)

    def test_superuser_sees_all_tokens(self):
        """スーパーユーザーは全件表示される"""
        _make_token(issuer=self.user)
        _make_token(issuer=None)
        self.client.force_login(_make_superuser())

        response = self.client.get(self.url)

        self.assertEqual(len(response.context["tokens"]), 2)

    def test_shows_only_own_users(self):
        """一般ユーザーは自分が登録した許可ユーザーのみ表示される"""
        mine = _make_download_user(owner=self.user, user_id="mine")
        _make_download_user(owner=_make_user("other"), user_id="theirs")

        response = self.client.get(self.url)

        self.assertEqual([u.id for u in response.context["users"]], [mine.id])

    def test_superuser_sees_all_users(self):
        """スーパーユーザーは許可ユーザーを全件表示できる"""
        _make_download_user(owner=self.user, user_id="a")
        _make_download_user(owner=None, user_id="b")
        self.client.force_login(_make_superuser())

        response = self.client.get(self.url)

        self.assertEqual(len(response.context["users"]), 2)


class ManageIssueTokenTest(TestCase):
    """manage_issue_token のテスト"""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.url = reverse("download:manage_issue_token")

    def test_creates_token_with_issuer(self):
        """ログインユーザーを発行者としてトークンが作成される"""
        response = self.client.post(self.url)

        self.assertRedirects(
            response, reverse("download:manage"), fetch_redirect_response=False
        )
        self.assertEqual(DownloadToken.objects.first().issuer, self.user)

    def test_title_is_upload_limit(self):
        """タイトルの初期値は '(Up Limit hh:mm:ss)'"""
        self.client.post(self.url)

        self.assertTrue(DownloadToken.objects.first().title.startswith("(Up Limit "))

    def test_anonymous_redirects_to_login(self):
        """未ログイン時はログインURLへリダイレクト"""
        self.client.logout()

        response = self.client.post(self.url)

        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_get_returns_405(self):
        """GETは405"""
        self.assertEqual(self.client.get(self.url).status_code, 405)


class ManageDeleteTokenTest(TestCase):
    """manage_delete_token のテスト"""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.token_obj = _make_token(issuer=self.user)
        self.url = reverse(
            "download:manage_delete_token", kwargs={"token": self.token_obj.token}
        )

    def test_post_logically_deletes(self):
        """POSTで論理削除される"""
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.token_obj.refresh_from_db()
        self.assertTrue(self.token_obj.is_deleted)

    def test_record_is_not_physically_deleted(self):
        """レコード自体は削除されない"""
        self.client.post(self.url)

        self.assertTrue(DownloadToken.objects.filter(pk=self.token_obj.pk).exists())

    def test_other_user_gets_403(self):
        """他ユーザーは403"""
        self.client.force_login(_make_user("other"))

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.token_obj.refresh_from_db()
        self.assertFalse(self.token_obj.is_deleted)

    def test_superuser_can_delete(self):
        """スーパーユーザーは削除できる"""
        self.client.force_login(_make_superuser())

        self.client.post(self.url)

        self.token_obj.refresh_from_db()
        self.assertTrue(self.token_obj.is_deleted)

    def test_unknown_token_returns_404(self):
        """存在しないトークンは404"""
        url = reverse("download:manage_delete_token", kwargs={"token": "x" * 32})

        self.assertEqual(self.client.post(url).status_code, 404)

    def test_get_returns_405(self):
        """GETは405"""
        self.assertEqual(self.client.get(self.url).status_code, 405)


# ═══════════════════════════════════════════════════════════════
# ビュー: 許可ユーザー管理
# ═══════════════════════════════════════════════════════════════

class ManageUserAddTest(TestCase):
    """manage_user_add のテスト"""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.url = reverse("download:manage_user_add")

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_creates_user(self):
        """許可ユーザーが作成され管理画面へリダイレクト"""
        response = self.client.post(
            self.url, {"user_id": "taro", "user_name": "山田太郎", "password": "pass-1234"}
        )

        self.assertRedirects(
            response, reverse("download:manage"), fetch_redirect_response=False
        )
        self.assertTrue(DownloadUser.objects.filter(user_id="taro").exists())

    def test_password_is_hashed(self):
        """パスワードはハッシュ化して保存される"""
        from django.contrib.auth.hashers import check_password

        self.client.post(self.url, {"user_id": "taro", "password": "pass-1234"})

        dl_user = DownloadUser.objects.get(user_id="taro")
        self.assertNotEqual(dl_user.password, "pass-1234")
        self.assertTrue(check_password("pass-1234", dl_user.password))

    def test_owner_is_request_user(self):
        """登録者はログインユーザーになる"""
        self.client.post(self.url, {"user_id": "taro", "password": "pass-1234"})

        self.assertEqual(DownloadUser.objects.get(user_id="taro").owner, self.user)

    def test_values_are_stripped(self):
        """入力値は前後の空白が除去される"""
        self.client.post(
            self.url, {"user_id": "  taro  ", "user_name": " 山田 ", "password": " pass-1234 "}
        )

        self.assertTrue(DownloadUser.objects.filter(user_id="taro", user_name="山田").exists())

    # ──────────────────────────────────────────────
    # 境界値
    # ──────────────────────────────────────────────

    def test_missing_user_id_creates_nothing(self):
        """user_id が無ければ作成されない（リダイレクトのみ）"""
        response = self.client.post(self.url, {"password": "pass-1234"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(DownloadUser.objects.count(), 0)

    def test_missing_password_creates_nothing(self):
        """password が無ければ作成されない"""
        self.client.post(self.url, {"user_id": "taro"})

        self.assertEqual(DownloadUser.objects.count(), 0)

    def test_get_returns_405(self):
        """GETは405"""
        self.assertEqual(self.client.get(self.url).status_code, 405)


class ManageUserEditTest(TestCase):
    """manage_user_edit のテスト"""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.dl_user = _make_download_user(
            owner=self.user, user_id="taro", user_name="山田", password="old-pass-1234"
        )
        self.url = reverse("download:manage_user_edit", kwargs={"user_id": self.dl_user.id})

    # ──────────────────────────────────────────────
    # 正常系
    # ──────────────────────────────────────────────

    def test_updates_fields(self):
        """user_id / user_name / comment を更新できる"""
        self.client.post(
            self.url, {"user_id": "jiro", "user_name": "鈴木次郎", "comment": "メモ"}
        )

        self.dl_user.refresh_from_db()
        self.assertEqual(self.dl_user.user_id, "jiro")
        self.assertEqual(self.dl_user.user_name, "鈴木次郎")
        self.assertEqual(self.dl_user.comment, "メモ")

    def test_password_is_updated_when_given(self):
        """パスワード指定時はハッシュ化して更新される"""
        from django.contrib.auth.hashers import check_password

        self.client.post(self.url, {"user_id": "taro", "password": "new-pass-9999"})

        self.dl_user.refresh_from_db()
        self.assertTrue(check_password("new-pass-9999", self.dl_user.password))

    def test_password_is_kept_when_blank(self):
        """パスワード未指定なら既存のまま維持される"""
        from django.contrib.auth.hashers import check_password

        self.client.post(self.url, {"user_id": "taro", "password": ""})

        self.dl_user.refresh_from_db()
        self.assertTrue(check_password("old-pass-1234", self.dl_user.password))

    def test_user_id_is_kept_when_blank(self):
        """user_id が空なら既存のまま維持される"""
        self.client.post(self.url, {"user_id": ""})

        self.dl_user.refresh_from_db()
        self.assertEqual(self.dl_user.user_id, "taro")

    # ──────────────────────────────────────────────
    # 認可
    # ──────────────────────────────────────────────

    def test_other_user_gets_403(self):
        """他ユーザーは403"""
        self.client.force_login(_make_user("other"))

        response = self.client.post(self.url, {"user_id": "hacked"})

        self.assertEqual(response.status_code, 403)
        self.dl_user.refresh_from_db()
        self.assertEqual(self.dl_user.user_id, "taro")

    def test_superuser_can_edit(self):
        """スーパーユーザーは編集できる"""
        self.client.force_login(_make_superuser())

        self.client.post(self.url, {"user_id": "jiro"})

        self.dl_user.refresh_from_db()
        self.assertEqual(self.dl_user.user_id, "jiro")

    def test_not_found_returns_404(self):
        """存在しないユーザーは404"""
        url = reverse("download:manage_user_edit", kwargs={"user_id": 99999})

        self.assertEqual(self.client.post(url).status_code, 404)

    def test_get_returns_405(self):
        """GETは405"""
        self.assertEqual(self.client.get(self.url).status_code, 405)


class ManageUserDeleteTest(TestCase):
    """manage_user_delete のテスト"""

    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)
        self.dl_user = _make_download_user(owner=self.user, user_id="taro")
        self.url = reverse("download:manage_user_delete", kwargs={"user_id": self.dl_user.id})

    def test_deletes_user(self):
        """許可ユーザーが物理削除される"""
        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(DownloadUser.objects.filter(pk=self.dl_user.pk).exists())

    def test_other_user_gets_403(self):
        """他ユーザーは403"""
        self.client.force_login(_make_user("other"))

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(DownloadUser.objects.filter(pk=self.dl_user.pk).exists())

    def test_superuser_can_delete(self):
        """スーパーユーザーは削除できる"""
        self.client.force_login(_make_superuser())

        self.client.post(self.url)

        self.assertFalse(DownloadUser.objects.filter(pk=self.dl_user.pk).exists())

    def test_anonymous_redirects_to_login(self):
        """未ログイン時はログインURLへリダイレクト"""
        self.client.logout()

        response = self.client.post(self.url)

        self.assertTrue(response["Location"].startswith("/accounts/login/"))

    def test_get_returns_405(self):
        """GETは405"""
        self.assertEqual(self.client.get(self.url).status_code, 405)
