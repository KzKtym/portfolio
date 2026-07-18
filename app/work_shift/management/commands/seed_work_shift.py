# app/work_shift/management/commands/seed_work_shift.py
"""
デモ用シードデータ投入コマンド。

使い方:
    python manage.py seed_work_shift            # 今月を「当月」としてデータを生成
    python manage.py seed_work_shift --ym 2026-07

既存の wsft_* データを全削除してから投入するので注意（デモ専用）。

投入内容（確定仕様。氏名は仮名。名字ランキング上位から選定）:
- 勤務タイプマスタ: 日1・早1・遅1・夜勤・休 の5種（グループ単位）
- 当月（--ym。省略時は今月）:
    職員2名（佐藤・鈴木）＋ スポット指名1名（伊藤）＋ 募集枠1名 が現在有効に所属
- 未登録（「メンバーを追加＋」のテスト用。当月にはTeamMembershipを持たない）:
    職員2名（高橋・田中）＋ スポット指名1名（渡辺）
    ※ 田中・渡辺は「過去月データ用」も兼ねる（過去月のみ所属していた、という過去実績を持つ。
      当月には現在有効な所属がないため、「メンバーを追加＋」からは選択可能なまま）
- 過去月（当月の1ヶ月前。過去月表示の動作確認用）:
    職員3名（佐藤・鈴木・田中）＋ スポット指名2名（伊藤・渡辺）が、その月にシフト実績を持つ
    （佐藤・鈴木・伊藤は当月から継続して所属しているため、過去月にも実績がある）
- 予定数（ShiftRequirement）:
    6月（過去月）はその日・その勤務タイプの実績数をそのまま投入（確定データ風）、
    7月（当月）は全種別・全日で一律1を投入（従来の固定値と同じ見た目）
"""
import calendar
from collections import Counter
from datetime import date, time, timedelta

from django.core.management.base import BaseCommand

from app.work_shift.models import (
    EventDefinition,
    Groupe,
    Member,
    RecruitmentSlot,
    Shift,
    ShiftRequirement,
    SpotWorker,
    Staff,
    Team,
    TeamMembership,
    WorkShiftType,
)


def _first_day_of_prev_month(d: date) -> date:
    """dが属する月の、1ヶ月前の月初日を返す簡易ヘルパー（year跨ぎにも対応）。"""
    total_months = d.year * 12 + (d.month - 1) - 1
    prev_year, prev_month0 = divmod(total_months, 12)
    return date(prev_year, prev_month0 + 1, 1)


