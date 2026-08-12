"""
ログイン失敗のカウントと一時ロック。

ID/PWログイン（管理者用）と商談用トークンログインの両方がここを通る。方針:

  - 連続 LOGIN_LOCK_THRESHOLD 回の失敗で一時ロック。
  - ロック秒数は LOGIN_LOCK_SECONDS から失敗ごとに倍化し、LOGIN_LOCK_MAX_SECONDS で頭打ち。
  - カウンタは「ログイン成功時のみ」リセットする。時間窓で自然回復させると、
    窓の直前で止める総当たり（例: 29秒ごとに9回）を素通ししてしまうため。
  - 累計 MEETING_REVOKE_THRESHOLD 回で商談用トークンは失効（呼び出し側が判断）。
    管理者アカウントは締め出しを避けるため失効させず、ERRORログのみ出す。

カウンタはDBに置く。キャッシュ（既定は LocMemCache）はプロセスごとに分かれるため、
gunicorn のワーカーが複数あると数え漏れる。
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import LoginLockout

logger = logging.getLogger(__name__)


def user_key(username, ip=None):
    """ID/PWログイン用のロックキー。

    既定（LOGIN_LOCK_SCOPE='user_ip'）はユーザー名+IP。ユーザー名だけで数えると
    第三者がわざと失敗させて管理者を締め出せる（自DoS）ため、既定では分けている。
    分散攻撃まで想定するなら .env で 'user' に切り替える。
    """
    if settings.LOGIN_LOCK_SCOPE == 'user' or not ip:
        return f'user:{username}'
    return f'user:{username}@{ip}'


def get_lock(key):
    """ロック行を取得する（無ければ None）"""
    return LoginLockout.objects.filter(key=key).first()


def check_locked(key):
    """ロック中なら残り秒数、そうでなければ0を返す"""
    lock = get_lock(key)
    return lock.remaining_seconds() if lock else 0


def _lock_seconds(fail_count):
    """連続失敗回数からロック秒数を求める（閾値到達後に倍化）"""
    over = fail_count - settings.LOGIN_LOCK_THRESHOLD
    seconds = settings.LOGIN_LOCK_SECONDS * (2 ** over)
    return min(seconds, settings.LOGIN_LOCK_MAX_SECONDS)


def register_failure(key, ip=None):
    """失敗を1回数える。閾値に達していればロックをかけ、更新後の行を返す"""
    now = timezone.now()
    with transaction.atomic():
        lock, _ = LoginLockout.objects.select_for_update().get_or_create(key=key)
        lock.fail_count += 1
        lock.fail_total += 1
        lock.last_failed_at = now
        lock.last_ip = ip or None
        if lock.fail_count >= settings.LOGIN_LOCK_THRESHOLD:
            seconds = _lock_seconds(lock.fail_count)
            lock.locked_until = now + timedelta(seconds=seconds)
            logger.warning(
                f'ログイン試行をロック: key={key} 連続{lock.fail_count}回 '
                f'({seconds}秒 / 累計{lock.fail_total}回)'
            )
        lock.save()
    return lock


def register_success(key):
    """成功したのでカウンタとロックを解除する"""
    LoginLockout.objects.filter(key=key).update(
        fail_count=0, locked_until=None,
    )


def should_revoke(lock):
    """累計失敗が失効閾値に達したか"""
    return lock.fail_total >= settings.MEETING_REVOKE_THRESHOLD
