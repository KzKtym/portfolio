"""
accounts アプリのカスタムミドルウェア
ログイン・ログアウト・認証失敗のログを記録
"""
import logging
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    """ログイン成功時のログ記録と履歴の保存"""
    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')

    logger.info(f'ログイン成功: {user.username} from {ip_address} ({user_agent})')

    # ログイン履歴を1行残す。履歴保存の失敗が認証そのものを止めないよう、
    # ここでの例外は握りつぶしてログにのみ残す。
    try:
        from .models import LoginHistory
        LoginHistory.objects.create(
            user=user,
            ip_address=ip_address or None,
            user_agent=(user_agent or '')[:255],
        )
    except Exception:
        logger.exception(f'ログイン履歴の保存に失敗: {user.username}')


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    """ログアウト時のログ記録"""
    if user:
        ip_address = get_client_ip(request)
        logger.info(f'ログアウト: {user.username} from {ip_address}')


@receiver(user_login_failed)
def log_user_login_failed(sender, credentials, request, **kwargs):
    """ログイン失敗時のログ記録"""
    ip_address = get_client_ip(request)
    username = credentials.get('username', 'unknown')
    
    logger.warning(f'ログイン失敗: {username} from {ip_address}')


def get_client_ip(request):
    """クライアントのIPアドレスを取得"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip