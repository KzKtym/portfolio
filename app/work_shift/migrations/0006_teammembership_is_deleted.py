# app/work_shift/migrations/0006_teammembership_is_deleted.py
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("work_shift", "0005_member_model_restructure"),
    ]

    operations = [
        migrations.AddField(
            model_name="teammembership",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
    ]
