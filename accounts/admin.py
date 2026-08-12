from django.contrib import admin

from .models import LoginHistory


@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    """ログイン履歴の閲覧用。追加・変更はできず、参照と絞り込みのみ。"""

    list_display = ('user', 'logged_in_at', 'ip_address', 'user_agent')
    list_filter = ('logged_in_at',)
    search_fields = ('user__username', 'ip_address')
    date_hierarchy = 'logged_in_at'
    ordering = ('-logged_in_at', '-id')
    readonly_fields = ('user', 'logged_in_at', 'ip_address', 'user_agent')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
