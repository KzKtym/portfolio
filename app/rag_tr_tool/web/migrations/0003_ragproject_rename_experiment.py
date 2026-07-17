from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("web", "0002_experiment_is_starred"),
    ]

    operations = [
        # RagProject テーブル作成
        migrations.CreateModel(
            name="RagProject",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("short_name", models.CharField(max_length=50)),
                ("description", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "rag_project",
            },
        ),
        # Experiment の物理テーブル名を rag_experiment に変更
        migrations.AlterModelTable(
            name="Experiment",
            table="rag_experiment",
        ),
        # Experiment に project ForeignKey 追加（null=True で一時的に許容）
        migrations.AddField(
            model_name="Experiment",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to="web.ragproject",
            ),
        ),
    ]