class Command(BaseCommand):
    help = "work_shift デモデータを投入する（既存データは削除される）"

    def add_arguments(self, parser):
        parser.add_argument("--ym", type=str, default=None, help="対象年月(当月) YYYY-MM（省略時は今月）")

    def handle(self, *args, **options):
        ym = options["ym"] or date.today().strftime("%Y-%m")
        year, month = map(int, ym.split("-"))
        target_first_day = date(year, month, 1)
        _, target_num_days = calendar.monthrange(year, month)

        past_first_day = _first_day_of_prev_month(target_first_day)
        past_year, past_month = past_first_day.year, past_first_day.month
        _, past_num_days = calendar.monthrange(past_year, past_month)
        past_last_day = date(past_year, past_month, past_num_days)

        # 全削除（デモ専用）。
        # Member削除 → Shift/TeamMembershipがCASCADEで芋づる式に消える
        # （StaffやSpotWorker自体はMemberとFKで直結していない緩い参照のため、別途消す必要がある）
        Member.objects.all().delete()
        ShiftRequirement.objects.all().delete()
        Team.objects.all().delete()  # RecruitmentSlotがCASCADEで消える。Groupeより先に消す(PROTECT対応)
        Staff.objects.all().delete()
        SpotWorker.objects.all().delete()
        EventDefinition.objects.all().delete()
        WorkShiftType.objects.all().delete()
        Groupe.objects.all().delete()

        # グループ・チーム（参考画像に合わせた名前）
        groupe = Groupe.objects.create(name="介護老人保健施設 さくら")
        team = Team.objects.create(name="フロア1F", group=groupe)

        # 勤務タイプマスタ（5種。既存の色分けをそのまま初期値として使う）
        WorkShiftType.objects.bulk_create([
            WorkShiftType(
                group=groupe, name="日1",
                start_time=time(9, 0), end_time=time(18, 0), is_overnight=False,
                break_minutes=60, color="#7cb342", order=1,
            ),
            WorkShiftType(
                group=groupe, name="早1",
                start_time=time(7, 0), end_time=time(16, 0), is_overnight=False,
                break_minutes=60, color="#26c6da", order=2,
            ),
            WorkShiftType(
                group=groupe, name="遅1",
                start_time=time(11, 0), end_time=time(20, 0), is_overnight=False,
                break_minutes=60, color="#42a5f5", order=3,
            ),
            WorkShiftType(
                group=groupe, name="夜勤",
                start_time=time(18, 0), end_time=time(8, 0), is_overnight=True,
                break_minutes=60, color="#7e57c2", order=4,
            ),
            WorkShiftType(
                group=groupe, name="休",
                start_time=None, end_time=None, is_overnight=False,
                break_minutes=None, color="#ec6a8a", order=5,
            ),
        ])

        # ---- 職員（4名） ----
        # 佐藤・鈴木: 当月に現在有効に所属（継続的な所属を想定し、開始日は過去月より前にする）
        # 高橋: どのチームにも一切所属させない（「メンバーを追加＋」テスト用の純粋な未登録職員）
        # 田中: 過去月のみ所属していた実績を持つ（当月には現在有効な所属がないため、
        #       「メンバーを追加＋」からは選択可能＝未登録扱い。過去月表示の動作確認も兼ねる）
        staff_sato = Staff.objects.create(name="佐藤", default_team=team.id)
        staff_suzuki = Staff.objects.create(name="鈴木", default_team=team.id)
        staff_takahashi = Staff.objects.create(name="高橋", default_team=None)
        staff_tanaka = Staff.objects.create(name="田中", default_team=None)

        # ---- スポットワーカー（2名） ----
        # 伊藤: 当月に現在有効に所属（スポット指名。継続所属のため過去月にも実績がある）
        # 渡辺: 過去月のみ所属していた実績を持つ（田中と同様、当月には現在有効な所属がないため
        #       「メンバーを追加＋」からは選択可能＝未登録扱い）
        spot_ito = SpotWorker.objects.create(name="伊藤")
        spot_watanabe = SpotWorker.objects.create(name="渡辺")

        long_ago = past_first_day - timedelta(days=60)  # 継続所属者の開始日（十分に過去）

        order_seq = [0]

        def next_order() -> int:
            v = order_seq[0]
            order_seq[0] += 1
            return v

        # 佐藤・鈴木: 継続所属（過去月・当月とも表示対象）
        member_sato = Member.objects.create(member_kind=Member.KIND_STAFF, member_id=staff_sato.id)
        TeamMembership.objects.create(team=team, member=member_sato, start_date=long_ago, end_date=None, order=next_order())

        member_suzuki = Member.objects.create(member_kind=Member.KIND_STAFF, member_id=staff_suzuki.id)
        TeamMembership.objects.create(team=team, member=member_suzuki, start_date=long_ago, end_date=None, order=next_order())

        # 伊藤: 継続所属（過去月・当月とも表示対象）
        member_ito = Member.objects.create(member_kind=Member.KIND_SPOT_WORKER, member_id=spot_ito.id)
        TeamMembership.objects.create(team=team, member=member_ito, start_date=long_ago, end_date=None, order=next_order())

        # 田中: 過去月のみ所属（過去月中に開始・終了。当月には登場しない＝未登録扱い）
        member_tanaka = Member.objects.create(member_kind=Member.KIND_STAFF, member_id=staff_tanaka.id)
        TeamMembership.objects.create(
            team=team, member=member_tanaka, start_date=past_first_day, end_date=past_last_day, order=next_order()
        )

        # 渡辺: 過去月のみ所属（田中と同様のパターン）
        member_watanabe = Member.objects.create(member_kind=Member.KIND_SPOT_WORKER, member_id=spot_watanabe.id)
        TeamMembership.objects.create(
            team=team, member=member_watanabe, start_date=past_first_day, end_date=past_last_day, order=next_order()
        )

        # 募集枠（当月1件）
        slot = RecruitmentSlot.objects.create(team=team, year_month=ym, slot_number=1)
        member_slot = Member.objects.create(member_kind=Member.KIND_RECRUITMENT_SLOT, member_id=slot.id)
        TeamMembership.objects.create(
            team=team, member=member_slot, start_date=target_first_day, end_date=None, order=next_order()
        )

        # 繰り返しイベント定義（履歴管理の初世代として effective_from を過去に設定）
        EventDefinition.objects.bulk_create([
            EventDefinition(
                target_type="facility", title="3階入浴",
                recurrence_type="weekly", recurrence_days=["MON", "THU"],
                effective_from="2026-01",
            ),
            EventDefinition(
                target_type="facility", title="1階入浴",
                recurrence_type="weekly", recurrence_days=["TUE", "FRI"],
                effective_from="2026-01",
            ),
            EventDefinition(
                target_type="facility", title="2階入浴",
                recurrence_type="weekly", recurrence_days=["WED", "SAT"],
                effective_from="2026-01",
            ),
            EventDefinition(
                target_type="facility", title="入浴休み",
                recurrence_type="weekly", recurrence_days=["SUN"],
                effective_from="2026-01",
            ),
        ])

        # シフト実績（メンバーごとにパターンをローテーションさせて全日分を生成）
        patterns = [
            ["日1", "日1", "休", "早1", "夜勤"],
            ["夜勤", "休", "早1", "日1", "日1"],
            ["休", "夜勤", "日1", "遅1", "早1"],
        ]

        # 当月: 佐藤・鈴木・伊藤・募集枠(Spot募集1)の4名分
        target_members = [member_sato, member_suzuki, member_ito, member_slot]
        target_shifts = []
        for i, member in enumerate(target_members):
            pattern = patterns[i % len(patterns)]
            for d in range(1, target_num_days + 1):
                target_shifts.append(Shift(
                    member=member,
                    date=date(year, month, d),
                    shift_type=pattern[(d - 1) % len(pattern)],
                    team=team.id,
                    order=i,  # TeamMembership.orderのスナップショット（過去月表示用）
                ))
        Shift.objects.bulk_create(target_shifts)

        # 過去月: 佐藤・鈴木・田中(職員3名) ＋ 伊藤・渡辺(スポット2名) の5名分
        past_members = [member_sato, member_suzuki, member_tanaka, member_ito, member_watanabe]
        past_shifts = []
        for i, member in enumerate(past_members):
            pattern = patterns[i % len(patterns)]
            for d in range(1, past_num_days + 1):
                past_shifts.append(Shift(
                    member=member,
                    date=date(past_year, past_month, d),
                    shift_type=pattern[(d - 1) % len(pattern)],
                    team=team.id,
                    order=i,
                ))
        Shift.objects.bulk_create(past_shifts)

        # 予定数（ShiftRequirement）。
        # 6月（過去月）: その日・その勤務タイプのシフト実績数をそのままrequired_countとして
        #   投入する（分子=分母になり、「確定済み」の過去データらしく見える）。実績0の日も
        #   0として明示的に登録する（未入力のまま暗黙の0にはしない）。
        # 7月（当月）: 現状の固定値と同じ見た目になるよう、全種別・全日で一律1を投入する。
        work_shift_types = list(WorkShiftType.objects.filter(group=groupe).order_by("order", "id"))

        past_shift_counts = Counter((s.date, s.shift_type) for s in past_shifts)
        requirement_objs = []
        for d in range(1, past_num_days + 1):
            day = date(past_year, past_month, d)
            for wst in work_shift_types:
                requirement_objs.append(ShiftRequirement(
                    team=team, date=day, work_shift_type=wst,
                    required_count=past_shift_counts.get((day, wst.name), 0),
                ))
        for d in range(1, target_num_days + 1):
            day = date(year, month, d)
            for wst in work_shift_types:
                requirement_objs.append(ShiftRequirement(
                    team=team, date=day, work_shift_type=wst, required_count=1,
                ))
        ShiftRequirement.objects.bulk_create(requirement_objs)

        self.stdout.write(self.style.SUCCESS(
            f"投入完了: グループ1件 / チーム1件({team.id}) / 勤務タイプ5件 / "
            f"職員4件（当月所属2・未登録2） / スポットワーカー2件（当月所属1・未登録1） / "
            f"募集枠1件 / イベント定義4件 / "
            f"当月シフト{len(target_shifts)}件（{ym}） / 過去月シフト{len(past_shifts)}件"
            f"（{past_year:04d}-{past_month:02d}） / 予定数{len(requirement_objs)}件"
        ))
