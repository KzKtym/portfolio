"""
商談用アクセス（ゲスト）のURL設定

相手に渡すURLなので短く保つ。ビューは accounts/views.py 側にあるが、
/accounts/ 配下だと長くなるためトップレベル /guest/ に生やしている。

  /guest/<token>/  … 着地。検証してセッションへ移し、すぐ /guest/ へ302
  /guest/          … パスワード入力（トークンはURLに出さない）
"""
from django.urls import path

from . import views

app_name = 'guest'

urlpatterns = [
    path('', views.meeting_login, name='login'),
    path('<str:token>/', views.meeting_entry, name='entry'),
]
