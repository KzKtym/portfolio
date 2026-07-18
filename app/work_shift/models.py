# app/work_shift/models.py
from django.db import models


class Groupe(models.Model):
    """施設グループ（例: 介護老人保健施設 さくら）"""
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "wsft_groupe"

    def __str__(self):
        return self.name


class WorkShiftType(models.Model):
    """
    勤務タイプマスタ（グループ単位で管理。例: 日1・早1・遅1・夜勤・休）。

    「休」のように実働時間を持たない種別も許容するため、start_time/end_time/break_minutesは
    いずれもNULL可とする。is_overnightは「翌」チェックボックスに対応し、Trueの場合は
    end_timeを翌日の時刻として扱う（例: 開始18:00・終了08:00・is_overnight=True →
    「18:00～翌08:00」）。

    シフト保存時（Shift.shift_type）は、この名称と一致するかをAPI側でチェックする
    （wsft_shiftsの型自体はマスタ変更の影響を受けない従来通りの自由文字列のまま。
    名称一致チェックのみ追加する運用）。
    """
    group = models.ForeignKey(
        Groupe,
        on_delete=models.CASCADE,
        related_name="work_shift_types",
    )
    name = models.CharField(max_length=20)
    start_time = models.TimeField(null=True, blank=True)
    is_overnight = models.BooleanField(default=False)  # 終了時刻が翌日扱いかどうか（「翌」チェック）
    end_time = models.TimeField(null=True, blank=True)
    break_minutes = models.IntegerField(null=True, blank=True)
    color = models.CharField(max_length=7)  # 例: "#7cb342"
    order = models.IntegerField(default=0)  # 並び順（一覧・日付クリックのパネル・下部集計行で使用）

    class Meta:
        db_table = "wsft_work_shift_types"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.name} ({self.group.name})"


class ShiftRequirement(models.Model):
    """
    予定数（勤務タイプ×日付ごとの必要人数）。「小計」行の分母として、
    通常タブ(F1)・予定数タブ(F2)の双方から同じデータを参照する（確定仕様）。
    未保存の行が存在しない日は0人（未入力）として扱う。
    """
    team = models.ForeignKey("Team", on_delete=models.CASCADE, related_name="shift_requirements")
    date = models.DateField()
    work_shift_type = models.ForeignKey(WorkShiftType, on_delete=models.CASCADE, related_name="requirements")
    required_count = models.IntegerField(default=0)

    class Meta:
        db_table = "wsft_shift_requirements"
        unique_together = [("team", "date", "work_shift_type")]

    def __str__(self):
        return f"team={self.team_id} / {self.date} / {self.work_shift_type.name}={self.required_count}"


class Team(models.Model):
    """
    チーム。

    組織上の所属ではなく、「フロア1F」のような場所ラベルとして扱う。
    シフト作成画面は「チーム＋年月」で一意なシートとして表示される。
    """
    name = models.CharField(max_length=100)
    group = models.ForeignKey(
        Groupe,
        on_delete=models.PROTECT,  # Groupeを消すには先にTeamを削除する必要がある
        related_name="teams",
    )

    class Meta:
        db_table = "wsft_teams"

    def __str__(self):
        return self.name


class Staff(models.Model):
    """
    職員。

    表示名は `{name} 職員{n}` の形式で組み立てる（nはチームごとに動的採番。詳細はMember/
    TeamMembershipの節、およびFastAPI側の採番ロジックを参照）。ここでの `name` は素の氏名のみ。
    """
    name = models.CharField(max_length=100)
    default_team = models.IntegerField(null=True, blank=True)  # テストデータ作成時の参考値。FK制約なし

    class Meta:
        db_table = "wsft_staffs"

    def __str__(self):
        return self.name


class SpotWorker(models.Model):
    """スポットワーカー。職員(Staff)とは明確に別モデルで管理する。項目は名前のみ。"""
    name = models.CharField(max_length=100)

    class Meta:
        db_table = "wsft_spot_worker"

    def __str__(self):
        return self.name


class RecruitmentSlot(models.Model):
    """
    「スポット（募集）」の枠。実在の人物ではなく、まだ誰も割り当たっていない募集枠を表す。
    表示名は `Spot募集{slot_number}` として組み立てる（幅を抑えるための表記。旧表記は
    `スポット（募集）{slot_number}`）。
    通常の職員・スポットワーカーと同様にシフト種別の入力・保存対象になる（仮の人物として扱う）。
    """
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="recruitment_slots")
    year_month = models.CharField(max_length=7)  # "YYYY-MM"。この枠が作られた月
    slot_number = models.IntegerField()  # チーム＋年月内での連番

    class Meta:
        db_table = "wsft_recruitment_slot"
        unique_together = ("team", "year_month", "slot_number")

    def __str__(self):
        return f"Spot募集{self.slot_number} ({self.team.name}/{self.year_month})"


