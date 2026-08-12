"""セル同期定義の登録フォーム。"""
from django import forms
from django.apps import apps

from .models import BINDING_ALLOWED_APP_LABEL, CellBinding


def bindable_models():
    """同期対象にできるモデル。skill_sheet アプリのものだけ。"""
    models = apps.get_app_config(BINDING_ALLOWED_APP_LABEL).get_models()
    return sorted(
        (m for m in models if m is not CellBinding),
        key=lambda m: m.__name__,
    )


def bindable_fields(model):
    """
    同期対象にできるフィールド。

    主キー・自動生成・リレーション・編集不可は除く。
    CellBinding.resolve_field() と同じ条件にしてある。
    """
    return [
        f for f in model._meta.get_fields()
        if getattr(f, 'concrete', False)
        and not f.is_relation
        and not f.primary_key
        and not f.auto_created
        and f.editable
    ]


def model_label_of(model):
    return f'{model._meta.app_label}.{model.__name__}'


def model_choices():
    return [('', '---------')] + [
        (model_label_of(m), f'{m._meta.verbose_name}（{m.__name__}）')
        for m in bindable_models()
    ]


def field_choices_by_model():
    """
    {model_label: [(field_name, 表示名), ...]} を返す。

    画面側でモデルの選択に応じて絞り込むために、全モデル分をまとめて渡す。
    問い合わせを往復させるほどの規模ではない。
    """
    return {
        model_label_of(model): [
            (f.name, f'{f.verbose_name}（{f.name}）') for f in bindable_fields(model)
        ]
        for model in bindable_models()
    }


class CellBindingForm(forms.ModelForm):
    """
    同期先をドロップダウンで選ばせる。

    管理サイトでは model_label / field_name が自由入力で、既存の定義を
    コピーして直す手間が大きかった。ここでは選択式にして、存在しない
    モデル・フィールドを入力できないようにしている。
    """

    model_label = forms.ChoiceField(label='モデル名', choices=[])
    field_name = forms.ChoiceField(label='フィールド名', choices=[])

    class Meta:
        model = CellBinding
        fields = [
            'name', 'label', 'description',
            'model_label', 'field_name', 'record_id',
            'writable',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'personal_age'}),
            'label': forms.TextInput(attrs={'placeholder': '年齢'}),
            'description': forms.Textarea(attrs={'rows': 2}),
            'record_id': forms.NumberInput(attrs={'min': 1, 'step': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.field_map = field_choices_by_model()
        self.fields['model_label'].choices = model_choices()

        # field_name は全モデル分を候補として受け付ける。実際に妥当な
        # 組み合わせかどうかは CellBinding.clean() が判定する。
        # 画面側は選択されたモデルの分だけに絞り込んで表示する。
        all_fields = {
            name: text
            for choices in self.field_map.values()
            for name, text in choices
        }
        self.fields['field_name'].choices = (
            [('', '---------')] + sorted(all_fields.items())
        )
