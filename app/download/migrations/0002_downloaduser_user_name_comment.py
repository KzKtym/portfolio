from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('download', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='downloaduser',
            name='user_name',
            field=models.CharField(blank=True, help_text='メール本文表示用', max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='downloaduser',
            name='comment',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name='downloaduser',
            name='user_id',
            field=models.CharField(help_text='任意の半角英数（アップロード時に指定）', max_length=100, unique=True),
        ),
    ]
