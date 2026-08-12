"""古いログイン履歴を削除する管理コマンド。

履歴は放置すると無制限に増えるため、保持期間を過ぎた行を落とす。
cron で定期実行する運用を想定（自動スケジュールは設定しない）。

    python manage.py prune_login_history            # 既定: 90日より前を削除
    python manage.py prune_login_history --days 30
    python manage.py prune_login_history --days 30 --dry-run
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import LoginHistory


class Command(BaseCommand):
    help = '指定日数より古いログイン履歴を削除する（既定: 90日）'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='この日数より古い履歴を削除する（既定: 90）',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='削除せず、対象件数だけを表示する',
        )

    def handle(self, *args, **options):
        days = options['days']
        if days < 0:
            self.stderr.write('--days は0以上を指定してください。')
            return

        cutoff = timezone.now() - timedelta(days=days)
        target = LoginHistory.objects.filter(logged_in_at__lt=cutoff)
        count = target.count()

        if options['dry_run']:
            self.stdout.write(f'[dry-run] {count} 件が削除対象です（{days}日より前）。')
            return

        target.delete()
        self.stdout.write(f'{count} 件のログイン履歴を削除しました（{days}日より前）。')
