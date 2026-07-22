from django.db import migrations, models
import django.db.models.deletion


def insert_default_project(apps, schema_editor):
    RagProject = apps.get_model("rag_tr_tool", "RagProject")
    RagProject.objects.create(
        id=1,
        name="Default",
        short_name="default",
        description="既存実験のデフォルトプロジェクト",
    )


def assign_default_project(apps, schema_editor):
    Experiment = apps.get_model("rag_tr_tool", "Experiment")
    Experiment.objects.filter(project__isnull=True).update(project_id=1)


class Migration(migrations.Migration):

    dependencies = [
        ("rag_tr_tool", "0003_ragproject_rename_experiment"),
    ]

    operations = [
        # デフォルトプロジェクト挿入
        migrations.RunPython(insert_default_project, migrations.RunPython.noop),
        # 既存 Experiment を project_id=1 に更新
        migrations.RunPython(assign_default_project, migrations.RunPython.noop),
        # project カラムを NOT NULL に変更
        migrations.AlterField(
            model_name="Experiment",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to="rag_tr_tool.ragproject",
            ),
        ),
    ]