class Member(models.Model):
    """
    「誰か」を指す汎用識別子。Staff/SpotWorker/RecruitmentSlotのいずれか1つを、
    種別(member_kind)とID(member_id)の組で指す（DBレベルのFKは張らない。種別によって
    参照先テーブルが変わるため）。ShiftやTeamMembershipは、Staff等を直接参照せず、
    必ずこのMember経由で「誰か」を扱う。
    """
    KIND_STAFF = 0
    KIND_SPOT_WORKER = 1
    KIND_RECRUITMENT_SLOT = 2
    KIND_CHOICES = [
        (KIND_STAFF, "職員"),
        (KIND_SPOT_WORKER, "スポットワーカー"),
        (KIND_RECRUITMENT_SLOT, "募集枠"),
    ]

    member_kind = models.IntegerField(choices=KIND_CHOICES)
    member_id = models.IntegerField()  # member_kindに応じて Staff.id / SpotWorker.id / RecruitmentSlot.id を指す

    class Meta:
        db_table = "wsft_member"
        unique_together = ("member_kind", "member_id")

    def __str__(self):
        return f"Member(kind={self.member_kind}, id={self.member_id})"


class TeamMembership(models.Model):
    """
    チームへの所属期間。**このチームのシートに表示するかどうかだけを制御する**。
    シフトの実データ（Shift）が何を記録するかとは無関係（Shiftは`member`経由でMemberを直接参照し、
    TeamMembershipを経由しない。所属期間の編集・削除が過去のシフト実績に影響しないようにするため）。

    「メンバーを追加＋」のいずれのタブ（職員/スポット指名/スポット募集）から追加した場合も、
    追加した瞬間に `start_date=当日, end_date=NULL(無期限)` でこのレコードが作られる。
    以後はシフト入力の有無に関わらず、対象月と期間が重なっている限り表示され続ける。

    `is_deleted`: 「×」ボタン押下による論理削除フラグ。`start_date`/`end_date`（実際の所属期間の
    事実）とは別軸の、表示上の一時的な削除フラグ。Trueの行はシートに表示されない。
    Shiftレコードには一切影響しない（Shift自体はこのTeamMembershipを経由して参照されないため）。
    復元はis_deletedをFalseに戻す操作だが、専用UIは今回のスコープ外（所属管理画面での対応予定）。
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="team_memberships")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)  # NULL = 無期限
    is_deleted = models.BooleanField(default=False)
    # チーム内の並び順（＝ドラッグ）。旧TeamMemberOrderを廃止しこちらへ統合した。
    # 「メンバーを追加＋」時は、その時点の最大orderの次の値（＝末尾）を自動採番する。
    # 過去月の表示順には使わない（Shift.orderを参照する。3.9節・9節の「月確定」課題を参照）。
    order = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "wsft_team_membership"

    def __str__(self):
        return f"{self.team.name} / member={self.member_id} / {self.start_date}〜{self.end_date or ''}"


class EventDefinition(models.Model):
    """
    繰り返しイベント定義（履歴管理版）。

    ルールの「編集」は既存行を直接UPDATEせず、以下の2ステップで行う運用とする。
      1. 既存行の effective_until に「変更を適用する年月」をセットして世代を閉じる
      2. 新しい内容の行を effective_from = 変更を適用する年月 で新規作成する

    削除も物理削除ではなく、effective_until に「削除を反映する年月」をセットする論理削除とする。
    """

    TARGET_TYPE_CHOICES = [
        ("facility", "施設"),
        ("team", "チーム"),
    ]
    RECURRENCE_TYPE_CHOICES = [
        ("weekly", "毎週"),
        ("monthly", "毎月"),
    ]

    target_type = models.CharField(max_length=10, choices=TARGET_TYPE_CHOICES)
    target_id = models.IntegerField(null=True, blank=True)

    title = models.CharField(max_length=100)
    recurrence_type = models.CharField(max_length=10, choices=RECURRENCE_TYPE_CHOICES)
    recurrence_days = models.JSONField(default=list)

    effective_from = models.CharField(max_length=7)   # "YYYY-MM"
    effective_until = models.CharField(max_length=7, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wsft_event_definitions"
        indexes = [
            models.Index(fields=["target_type", "effective_from"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.recurrence_type} / {self.effective_from}〜{self.effective_until or ''})"


class Shift(models.Model):
    """
    個別シフト実績。

    `member` は「誰のシフトか」をMember経由で指す（Staff/SpotWorker/RecruitmentSlotのいずれか）。
    `team` は「このシフトが、どのチーム（場所）のシートで記録されたか」を示す履歴的な値であり、
    あえてFKにしない。保存API呼び出し1回＝1チーム・1月という業務制約に合わせて書き込み時に設定する。

    `deleted_at`: 従来は「メンバーを削除(×)」操作の論理削除フラグとして使っていたが、
    「×」の挙動をTeamMembership.is_deletedへ移管したため、現在能動的にセットする操作は
    存在しない（将来的な用途のため列自体は残してある。値は基本的に常にNULLとなる）。
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="shifts")
    date = models.DateField()
    shift_type = models.CharField(max_length=20)  # 例: '早1', '夜勤', '休'
    team = models.IntegerField()  # Team.id を指すが、FK制約は持たない
    deleted_at = models.DateTimeField(null=True, blank=True)
    # 保存時点でのTeamMembership.orderのスナップショット。過去月（対象年月 < 今月）を表示する際、
    # マスターの現在の並び順ではなく、この凍結された値を使って並び替える（9節の設計原則:
    # 「過去分はメンバーも並び順もマスターの変更の影響を受けない」に対応するため）。
    order = models.IntegerField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wsft_shifts"
        unique_together = ("member", "date")

    def __str__(self):
        return f"member={self.member_id} / {self.date} / {self.shift_type} (team={self.team})"
