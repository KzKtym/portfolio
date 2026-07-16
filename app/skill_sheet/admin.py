from django.contrib import admin
from .models import SkillSheetData, PersonalInfo

admin.site.register(PersonalInfo)
admin.site.register(SkillSheetData)

# @admin.register(YourModel)
# class YourModelAdmin(admin.ModelAdmin):
#     list_display = ['id', 'name', 'created_at']  # 一覧に表示する項目
#     list_filter = ['created_at']  # フィルタ項目
#     search_fields = ['name']  # 検索可能な項目
#     ordering = ['-created_at']  # デフォルトの並び順
