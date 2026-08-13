"""
home アプリのビュー
"""
import json
import logging
import os
import markdown
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.models import User
from django.db.models import OuterRef, Subquery
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from django.utils import timezone

from app.common.config import get_app_config_path, load_app_config
from accounts.models import (
    LoginHistory,
    LoginLockout,
    MeetingAccess,
    generate_meeting_password,
    generate_meeting_token,
    hash_meeting_token,
)
from app.common.decorators import no_cache_no_index
from app.common.permissions import is_superuser

logger = logging.getLogger(__name__)

APP_LABEL = 'home'
SYSTEM_INFO_MD = Path(settings.MEDIA_ROOT) / 'home' / 'system_information.md'

NO_INFORMATION = '（お知らせ無し）'

# 発行直後のURL・パスワードを1度だけ表示するためのセッションキー
SESSION_ISSUED_KEY = 'service_admin_issued'

# サービス管理画面の絞り込み。既定値は各タプルの先頭。
USER_FILTERS = ('active', 'all')
LOG_FILTERS = ('last', 'last3byu', 'tail20')
LOG_TAIL_COUNT = 20
LOG_PER_USER_COUNT = 3


def read_system_info_text():
    """お知らせMarkdownの生テキストを返す。ファイルが無ければ空文字。"""
    try:
        return SYSTEM_INFO_MD.read_text(encoding='utf-8')
    except FileNotFoundError:
        logger.warning(f'system_infomation.md が見つかりません: {SYSTEM_INFO_MD}')
        return ''


def render_system_info(text):
    """お知らせMarkdownをHTMLへ変換する。空なら代替文言を返す。

    編集できるのは管理者だけなので、生成HTMLはそのまま埋め込む（mark_safe）。
    """
    text = (text or '').strip()
    if not text:
        return NO_INFORMATION
    return mark_safe(markdown.markdown(text))


@method_decorator(no_cache_no_index, name='dispatch')
class HomeView(LoginRequiredMixin, TemplateView):
    """
    ログイン後のホーム画面
    認証が必要
    """
    template_name = 'home/home.html'

    def get_context_data(self, **kwargs):
        """テンプレートに渡すコンテキストデータ"""
        context = super().get_context_data(**kwargs)

        # ユーザー情報
        context['user'] = self.request.user
        context['current_time'] = timezone.now()

        # 「最終ログイン」は今回のログインではなく、その1つ前のログイン日時を出す。
        # user.last_login はログインの度に現在時刻へ更新され「今」になってしまうため、
        # LoginHistory の直近2件を取り、2件目（＝前回）の日時を採用する。
        recent = list(
            LoginHistory.objects
            .filter(user=self.request.user)
            .order_by('-logged_in_at', '-id')[:2]
        )
        context['previous_login'] = recent[1].logged_in_at if len(recent) > 1 else None

        # サービス一覧を JSON から読み込む
        try:
            context['services'] = load_app_config(APP_LABEL)
        except FileNotFoundError:
            logger.error(f'config.json が見つかりません: {get_app_config_path(APP_LABEL)}')
            context['services'] = []
        except json.JSONDecodeError as e:
            logger.error(f'config.json の解析に失敗しました: {e}')
            context['services'] = []

        # システムお知らせを Markdown ファイルから読み込む
        context['system_infomation'] = render_system_info(read_system_info_text())

        # ログに記録
        logger.info(f'ホームページアクセス: {self.request.user.username}')

        return context


