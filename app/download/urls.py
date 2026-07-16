from django.urls import path

from . import views

app_name = 'download'

urlpatterns = [
    # トークン発行API
    path('api/token/', views.api_issue_token, name='api_issue_token'),
    # アップロードAPI
    path('api/upload/', views.api_upload, name='api_upload'),

    # ダウンロード管理画面
    path('manage/', views.manage_view, name='manage'),
    path('manage/issue/', views.manage_issue_token, name='manage_issue_token'),
    path('manage/delete/<str:token>/', views.manage_delete_token, name='manage_delete_token'),
    path('manage/user/add/', views.manage_user_add, name='manage_user_add'),
    path('manage/user/<int:user_id>/edit/', views.manage_user_edit, name='manage_user_edit'),
    path('manage/user/<int:user_id>/delete/', views.manage_user_delete, name='manage_user_delete'),

    # ダウンロード案内の下書き表示（管理画面配下・ログイン必須）
    path('manage/draft/<str:token>/', views.draft_view, name='draft'),

    # テストダウンロード（管理画面配下・ログイン必須）
    path('manage/test/<str:token>/', views.test_download_view, name='test_download'),

    # ダウンロード実行画面（最後に定義してパスの衝突を避ける）
    path('<str:token>/', views.download_view, name='download'),
]
