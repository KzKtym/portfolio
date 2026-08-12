from django.contrib import admin
from .models import CellBinding, SkillSheetData, PersonalInfo

admin.site.register(PersonalInfo)
admin.site.register(SkillSheetData)


@admin.register(CellBinding)
class CellBindingAdmin(admin.ModelAdmin):
    list_display = ['name', 'label', 'target', 'writable', 'updated_at']
    list_filter = ['writable', 'model_label']
    search_fields = ['name', 'label', 'description']
    ordering = ['name']
    fieldsets = (
        (None, {
            'fields': ('name', 'label', 'description'),
        }),
        ('同期先', {
            'fields': ('model_label', 'field_name', 'record_id'),
            'description': 'ローカル側には公開されない。クライアントが知るのは名称だけ。',
        }),
        ('権限', {
            'fields': ('writable',),
            'description': 'writable を外すと pull（DB→ローカル）専用になる。',
        }),
    )

    @admin.display(description='同期先')
    def target(self, obj):
        return f"{obj.model_label}.{obj.field_name} #{obj.record_id}"
