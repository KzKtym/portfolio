# app/work_shift/migrations/0009_work_shift_type_order.py
"""
勤務タイプマスタ（WorkShiftType）に「並び順」（order）を追加する。
一覧・日付クリックのパネル・下部集計行の並びは、これまでのid昇順からorder昇順に統一する。
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("work_shift", "0008_work_shift_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="workshifttype",
            name="order",
            field=models.IntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name="workshifttype",
            options={"ordering": ["order", "id"]},
        ),
    ]
