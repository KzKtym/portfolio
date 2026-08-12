from django.urls import path
from . import api_views, binding_views, views

app_name = 'skill_sheet'

urlpatterns = [
    path('', views.index, name='index'),

    # セル同期API（ローカルのスプレッド形式アプリ向け）
    path('api/cells/', api_views.api_cells, name='api_cells'),
    path('api/bindings/', api_views.api_bindings, name='api_bindings'),

    # セル同期定義の管理（管理者のみ）
    path('bindings/', binding_views.binding_list, name='binding_list'),
    path('bindings/new/', binding_views.binding_create, name='binding_create'),
    path('bindings/<int:pk>/', binding_views.binding_edit, name='binding_edit'),

    path('<int:pk>/', views.detail, name='detail'),
]
