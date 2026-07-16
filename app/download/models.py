import os
import secrets
import string

from django.conf import settings
from django.db import models
from django.utils import timezone


def generate_token():
    """32桁の英数字トークンを生成する"""
    chars = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(32))


def upload_to_download(instance, filename):
    """./media/download/ 配下に保存するパスを返す"""
    return os.path.join('download', filename)


class DownloadToken(models.Model):
    """ダウンロードサービス用トークン管理"""

    token = models.CharField(max_length=32, unique=True, db_index=True, default=generate_token)

    # 発行情報
    issuer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='issued_download_tokens',
        help_text='管理画面から発行したログインユーザー（APIからの発行時はNULL）',
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    upload_deadline = models.DateTimeField(help_text='アップロード期限（発行日時 + m分）')
    download_expire_date = models.DateField(help_text='ダウンロード有効期限（発行日翌日0時 + d日）')

    # アップロード時に設定される情報
    title = models.CharField(max_length=255, null=True, blank=True)
    upload_type = models.CharField(max_length=100, null=True, blank=True)
    target_user = models.CharField(max_length=100, null=True, blank=True, help_text='指定ユーザー（フリーテキスト）')
    uploaded_file = models.FileField(upload_to=upload_to_download, null=True, blank=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)

    # ダウンロード時に設定される情報
    downloaded_at = models.DateTimeField(null=True, blank=True)
    download_user = models.CharField(max_length=100, null=True, blank=True)

    # 論理削除
    is_deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'download_token'
        ordering = ['-issued_at']
        verbose_name = 'ダウンロードトークン'
        verbose_name_plural = 'ダウンロードトークン'

    def __str__(self):
        return self.token

    @property
    def is_upload_expired(self):
        """アップロード期限切れかどうか"""
        return timezone.now() > self.upload_deadline

    @property
    def is_download_expired(self):
        """ダウンロード期限切れかどうか"""
        return timezone.now().date() > self.download_expire_date

    @property
    def is_uploaded(self):
        return bool(self.uploaded_file)


class DownloadUser(models.Model):
    """ダウンロード実行時の認証用ユーザー"""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='owned_download_users',
        help_text='登録したログインユーザー',
    )
    user_id = models.CharField(max_length=100, unique=True, help_text='任意の半角英数（アップロード時に指定）')
    user_name = models.CharField(max_length=100, null=True, blank=True, help_text='メール本文表示用')
    password = models.CharField(max_length=128, help_text='ハッシュ化して保存')
    comment = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = 'download_user'
        verbose_name = 'ダウンロードユーザー'
        verbose_name_plural = 'ダウンロードユーザー'

    def __str__(self):
        return self.user_id