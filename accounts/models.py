from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


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

    class Meta:
        verbose_name = 'ログイン履歴'
        verbose_name_plural = 'ログイン履歴'
        ordering = ('-logged_in_at', '-id')
        indexes = [
            models.Index(fields=['user', '-logged_in_at']),
        ]

    def __str__(self):
        return f'{self.user.username} @ {self.logged_in_at:%Y-%m-%d %H:%M}'
