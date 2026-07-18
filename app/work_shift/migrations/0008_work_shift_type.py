# app/work_shift/migrations/0008_work_shift_type.py
"""
勤務タイプ（WorkShiftType）マスタを新設する。

- サイドメニュー「デモ用管理」→「勤務タイプ」のCRUD画面用（グループ単位で管理）
- 「休」のように実働時間を持たない種別も許容するため、start_time/end_time/break_minutesは
  いずれもNULL可
- Shift.shift_type自体はこれまで通り自由文字列のまま変更しない
  （保存時にこのマスタの名称と一致するかをAPI側でチェックするのみ）
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("work_shift", "0007_order_consolidation"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkShiftType",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=20)),
                ("start_time", models.TimeField(blank=True, null=True)),
                ("is_overnight", models.BooleanField(default=False)),
                ("end_time", models.TimeField(blank=True, null=True)),
                ("break_minutes", models.IntegerField(blank=True, null=True)),
                ("color", models.CharField(max_length=7)),
                (
                    "group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="work_shift_types",
                        to="work_shift.groupe",
                    ),
                ),
            ],
            options={
                "db_table": "wsft_work_shift_types",
                "ordering": ["id"],
            },
        ),
    ]
