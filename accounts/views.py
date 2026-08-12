"""
accounts アプリのビュー
"""
import logging
from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.generic import CreateView
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .lockout import check_locked, register_failure, register_success, should_revoke, user_key
from .middleware import SESSION_MEETING_KEY, get_client_ip
from .models import MeetingAccess, hash_meeting_token

logger = logging.getLogger(__name__)


def is_superuser(user):
    """管理者権限チェック"""
    return user.is_superuser


@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(is_superuser), name='dispatch')
class SignUpView(CreateView):
    """
    管理者によるユーザー作成ビュー
    管理者のみアクセス可能

    元はユーザー自身が登録するサインアップ画面だったが、当サイトでは「新規登録は管理者のみ」
    というルールにした。ただし逐一 /admin/ を開かなくても登録できるよう、画面自体は残している。
    """
    model = User
    form_class = UserCreationForm
    template_name = 'accounts/signup.html'
    # 作成後は管理者が普段いる /home/ へ戻す。連続登録の運用は想定していないため、
    # 管理サイトへは戻さない（home アプリ未実装だった頃の暫定 'admin:index' から変更）。
    success_url = reverse_lazy('home:home')
    
    def form_valid(self, form):
        """ユーザー作成成功時の処理"""
        response = super().form_valid(form)
        username = form.cleaned_data.get('username')
        
        # ログに記録
        logger.info(f'新規ユーザー作成: {username} (作成者: {self.request.user.username})')
        
        # 成功メッセージ
        messages.success(self.request, f'ユーザー「{username}」を作成しました。')
        
        return response
    
    def form_invalid(self, form):
        """ユーザー作成失敗時の処理"""
        logger.warning(f'ユーザー作成失敗: {self.request.user.username}')
        messages.error(self.request, 'ユーザー作成に失敗しました。入力内容を確認してください。')
        return super().form_invalid(form)


@require_http_methods(["GET"])
def signup_permission_denied(request):
    """
    サインアップ権限なしページ
    管理者以外がサインアップページにアクセスした場合
    """
    return render(request, 'accounts/signup_permission_denied.html', status=403)


# ═══════════════════════════════════════════════════
# ID/PWログイン（管理者・既存ユーザー用）
# ═══════════════════════════════════════════════════

class LockedLoginView(auth_views.LoginView):
    """Django標準のログイン画面に、失敗回数による一時ロックを足したもの。

    画面・フォームは標準のまま。ロック中はパスワードの照合そのものを行わない
    （照合させると総当たりの速度を落とせないため）。
    """

    def post(self, request, *args, **kwargs):
        username = (request.POST.get('username') or '').strip()
        self.lock_key = user_key(username, get_client_ip(request))

        remaining = check_locked(self.lock_key)
        if remaining:
            logger.warning(f'ロック中のログイン試行: key={self.lock_key} 残り{remaining}秒')
            messages.error(
                request,
                f'ログインの試行が制限されています。{remaining}秒後にもう一度お試しください。'
            )
            return redirect(request.get_full_path())

        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        register_success(self.lock_key)
        return super().form_valid(form)

    def form_invalid(self, form):
        lock = register_failure(self.lock_key, get_client_ip(self.request))
        if should_revoke(lock):
            # 管理者アカウントは締め出しを避けるため失効させない（監視で拾う想定）。
            logger.error(
                f'ログイン失敗が累計{lock.fail_total}回に達しました: key={self.lock_key}'
            )
        if lock.is_locked():
            messages.error(
                self.request,
                f'ログインの試行が制限されています。{lock.remaining_seconds()}秒後にもう一度お試しください。'
            )
        return super().form_invalid(form)


# ═══════════════════════════════════════════════════
# 商談用アクセス（トークンURL + パスワード）
# ═══════════════════════════════════════════════════

# Referer は外部（CDN等）へは送らせず、同一オリジンには送る。
#   'no-referrer' にすると Chrome がフォーム送信時に Origin: null を送るため、
#   DjangoのCSRF検証（Origin照合）が必ず失敗する。URLの漏洩防止は 'same-origin'
#   でも達成できる（外部へは Referer を一切送らない）。
REFERRER_POLICY = 'same-origin'


def _meeting_unavailable(request):
    """無効なリンクに対する共通レスポンス。

    期限切れ・失効・存在しないを区別せず同じ文面を返す（有効なトークンを
    探る手がかりを与えないため）。
    """
    response = render(request, 'accounts/meeting_unavailable.html', status=404)
    response['Referrer-Policy'] = REFERRER_POLICY
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@never_cache
@require_http_methods(["GET"])
def meeting_entry(request, token):
    """商談用トークンURLの着地点。

    トークンを検証したらすぐセッションへ移し、302でトークンを含まないURLへ飛ばす。
    ブラウザ履歴・Referer・アクセスログにトークンが残る窓を最小化するため、
    ここでは何も表示しない。ログイン自体はこの後のパスワード入力で行う。
    """
    access = (
        MeetingAccess.objects
        .select_related('user')
        .filter(token_hash=hash_meeting_token(token))
        .first()
    )
    if access is None or not access.is_available():
        logger.warning(f'商談用アクセス: 無効なトークンでの着地 from {get_client_ip(request)}')
        return _meeting_unavailable(request)

    request.session[SESSION_MEETING_KEY] = access.id
    logger.info(f'商談用アクセス: 着地 id={access.id} label={access.label}')

    response = redirect('guest:login')
    response['Referrer-Policy'] = REFERRER_POLICY
    return response


@never_cache
@require_http_methods(["GET", "POST"])
def meeting_login(request):
    """商談用アクセスのパスワード入力画面。

    トークンは meeting_entry がセッションへ入れた分だけを見る。直接ここへ来ても
    セッションが無ければ何もできない。
    """
    access_id = request.session.get(SESSION_MEETING_KEY)
    access = (
        MeetingAccess.objects.select_related('user').filter(id=access_id).first()
        if access_id else None
    )
    if access is None or not access.is_available():
        return _meeting_unavailable(request)

    error = None
    if request.method == 'POST':
        error = _meeting_authenticate(request, access)
        if error is None:
            return redirect(settings.LOGIN_REDIRECT_URL)
        if error == 'revoked':
            return _meeting_unavailable(request)

    response = render(request, 'accounts/meeting_login.html', {'access': access, 'error': error})
    response['Referrer-Policy'] = REFERRER_POLICY
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


def _meeting_authenticate(request, access):
    """商談用アクセスのパスワード照合。成功なら None、失敗ならエラー文言を返す"""
    remaining = check_locked(access.lock_key)
    if remaining:
        logger.warning(f'商談用アクセス: ロック中の試行 id={access.id} 残り{remaining}秒')
        return f'入力の試行が制限されています。{remaining}秒後にもう一度お試しください。'

    user = authenticate(
        request,
        username=access.user.username,
        password=request.POST.get('password', ''),
    )
    if user is None:
        lock = register_failure(access.lock_key, get_client_ip(request))
        if should_revoke(lock):
            access.revoke(MeetingAccess.REVOKE_LOCKOUT)
            logger.error(
                f'商談用アクセスを失効: id={access.id} label={access.label} '
                f'累計{lock.fail_total}回失敗'
            )
            return 'revoked'
        if lock.is_locked():
            return f'入力の試行が制限されています。{lock.remaining_seconds()}秒後にもう一度お試しください。'
        return 'パスワードが正しくありません。'

    register_success(access.lock_key)
    access.last_accessed_at = timezone.now()
    access.save(update_fields=['last_accessed_at'])
    login(request, user)
    logger.info(f'商談用アクセス: ログイン成功 id={access.id} user={user.username}')
    return None