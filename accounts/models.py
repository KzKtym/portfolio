import secrets
import string
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.crypto import salted_hmac

# トークン・パスワードに使う文字集合。
# パスワードは口頭伝達・スマホ入力を想定し、紛らわしい文字（0/O/o/1/l/I）を除く。
TOKEN_CHARS = string.ascii_lowercase + string.digits
PASSWORD_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'


def generate_meeting_token():
    """商談用アクセスのトークン（URLに載る値）を生成する"""
    return ''.join(secrets.choice(TOKEN_CHARS) for _ in range(settings.MEETING_TOKEN_LENGTH))


def generate_meeting_password():
    """商談用アカウントのパスワードを生成する（人には決めさせない）"""
    return ''.join(secrets.choice(PASSWORD_CHARS) for _ in range(settings.MEETING_PASSWORD_LENGTH))


def hash_meeting_token(raw_token):
    """トークンの保存・照合用ハッシュ。

    32桁ランダム（約165bit）で総当たりの余地がないため、パスワードのような
    低速ハッシュではなくインデックス検索できる HMAC-SHA1 を使う。
    SECRET_KEY が pepper として効くので、DBだけを抜かれても復元できない。
    """
    return salted_hmac('accounts.MeetingAccess.token', raw_token).hexdigest()


class LoginHistory(models.Model):
    """ログイン成功を1件1行で記録する履歴。

    Django 標準の User をそのまま使っているため、User にフィールドを足さず
    外付けの履歴テーブルで扱う。用途は次の3つ:
      - ホーム画面の「最終ログイン」表示（今回を除く直近の1件）
      - アクセス元IPの保全（画面には出さず、管理サイト・調査用）
      - 数日分のログイン履歴の追跡

    行は user_logged_in シグナル（accounts/middleware.py）が作成する。
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='login_history',
        verbose_name='ユーザー',
    )
    logged_in_at = models.DateTimeField(
        default=timezone.now,
        verbose_name='ログイン日時',
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name='IPアドレス',
    )
    user_agent = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='ユーザーエージェント',
    )
    meeting_access = models.ForeignKey(
        'MeetingAccess',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='login_histories',
        verbose_name='商談用アクセス',
        help_text='商談用トークン経由のログインならその発行分。ID/PWログインならNULL',
    )

    class Meta:
        verbose_name = 'ログイン履歴'
        verbose_name_plural = 'ログイン履歴'
        ordering = ('-logged_in_at', '-id')
        indexes = [
            models.Index(fields=['user', '-logged_in_at']),
        ]

    def __str__(self):
        return f'{self.user.username} @ {self.logged_in_at:%Y-%m-%d %H:%M}'


class LoginLockout(models.Model):
    """ログイン失敗の回数と一時ロックの状態を持つ行。

    ID/PWログイン・商談用トークンログインの両方が同じ仕組みを使う。key の形式は
      - 'user:<username>' / 'user:<username>@<ip>'  … ID/PWログイン（LOGIN_LOCK_SCOPE で切替）
      - 'meeting:<id>'                              … 商談用アクセス
    運用中に閾値を変えられるよう、判定ロジックは accounts/lockout.py に集約している。
    """

    key = models.CharField(max_length=191, unique=True, verbose_name='ロックキー')
    fail_count = models.PositiveIntegerField(
        default=0,
        verbose_name='連続失敗回数',
        help_text='ログイン成功でのみ0に戻る（時間経過では戻さない）',
    )
    fail_total = models.PositiveIntegerField(default=0, verbose_name='累計失敗回数')
    locked_until = models.DateTimeField(null=True, blank=True, verbose_name='ロック解除日時')
    last_failed_at = models.DateTimeField(null=True, blank=True, verbose_name='最終失敗日時')
    last_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name='最終失敗IP')

    class Meta:
        verbose_name = 'ログインロック'
        verbose_name_plural = 'ログインロック'
        ordering = ('-last_failed_at',)

    def __str__(self):
        return f'{self.key} (連続{self.fail_count}/累計{self.fail_total})'

    def is_locked(self, now=None):
        now = now or timezone.now()
        return bool(self.locked_until and self.locked_until > now)

    def remaining_seconds(self, now=None):
        """ロック解除までの残り秒数（ロック中でなければ0）"""
        now = now or timezone.now()
        if not self.is_locked(now):
            return 0
        return int((self.locked_until - now).total_seconds()) + 1


class MeetingAccess(models.Model):
    """商談用の一時アクセス（トークンURL + パスワード）。

    トークンは「誰のアカウントか」を指すだけで、これ単体ではログインできない。
    着地後は必ずパスワード入力を求める（accounts/views.py の meeting_entry →
    meeting_login）。トークン自体は平文で持たず、HMAC ハッシュだけを保存する。
    """

    REVOKE_MANUAL = 'manual'
    REVOKE_LOCKOUT = 'lockout'
    REVOKE_REASONS = (
        (REVOKE_MANUAL, '手動失効'),
        (REVOKE_LOCKOUT, '失敗回数超過'),
    )

    label = models.CharField(max_length=100, verbose_name='商談名・相手先')
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='meeting_accesses',
        verbose_name='紐づくユーザー',
    )
    issuer = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='issued_meeting_accesses',
        verbose_name='発行者',
    )
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name='トークンハッシュ',
    )
    issued_at = models.DateTimeField(default=timezone.now, verbose_name='発行日時')
    expires_at = models.DateTimeField(verbose_name='有効期限')
    last_accessed_at = models.DateTimeField(null=True, blank=True, verbose_name='最終アクセス')
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name='失効日時')
    revoked_reason = models.CharField(
        max_length=20,
        blank=True,
        default='',
        choices=REVOKE_REASONS,
        verbose_name='失効理由',
    )
    note = models.CharField(max_length=255, blank=True, default='', verbose_name='メモ')

    class Meta:
        verbose_name = '商談用アクセス'
        verbose_name_plural = '商談用アクセス'
        ordering = ('-issued_at',)

    def __str__(self):
        return f'{self.label}（{self.user.username}）'

    @property
    def lock_key(self):
        return f'meeting:{self.pk}'

    def is_expired(self, now=None):
        """絶対期限切れ"""
        return (now or timezone.now()) >= self.expires_at

    def is_idle_expired(self, now=None):
        """無操作期限切れ（MEETING_IDLE_DAYS が0なら常にFalse）"""
        idle_days = settings.MEETING_IDLE_DAYS
        if not idle_days:
            return False
        base = self.last_accessed_at or self.issued_at
        return (now or timezone.now()) >= base + timedelta(days=idle_days)

    def is_available(self, now=None):
        """このトークンでパスワード入力画面まで進めるか"""
        now = now or timezone.now()
        return not (self.revoked_at or self.is_expired(now) or self.is_idle_expired(now))

    @property
    def status(self):
        """管理画面に出す状態ラベル"""
        if self.revoked_at:
            return '失効（%s）' % self.get_revoked_reason_display()
        if self.is_expired():
            return '期限切れ'
        if self.is_idle_expired():
            return '無操作期限切れ'
        return '有効'

    def revoke(self, reason=REVOKE_MANUAL):
        """失効させる（すでに失効済みなら何もしない）"""
        if self.revoked_at:
            return
        self.revoked_at = timezone.now()
        self.revoked_reason = reason
        self.save(update_fields=['revoked_at', 'revoked_reason'])
