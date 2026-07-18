# app/work_shift/migrations/0010_shift_requirement.py
"""
予定数（勤務タイプ×日付ごとの必要人数）を管理する ShiftRequirement を新設する。
これまで固定値(MOCK_SHIFT_TYPE_REQUIREMENTS)だった「小計」行の分母を、
チーム×日付×勤務タイプ単位で個別に保存・編集できるようにする（予定数タブ F2）。

注意: このマイグレーションは一度 0009 まで巻き戻してから再適用する運用を想定している
（モデル名を ShiftTypeRequirement → ShiftRequirement に変更したため）。
    python manage.py migrate work_shift 0009
    python manage.py migrate work_shift
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("work_shift", "0009_work_shift_type_order"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShiftRequirement",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("required_count", models.IntegerField(default=0)),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="shift_requirements",
                        to="work_shift.team",
                    ),
                ),
                (
                    "work_shift_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="requirements",
                        to="work_shift.workshifttype",
                    ),
                ),
            ],
            options={
                "db_table": "wsft_shift_requirements",
            },
        ),
        migrations.AlterUniqueTogether(
            name="shiftrequirement",
            unique_together={("team", "date", "work_shift_type")},
        ),
    ]
