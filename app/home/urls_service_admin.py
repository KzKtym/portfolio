"""
サービス管理画面のURL設定

ビューは home アプリ（app/home/views.py）に置くが、URLは /home/ 配下ではなく
/service_admin/ に生やすため、home:home とは別の名前空間として切り出している。
"""
from django.urls import path

from . import views

app_name = 'service_admin'

urlpatterns = [
    path('', views.ServiceAdminView.as_view(), name='index'),
    path('notice/save/', views.service_admin_notice_save, name='notice_save'),
    path('notice/preview/', views.service_admin_notice_preview, name='notice_preview'),
    path('meeting/issue/', views.service_admin_meeting_issue, name='meeting_issue'),
    path('meeting/<int:pk>/revoke/', views.service_admin_meeting_revoke, name='meeting_revoke'),
    path('meeting/<int:pk>/reissue/', views.service_admin_meeting_reissue, name='meeting_reissue'),
    path('issued/dismiss/', views.service_admin_issued_dismiss, name='issued_dismiss'),
]
