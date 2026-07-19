"""
accounts アプリのビュー
"""
import logging
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import CreateView
from django.views.decorators.http import require_http_methods

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