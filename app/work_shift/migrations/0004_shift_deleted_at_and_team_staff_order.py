# app/work_shift/migrations/0004_shift_deleted_at_and_team_staff_order.py
#
# 依存先のファイル名は、お手元の実際のマイグレーション履歴（前回リネームした
# 0003_groupe_team_shift_restructure など）に合わせて必要に応じて調整してください。
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("work_shift", "0003_groupe_team_shift_restructure"),
    ]

    operations = [
        migrations.AddField(
            model_name="shift",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="TeamStaffOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.IntegerField()),
                (
                    "staff",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="team_orders",
                        to="work_shift.staff",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="staff_orders",
                        to="work_shift.team",
                    ),
                ),
            ],
            options={
                "db_table": "wsft_team_staff_order",
            },
        ),
        migrations.AlterUniqueTogether(
            name="teamstafforder",
            unique_together={("team", "staff")},
        ),
    ]
