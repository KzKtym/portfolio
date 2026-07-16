from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('download', '0002_downloaduser_user_name_comment'),
    ]

    operations = [
        migrations.AddField(
            model_name='downloadtoken',
            name='issuer',
            field=models.ForeignKey(
                blank=True,
                help_text='管理画面から発行したログインユーザー（APIからの発行時はNULL）',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='issued_download_tokens',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='downloaduser',
            name='owner',
            field=models.ForeignKey(
                blank=True,
                help_text='登録したログインユーザー',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='owned_download_users',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]