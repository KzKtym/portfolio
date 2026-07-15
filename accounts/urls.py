"""
accounts アプリのURL設定
"""
from django.urls import path, include, reverse_lazy
from django.contrib.auth import views as auth_views
from . import views

app_name = 'accounts'

urlpatterns = [
    # Django標準の認証ビュー
    path('login/', auth_views.LoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),

    # パスワード変更（success_url は名前空間付きで明示）
    path('password_change/',
         auth_views.PasswordChangeView.as_view(
             success_url=reverse_lazy('accounts:password_change_done')),
         name='password_change'),
    path('password_change/done/', auth_views.PasswordChangeDoneView.as_view(), name='password_change_done'),

    # パスワードリセット（success_url は名前空間付きで明示）
    path('password_reset/',
         auth_views.PasswordResetView.as_view(
             success_url=reverse_lazy('accounts:password_reset_done')),
         name='password_reset'),
    path('password_reset/done/', auth_views.PasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(
             success_url=reverse_lazy('accounts:password_reset_complete')),
         name='password_reset_confirm'),
    path('reset/done/', auth_views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    
    # カスタムビュー（管理者による新規ユーザー作成）
    path('signup/', views.SignUpView.as_view(), name='signup'),
]
