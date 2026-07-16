from django.db import models


class PersonalInfo(models.Model):
    """パーソナル情報"""
    registration_no = models.CharField('登録No', max_length=10, null=True, blank=True)
    age = models.IntegerField('年齢')
    gender = models.CharField('性別', max_length=1, null=True, blank=True, choices=[
        ('M', '男性'),
        ('F', '女性'),
        ('X', 'その他'),
    ])
    education = models.CharField('学歴', max_length=40)
    qualification = models.CharField('資格', max_length=100, null=True, blank=True)
    availability = models.CharField('稼動', max_length=40, null=True, blank=True)
    affiliation = models.CharField('所属', max_length=100, null=True, blank=True)
    nearest_station = models.CharField('最寄駅', max_length=40)
    specialty_field = models.CharField('得意分野', max_length=200, null=True, blank=True)
    specialty_tech = models.CharField('得意技術', max_length=200, null=True, blank=True)
    specialty_business = models.CharField('得意業務', max_length=200, null=True, blank=True)
    self_pr = models.TextField('自己PR', null=True, blank=True)
    created_at = models.DateTimeField('作成日時', auto_now_add=True)
    updated_at = models.DateTimeField('更新日時', auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'skill_sheet_personal'
        verbose_name = 'パーソナル情報'
        verbose_name_plural = 'パーソナル情報'

    def __str__(self):
        return f"ID:{self.id} - {self.registration_no or 'デフォルト'}"


class SkillSheetData(models.Model):
    """スキルシート詳細"""
    personal = models.ForeignKey(
        PersonalInfo,
        on_delete=models.CASCADE,
        related_name='skill_sheets',
        verbose_name='パーソナルID'
    )
    project_name = models.CharField('案件名', max_length=200)
    content = models.TextField('内容')
    remote = models.BooleanField('リモート', default=False)
    work_style = models.CharField('業務形態', max_length=20, null=True, blank=True)
    start_month = models.CharField('開始年月', max_length=6)
    end_month = models.CharField('終了年月', max_length=6)
    duration = models.IntegerField('期間')
    lang = models.CharField('Lang', max_length=200, null=True, blank=True)
    db = models.CharField('DB', max_length=200, null=True, blank=True)
    os = models.CharField('OS', max_length=200, null=True, blank=True)
    tools = models.CharField('Tools', max_length=200, null=True, blank=True)
    scope = models.CharField('担当工程', max_length=400, null=True, blank=True)
    process1 = models.BooleanField('Process1', default=False)
    process2 = models.BooleanField('Process2', default=False)
    process3 = models.BooleanField('Process3', default=False)
    process4 = models.BooleanField('Process4', default=False)
    process5 = models.BooleanField('Process5', default=False)
    process6 = models.BooleanField('Process6', default=False)
    process7 = models.BooleanField('Process7', default=False)
    person1 = models.IntegerField('Person1', default=0)
    person2 = models.IntegerField('Person2', default=0)
    person3 = models.IntegerField('Person3', default=0)
    remarks = models.TextField('備考', null=True, blank=True)
    created_at = models.DateTimeField('作成日時', auto_now_add=True)
    updated_at = models.DateTimeField('更新日時', auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'skill_sheet_data'
        verbose_name = 'スキルシート詳細'
        verbose_name_plural = 'スキルシート詳細'
        ordering = ['-start_month']

    def __str__(self):
        return f"{self.project_name} ({self.start_month}-{self.end_month})"