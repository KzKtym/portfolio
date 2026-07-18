# app/work_shift/migrations/0005_member_model_restructure.py
#
# Shift/並び順の参照先を「Staff直接」から「Member（職員/スポットワーカー/募集枠を
# 包含する汎用識別子）」経由に置き換える大規模な構造変更。
# 既存データは python manage.py seed_work_shift で作り直す運用のため、
# AddField の default 値はプレースホルダーとして扱って問題ない。
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("work_shift", "0004_shift_deleted_at_and_team_staff_order"),
    ]

    operations = [
        migrations.CreateModel(
            name="SpotWorker",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
            ],
            options={"db_table": "wsft_spot_worker"},
        ),
        migrations.CreateModel(
            name="RecruitmentSlot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year_month", models.CharField(max_length=7)),
                ("slot_number", models.IntegerField()),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recruitment_slots",
                        to="work_shift.team",
                    ),
                ),
            ],
            options={"db_table": "wsft_recruitment_slot"},
        ),
        migrations.AlterUniqueTogether(
            name="recruitmentslot",
            unique_together={("team", "year_month", "slot_number")},
        ),
        migrations.CreateModel(
            name="Member",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "member_kind",
                    models.IntegerField(choices=[(0, "職員"), (1, "スポットワーカー"), (2, "募集枠")]),
                ),
                ("member_id", models.IntegerField()),
            ],
            options={"db_table": "wsft_member"},
        ),
        migrations.AlterUniqueTogether(
            name="member",
            unique_together={("member_kind", "member_id")},
        ),
        migrations.CreateModel(
            name="TeamMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_date", models.DateField()),
                ("end_date", models.DateField(blank=True, null=True)),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="team_memberships",
                        to="work_shift.member",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="work_shift.team",
                    ),
                ),
            ],
            options={"db_table": "wsft_team_membership"},
        ),

        # --- Shift: staff(FK) を member(FK) に置き換え ---
        # SQLiteは「unique_togetherが参照しているフィールド」を先に外しておかないと
        # テーブル再構築に失敗するため、先に旧unique_togetherを解除する
        migrations.AlterUniqueTogether(
            name="shift",
            unique_together=set(),
        ),
        migrations.RemoveField(model_name="shift", name="staff"),
        migrations.AddField(
            model_name="shift",
            name="member",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="shifts",
                to="work_shift.member",
                default=1,  # プレースホルダー。seed_work_shiftで実データを作り直す前提
            ),
            preserve_default=False,
        ),
        migrations.AlterUniqueTogether(
            name="shift",
            unique_together={("member", "date")},
        ),

        # --- TeamStaffOrder(staff直接参照) を廃止し、TeamMemberOrder(member経由参照)に置き換え ---
        migrations.AlterUniqueTogether(
            name="teamstafforder",
            unique_together=set(),
        ),
        migrations.RemoveField(model_name="teamstafforder", name="staff"),
        migrations.RemoveField(model_name="teamstafforder", name="team"),
        migrations.DeleteModel(name="TeamStaffOrder"),
        migrations.CreateModel(
            name="TeamMemberOrder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.IntegerField()),
                (
                    "member",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="team_orders",
                        to="work_shift.member",
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="member_orders",
                        to="work_shift.team",
                    ),
                ),
            ],
            options={"db_table": "wsft_team_member_order"},
        ),
        migrations.AlterUniqueTogether(
            name="teammemberorder",
            unique_together={("team", "member")},
        ),
    ]
