import datetime
import decimal

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.core.validators import RegexValidator
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


# ═══════════════════════════════════════════════════════════════
# セル同期（ローカルのスプレッドシート ⇔ DB）
# ═══════════════════════════════════════════════════════════════

# バインディングを張れるアプリ。ここを skill_sheet に固定することで、
# 登録者（管理サイトの操作者）が auth_user 等の他アプリのテーブルを
# 同期対象に指定できないようにしている。
BINDING_ALLOWED_APP_LABEL = 'skill_sheet'

# 名称はASCIIに限定する。JSON・URL・ログを通過するたびに正規化揺れ
# （NFC/NFKC）の問題を招くため、全角は許容しない。日本語は label に置く。
BINDING_NAME_PATTERN = r'^[a-zA-Z][a-zA-Z0-9_.\-]{0,63}$'


class BindingConfigError(Exception):
    """バインディング定義そのものが壊れている（利用者の入力ではなく設定の誤り）"""


def _to_jsonable(value):
    """DBから読んだ値を JSON で返せる形へ落とす"""
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    return value


class CellBinding(models.Model):
    """
    セル同期の束縛定義。「名称」と「DB上の実体」を対応づける。

    ローカル側の設定ファイルはこの `name` しか知らない。テーブル名・フィールド名・
    レコードidがクライアントから送られてくることは無いため、任意のテーブルを
    書き換える経路が存在しない。このテーブル自体がホワイトリストとして機能する。
    """
    name = models.CharField(
        '名称', max_length=64, unique=True,
        validators=[RegexValidator(
            BINDING_NAME_PATTERN,
            message='名称は英字で始まり、英数字と _ . - のみが使えます（64文字以内）。',
        )],
        help_text='ローカル設定ファイルから参照する識別子。英数記号のみ。',
    )
    label = models.CharField('表示名', max_length=100, help_text='日本語可。画面とエラーメッセージで使う。')
    model_label = models.CharField(
        '対象モデル', max_length=100,
        help_text=f'{BINDING_ALLOWED_APP_LABEL}.PersonalInfo の形式。',
    )
    field_name = models.CharField('対象フィールド', max_length=64)
    record_id = models.IntegerField('レコードID')
    writable = models.BooleanField(
        '書き込み許可', default=False,
        help_text='push（ローカル→DB）を許可する場合のみチェック。既定は読み取り専用。',
    )
    description = models.TextField('説明', null=True, blank=True)
    created_at = models.DateTimeField('作成日時', auto_now_add=True)
    updated_at = models.DateTimeField('更新日時', auto_now=True, null=True, blank=True)

    class Meta:
        db_table = 'skill_sheet_cell_binding'
        verbose_name = 'セル同期定義'
        verbose_name_plural = 'セル同期定義'
        ordering = ['name']

    def __str__(self):
        return f"{self.name}（{self.label}）"

    # ------------------------------------------------------------------
    # 解決
    # ------------------------------------------------------------------

    def resolve_model(self):
        """model_label からモデルクラスを得る。skill_sheet 以外は拒否する。"""
        try:
            app_label, model_name = self.model_label.split('.')
        except (ValueError, AttributeError):
            raise BindingConfigError(
                f"対象モデルの書式が不正です: {self.model_label!r}"
                f"（{BINDING_ALLOWED_APP_LABEL}.PersonalInfo の形式）"
            )
        if app_label != BINDING_ALLOWED_APP_LABEL:
            raise BindingConfigError(
                f"同期対象にできるのは {BINDING_ALLOWED_APP_LABEL} アプリのモデルだけです: {self.model_label!r}"
            )
        try:
            return apps.get_model(app_label, model_name)
        except LookupError:
            raise BindingConfigError(f"対象モデルが存在しません: {self.model_label!r}")

    def resolve_field(self):
        """field_name から編集可能な具象フィールドを得る。"""
        model = self.resolve_model()
        try:
            field = model._meta.get_field(self.field_name)
        except FieldDoesNotExist:
            raise BindingConfigError(
                f"{self.model_label} にフィールド {self.field_name!r} は存在しません。"
            )
        if field.is_relation or field.primary_key or field.auto_created or not field.editable:
            raise BindingConfigError(
                f"フィールド {self.field_name!r} は同期対象にできません"
                f"（主キー・自動生成・リレーション・編集不可のいずれか）。"
            )
        return field

    def resolve_object(self):
        """対象レコードを得る。"""
        model = self.resolve_model()
        try:
            return model.objects.get(pk=self.record_id)
        except model.DoesNotExist:
            raise BindingConfigError(
                f"{self.model_label} に id={self.record_id} のレコードがありません。"
            )

    def clean(self):
        """管理サイトでの登録時に、指し先が実在することを検証する。"""
        super().clean()
        try:
            self.resolve_field()
            self.resolve_object()
        except BindingConfigError as e:
            raise ValidationError(str(e))

    # ------------------------------------------------------------------
    # 読み書き
    # ------------------------------------------------------------------

    @property
    def field_type(self):
        """フィールド型名。バインディング一覧APIで返す。解決できなければ空。"""
        try:
            return type(self.resolve_field()).__name__
        except BindingConfigError:
            return ''

    def read_value(self):
        """pull: DBの値を読む。"""
        field = self.resolve_field()
        obj = self.resolve_object()
        return _to_jsonable(getattr(obj, field.attname))

    def write_value(self, value):
        """
        push: DBへ値を書く。

        値の変換と検証は Django のフィールドに委ねる。IntegerField に "41" を
        渡しても解決され、解決できない値は ValidationError になる。
        """
        field = self.resolve_field()
        obj = self.resolve_object()
        cleaned = field.clean(value, obj)
        setattr(obj, field.attname, cleaned)

        update_fields = [field.attname]
        for f in obj._meta.fields:
            # auto_now は update_fields に含めないと更新されない
            if getattr(f, 'auto_now', False):
                update_fields.append(f.attname)
        obj.save(update_fields=update_fields)
        return _to_jsonable(cleaned)