"""
home アプリのビュー
"""
import json
import logging
import markdown
from pathlib import Path
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from django.utils.safestring import mark_safe
from django.views.generic import TemplateView
from django.utils import timezone

from accounts.models import LoginHistory
from .decorators import no_cache_no_index

logger = logging.getLogger(__name__)

SERVICES_JSON = Path(__file__).parent / 'config.json'
SYSTEM_INFO_MD = Path(settings.MEDIA_ROOT) / 'home' / 'system_information.md'


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
            with SERVICES_JSON.open(encoding='utf-8') as f:
                context['services'] = json.load(f)
        except FileNotFoundError:
            logger.error(f'config.json が見つかりません: {SERVICES_JSON}')
            context['services'] = []
        except json.JSONDecodeError as e:
            logger.error(f'config.json の解析に失敗しました: {e}')
            context['services'] = []

        # システムお知らせを Markdown ファイルから読み込む
        try:
            text = SYSTEM_INFO_MD.read_text(encoding='utf-8').strip()
            if text:
                context['system_infomation'] = mark_safe(markdown.markdown(text))
            else:
                context['system_infomation'] = '（お知らせ無し）'
        except FileNotFoundError:
            logger.warning(f'system_infomation.md が見つかりません: {SYSTEM_INFO_MD}')
            context['system_infomation'] = '（お知らせ無し）'

        # ログに記録
        logger.info(f'ホームページアクセス: {self.request.user.username}')

        return context