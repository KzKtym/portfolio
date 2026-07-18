# app/work_shift/migrations/0007_order_consolidation.py
"""
「＝」並び順の管理方法を再設計する。

- TeamMemberOrder（旧: チーム単位で1テーブル管理）を廃止
- TeamMembership.order へ統合（当月・将来月の並び順はこちらを使う）
- Shift.order を新設（過去月の並び順は、保存時点のTeamMembership.orderのスナップショットである
  こちらを使う。9節の設計原則「過去分はマスター変更の影響を受けない」に対応するため）
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("work_shift", "0006_teammembership_is_deleted"),
    ]

    operations = [
        migrations.AddField(
            model_name="teammembership",
            name="order",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="shift",
            name="order",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.DeleteModel(name="TeamMemberOrder"),
    ]
