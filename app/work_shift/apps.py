# app/work_shift/apps.py
from django.apps import AppConfig


class WorkShiftConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app.work_shift"
    label = "work_shift"
    verbose_name = "シフト管理"
