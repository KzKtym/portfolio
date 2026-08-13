"""
セル同期定義（CellBinding）の管理画面。

管理サイトでも登録はできるが、同期先の指定が自由入力で、定義を1件ずつ
コピーして直す手間が大きかった。ここではモデル名・フィールド名を選択式にし、
画面下部にローカル設定ファイルの雛形を出す。

削除は管理サイトに任せる。
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from app.common.permissions import is_superuser

from .forms import CellBindingForm, field_choices_by_model
from .models import CellBinding
from .utils import load_config, resolve_secret

# 設定サンプルの固定部分。利用者が必ず書き換える箇所なので、
# それと分かる値を入れておく。
SAMPLE_BOOK_PATH = 'C:/xxx.xlsx'
SAMPLE_DIRECTION = 'pull'
SAMPLE_SAVE_AFTER_PULL = False


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def build_sample_config(request):
    """
    ローカル設定ファイルの雛形を JSON 文字列で返す。

    ペアは登録の新しい順（id 降順）。sheet / cell は利用者がブックを見ながら
    埋める箇所なので空にしておく。

    json.dumps(indent=2) だとペアが4行に分かれて件数が増えるほど読みにくく
    なるため、ペアだけ1行に収まるよう組み立てている。
    """
    names = list(CellBinding.objects.order_by('-id').values_list('name', flat=True))

    config = load_config()
    api_password = resolve_secret(config.get('api_password', ''))
    if not api_password:
        # 解決できないときは設定値そのものを出す。どこを直せばよいか分かる。
        api_password = config.get('api_password', '')

    if names:
        pairs = ',\n'.join(
            f'        {{ "name": {_json(name)}, "sheet": "", "cell": "" }}'
            for name in names
        )
        pairs_block = f'[\n{pairs}\n      ]'
    else:
        pairs_block = '[]'

    endpoint = request.build_absolute_uri(reverse('skill_sheet:api_cells'))

    return (
        '{\n'
        f'  "endpoint": {_json(endpoint)},\n'
        f'  "api_password": {_json(api_password)},\n'
        '  "books": [\n'
        '    {\n'
        f'      "path": {_json(SAMPLE_BOOK_PATH)},\n'
        f'      "direction": {_json(SAMPLE_DIRECTION)},\n'
        f'      "save_after_pull": {_json(SAMPLE_SAVE_AFTER_PULL)},\n'
        f'      "pairs": {pairs_block}\n'
        '    }\n'
        '  ]\n'
        '}'
    )


@user_passes_test(is_superuser)
def binding_list(request):
    """定義の一覧と、設定ファイルの雛形。"""
    context = {
        'bindings': CellBinding.objects.order_by('-id'),
        'sample_config': build_sample_config(request),
    }
    return render(request, 'skill_sheet/binding_list.html', context)


@user_passes_test(is_superuser)
def binding_create(request):
    return _edit(request, instance=None)


@user_passes_test(is_superuser)
def binding_edit(request, pk):
    return _edit(request, instance=get_object_or_404(CellBinding, pk=pk))


def _edit(request, instance):
    if request.method == 'POST':
        form = CellBindingForm(request.POST, instance=instance)
        if form.is_valid():
            binding = form.save()
            messages.success(request, f'「{binding.label}」を保存しました。')
            return redirect('skill_sheet:binding_list')
    else:
        form = CellBindingForm(instance=instance)

    context = {
        'form': form,
        'binding': instance,
        'is_new': instance is None,
        'basic_fields': [form['name'], form['label'], form['description']],
        'target_fields': [form['model_label'], form['field_name'], form['record_id']],
        'permission_fields': [form['writable']],
        # モデルの選択に応じてフィールドの候補を絞り込むため、画面へ渡す。
        # テンプレート側は json_script で埋め込む。
        'field_map': {
            model_label: [{'value': name, 'text': text} for name, text in choices]
            for model_label, choices in field_choices_by_model().items()
        },
    }
    return render(request, 'skill_sheet/binding_form.html', context)