@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(is_superuser), name='dispatch')
@method_decorator(no_cache_no_index, name='dispatch')
class ServiceAdminView(TemplateView):
    """
    サービス管理画面（管理者のみ）

    /admin/ を開くほどではない日常の確認・編集をまとめた画面。
      - ユーザー一覧（auth_user の参照のみ）
      - お知らせ管理（media/home/system_information.md の表示・編集）
      - アクセスログ（accounts_loginhistory の参照のみ）
    """
    template_name = 'home/service_admin.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # ── ユーザー一覧 ─────────────────────────────
        user_filter = self.request.GET.get('users', USER_FILTERS[0])
        if user_filter not in USER_FILTERS:
            user_filter = USER_FILTERS[0]
        users = User.objects.order_by('-id')
        if user_filter == 'active':
            users = users.filter(is_active=True)
        context['user_filter'] = user_filter
        context['users'] = users

        # ── お知らせ管理 ─────────────────────────────
        notice_text = read_system_info_text()
        context['notice_text'] = notice_text
        context['notice_html'] = render_system_info(notice_text)

        # ── 商談用アクセス ───────────────────────────
        context['meeting_accesses'] = self._meeting_accesses()
        context['meeting_expire_days'] = settings.MEETING_EXPIRE_DAYS
        # 発行結果は「閉じる」を押すまでセッションに残す。ここで消してしまうと
        # 画面を離れた瞬間に控え損ねるため（値そのものはDBに平文で持たない）。
        context['issued'] = self.request.session.get(SESSION_ISSUED_KEY)

        # ── アクセスログ ─────────────────────────────
        log_filter = self.request.GET.get('logs', LOG_FILTERS[0])
        if log_filter not in LOG_FILTERS:
            log_filter = LOG_FILTERS[0]
        context['log_filter'] = log_filter
        context['login_histories'] = self._login_histories(log_filter)

        logger.info(f'サービス管理画面アクセス: {self.request.user.username}')

        return context

    @staticmethod
    def _meeting_accesses():
        """商談用アクセスの一覧。各行に失敗カウンタ（LoginLockout）を添える"""
        accesses = list(
            MeetingAccess.objects.select_related('user', 'issuer').all()
        )
        locks = {
            lock.key: lock
            for lock in LoginLockout.objects.filter(
                key__in=[a.lock_key for a in accesses]
            )
        }
        for access in accesses:
            access.lock = locks.get(access.lock_key)
        return accesses

    @staticmethod
    def _login_histories(log_filter):
        """アクセスログの絞り込み結果を返す"""
        base = (
            LoginHistory.objects
            .select_related('user', 'meeting_access')
            .order_by('-logged_in_at', '-id')
        )

        if log_filter == 'tail20':
            return base[:LOG_TAIL_COUNT]

        if log_filter == 'last3byu':
            # 各ユーザーの新しい順3件。ユーザー単位で見比べる画面なので、
            # 全体の新しい順ではなくユーザーごとにまとめて並べる。
            return (
                base
                .filter(id__in=Subquery(ServiceAdminView._recent_ids(LOG_PER_USER_COUNT)))
                .order_by('user__username', '-logged_in_at', '-id')
            )

        # 'last': 各ユーザーの最終ログイン行だけを全体の新しい順で。
        return base.filter(id__in=Subquery(ServiceAdminView._recent_ids(1)))

    @staticmethod
    def _recent_ids(count):
        """ユーザーごとの新しい順 count 件の id を返す相関サブクエリ"""
        return (
            LoginHistory.objects
            .filter(user_id=OuterRef('user_id'))
            .order_by('-logged_in_at', '-id')
            .values('id')[:count]
        )


@login_required
@user_passes_test(is_superuser)
@require_POST
def service_admin_notice_save(request):
    """お知らせMarkdownを上書き保存する（管理者のみ）"""
    text = request.POST.get('content', '').replace('\r\n', '\n').replace('\r', '\n')

    try:
        SYSTEM_INFO_MD.parent.mkdir(parents=True, exist_ok=True)
        # 書き込み途中のファイルを /home/ 側に読ませないため、一時ファイル経由で置換する。
        tmp_path = SYSTEM_INFO_MD.with_name(SYSTEM_INFO_MD.name + '.tmp')
        tmp_path.write_text(text, encoding='utf-8')
        os.replace(tmp_path, SYSTEM_INFO_MD)
    except OSError as e:
        logger.error(f'お知らせの保存に失敗しました: {e}')
        messages.error(request, 'お知らせの保存に失敗しました。')
    else:
        logger.info(f'お知らせを更新: {request.user.username}')
        messages.success(request, 'お知らせを保存しました。')

    return redirect('service_admin:index')


@login_required
@user_passes_test(is_superuser)
@require_POST
def service_admin_notice_preview(request):
    """編集中のMarkdownを /home/ と同じ変換でHTML化して返す（管理者のみ）"""
    html = render_system_info(request.POST.get('content', ''))
    return JsonResponse({'html': html})


NEW_USER_CHOICE = '__new__'


def _create_meeting_user(request, raw_password):
    """商談用のユーザーを新規作成する。失敗したら None を返してメッセージを積む。

    ユーザー名の形式・重複の検証は Django標準の UserCreationForm に任せる
    （/accounts/signup/ と同じ規則にそろえるため）。パスワードは自動生成した
    ものを両欄に入れて渡すので、管理者は入力しない。
    """
    form = UserCreationForm({
        'username': (request.POST.get('new_username') or '').strip(),
        'password1': raw_password,
        'password2': raw_password,
    })
    if form.is_valid():
        user = form.save()
        logger.info(f'新規ユーザー作成: {user.username} (作成者: {request.user.username})')
        return user

    detail = ' / '.join(
        f'{field}: {error}'
        for field, errors in form.errors.items()
        for error in errors
    )
    logger.warning(f'ユーザー作成失敗: {request.user.username} ({detail})')
    messages.error(request, f'ユーザー作成に失敗しました。{detail}')
    return None


