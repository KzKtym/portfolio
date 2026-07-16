from app.download import models as download_models
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='DownloadToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(db_index=True, default=download_models.generate_token, max_length=32, unique=True)),
                ('issued_at', models.DateTimeField(auto_now_add=True)),
                ('upload_deadline', models.DateTimeField(help_text='アップロード期限（発行日時 + m分）')),
                ('download_expire_date', models.DateField(help_text='ダウンロード有効期限（発行日翌日0時 + d日）')),
                ('title', models.CharField(blank=True, max_length=255, null=True)),
                ('upload_type', models.CharField(blank=True, max_length=100, null=True)),
                ('target_user', models.CharField(blank=True, help_text='指定ユーザー（フリーテキスト）', max_length=100, null=True)),
                ('uploaded_file', models.FileField(blank=True, null=True, upload_to=download_models.upload_to_download)),
                ('uploaded_at', models.DateTimeField(blank=True, null=True)),
                ('downloaded_at', models.DateTimeField(blank=True, null=True)),
                ('download_user', models.CharField(blank=True, max_length=100, null=True)),
                ('is_deleted', models.BooleanField(default=False)),
            ],
            options={
                'verbose_name': 'ダウンロードトークン',
                'verbose_name_plural': 'ダウンロードトークン',
                'db_table': 'download_token',
                'ordering': ['-issued_at'],
            },
        ),
        migrations.CreateModel(
            name='DownloadUser',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_id', models.CharField(max_length=100, unique=True)),
                ('password', models.CharField(help_text='ハッシュ化して保存', max_length=128)),
            ],
            options={
                'verbose_name': 'ダウンロードユーザー',
                'verbose_name_plural': 'ダウンロードユーザー',
                'db_table': 'download_user',
            },
        ),
    ]
