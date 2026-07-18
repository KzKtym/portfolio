# app/work_shift/migrations/0002_groupe_team_shift_restructure.py
#
# 前提: 既存データは python manage.py seed_work_shift で作り直す運用のため、
# AddField の default 値はプレースホルダーとして扱って問題ない。
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("work_shift", "0002_rename_event_defin_target__f07618_idx_wsft_event__target__ed875b_idx_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Groupe",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
            ],
            options={
                "db_table": "wsft_groupe",
            },
        ),
        migrations.AddField(
            model_name="team",
            name="group",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="teams",
                to="work_shift.groupe",
                default=1,  # プレースホルダー。seed_work_shiftで実データを作り直す前提
            ),
            preserve_default=False,
        ),
        migrations.RemoveField(
            model_name="staff",
            name="team",
        ),
        migrations.AddField(
            model_name="staff",
            name="default_team",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shift",
            name="team",
            field=models.IntegerField(default=1),  # プレースホルダー。seed_work_shiftで実データを作り直す前提
            preserve_default=False,
        ),
    ]