def _issue_meeting_access(request, label, user, expire_days, raw_password):
    """商談用アクセスを1件作り、生のURL・パスワードをセッションに置く"""
    raw_token = generate_meeting_token()
    access = MeetingAccess.objects.create(
        label=label,
        user=user,
        issuer=request.user,
        token_hash=hash_meeting_token(raw_token),
        expires_at=timezone.now() + timedelta(days=expire_days),
    )

    # 生の値はDBに残さない方針のため、発行結果は管理者のセッションにだけ置く。
    # 「閉じる」を押すまで画面に出し続ける（控え損ねの救済）。
    request.session[SESSION_ISSUED_KEY] = {
        'access_id': access.id,
        'label': access.label,
        'username': user.username,
        'url': request.build_absolute_uri(reverse('guest:entry', args=[raw_token])),
        'password': raw_password,
        'expires_at': access.expires_at.isoformat(),
    }

    logger.info(
        f'商談用アクセスを発行: id={access.id} label={label} user={user.username} '
        f'({expire_days}日間, 発行者: {request.user.username})'
    )
    return access


def _expire_days_from(request):
    """入力された有効日数を設定の範囲に丸める"""
    try:
        days = int(request.POST.get('expire_days') or settings.MEETING_EXPIRE_DAYS)
    except ValueError:
        days = settings.MEETING_EXPIRE_DAYS
    return max(1, min(days, settings.MEETING_EXPIRE_DAYS))


@login_required
@user_passes_test(is_superuser)
@require_POST
def service_admin_meeting_issue(request):
    """商談用アクセスを発行する（管理者のみ）

    対象ユーザーは「新規作成」（既定）か既存ユーザーの選択。新規作成の場合は
    ユーザー作成と発行を1回の操作でまとめて行う。
    トークンとパスワードはここで生成し、DBに保存するのはハッシュだけ。
    """
    label = (request.POST.get('label') or '').strip()
    username = (request.POST.get('username') or '').strip()
    expire_days = _expire_days_from(request)

    if not label:
        messages.error(request, '商談名・相手先を入力してください。')
        return redirect('service_admin:index')

    if username == NEW_USER_CHOICE or not username:
        # 新規作成: パスワードは常に自動生成
        raw_password = generate_meeting_password()
        user = _create_meeting_user(request, raw_password)
        if user is None:
            return redirect('service_admin:index')
    else:
        user = User.objects.filter(username=username).first()
        if user is None:
            messages.error(request, '対象ユーザーが見つかりません。')
            return redirect('service_admin:index')
        raw_password = ''
        if request.POST.get('regenerate_password') == 'on':
            raw_password = generate_meeting_password()
            user.set_password(raw_password)
            user.save(update_fields=['password'])

    _issue_meeting_access(request, label, user, expire_days, raw_password)
    messages.success(request, f'商談用アクセス「{label}」を発行しました。')
    return redirect('service_admin:index')


@login_required
@user_passes_test(is_superuser)
@require_POST
def service_admin_meeting_reissue(request, pk):
    """商談用アクセスを再発行する（管理者のみ）

    URLとパスワードは発行時にしか表示できない（DBにはハッシュしか無い）。
    控え損ねた・相手に送り直したい場合は、同じ商談名・ユーザーで新しい
    URLとパスワードを作り直し、元のトークンは失効させる。
    """
    old = get_object_or_404(MeetingAccess, pk=pk)

    raw_password = generate_meeting_password()
    old.user.set_password(raw_password)
    old.user.save(update_fields=['password'])

    access = _issue_meeting_access(
        request, old.label, old.user, _expire_days_from(request), raw_password
    )
    old.revoke(MeetingAccess.REVOKE_MANUAL)

    logger.info(f'商談用アクセスを再発行: old_id={old.id} new_id={access.id}')
    messages.success(
        request,
        f'商談用アクセス「{old.label}」を再発行しました。以前のURLとパスワードは使えません。'
    )
    return redirect('service_admin:index')


@login_required
@user_passes_test(is_superuser)
@require_POST
def service_admin_issued_dismiss(request):
    """発行結果パネルを閉じる（セッションから消す）"""
    request.session.pop(SESSION_ISSUED_KEY, None)
    return redirect('service_admin:index')


@login_required
@user_passes_test(is_superuser)
@require_POST
def service_admin_meeting_revoke(request, pk):
    """商談用アクセスを手動で失効させる（管理者のみ）"""
    access = get_object_or_404(MeetingAccess, pk=pk)
    access.revoke(MeetingAccess.REVOKE_MANUAL)
    logger.info(
        f'商談用アクセスを失効: id={access.id} label={access.label} '
        f'(操作者: {request.user.username})'
    )
    messages.success(request, f'商談用アクセス「{access.label}」を失効しました。')
    return redirect('service_admin:index')