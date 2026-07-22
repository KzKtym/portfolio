import json
from pathlib import Path
from django.contrib import messages
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.conf import settings
from . import services
from ..models import Experiment, RagProject

_PJ_BASE_DIR = Path(settings.BASE_DIR) / "data" / "rag_tr_tool"


def _init_project_dirs(project_id: int) -> None:
    """新規プロジェクトのディレクトリ構成と空ファイルを作成する。"""
    pj_dir = _PJ_BASE_DIR / f"pj_{project_id}"
    for sub in ["index", "log", "raw"]:
        (pj_dir / sub).mkdir(parents=True, exist_ok=True)
    queries_path = pj_dir / "evaluation_queries.json"
    if not queries_path.exists():
        queries_path.write_text("[]", encoding="utf-8")


def project_list(request):
    """プロジェクト管理画面（GET: 一覧表示 / POST: 新規作成）"""
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        short_name = request.POST.get("short_name", "").strip()
        description = request.POST.get("description", "").strip()
        if name and short_name:
            project = RagProject.objects.create(name=name, short_name=short_name, description=description)
            _init_project_dirs(project.id)
        return redirect("project_list")

    projects = RagProject.objects.all().order_by("id")
    descriptions_json = json.dumps({str(p.id): p.description for p in projects})
    return render(request, "rag_tr_tool/projects.html", {
        "projects": projects,
        "descriptions_json": descriptions_json,
    })


def project_edit(request, project_id):
    """Ajax POST: プロジェクト編集"""
    if request.method == "POST":
        data = json.loads(request.body)
        RagProject.objects.filter(id=project_id).update(
            name=data.get("name", ""),
            short_name=data.get("short_name", ""),
            description=data.get("description", ""),
        )
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": "error"}, status=405)


def project_delete(request, project_id):
    """Ajax POST: プロジェクト削除（紐づく実験をカスケード削除）"""
    if request.method == "POST":
        try:
            RagProject.objects.get(id=project_id).delete()
            return JsonResponse({"status": "ok"})
        except RagProject.DoesNotExist:
            return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse({"status": "error"}, status=405)


def new_experiment_view(request, project_id):
    data = services.get_new_experiment_context(request.GET.get("params"), project_id=project_id)
    data["project_id"] = project_id
    return render(request, "rag_tr_tool/new.html", data)


def check_index(request):
    """Ajax: 送信パラメータに対応するIndexの有無・情報を返す"""
    if request.method == "POST":
        params = json.loads(request.body)
        return JsonResponse(services.get_index_check(params))
    return JsonResponse({"exists": False})


def run_experiment(request, project_id):
    # POST以外（GET等で直接叩かれた場合）は新規画面へ戻す
    if request.method != "POST":
        return redirect("new_experiment", project_id=project_id)

    # パラメータ未設定の送信は実行しない（フロントJSを経由しない異常経路の防御）。
    # 正規の実行は finalParams(name="parameters") にJSONが入る。Enterによる暗黙送信
    # などでJSが走らなかった場合はここが空となり、実行に進まないようにする。
    try:
        raw_dict = json.loads(request.POST.get("parameters", "{}"))
    except json.JSONDecodeError:
        raw_dict = {}
    if not raw_dict:
        return redirect("new_experiment", project_id=project_id)

    name = request.POST.get("name")
    rebuild = request.POST.get("rebuild_index") == "1"
    data = services.run_experiment_service(name, raw_dict, rebuild, project_id)
    if not data.get("ok"):
        # 失敗時は実験レコードを作らないため、結果画面ではなく入力画面へ戻す
        messages.error(
            request,
            f"実験の実行に失敗しました（{data.get('error_type', 'Unknown')}）: {data.get('error', '')}",
        )
        return redirect("new_experiment", project_id=project_id)
    return render(request, "rag_tr_tool/result.html", data)


def experiment_list(request, project_id):
    experiments = services.get_experiment_list(project_id)
    return render(request, "rag_tr_tool/list.html", {
        "experiments": experiments,
        "project_id": project_id,
    })


def delete_experiments(request):
    if request.method == "POST":
        ids = request.POST.get("ids", "")
        project_id = request.POST.get("project_id", "")
        id_list = [i for i in ids.split(",") if i]
        if id_list:
            services.delete_experiments_service(id_list)
        if project_id:
            return redirect("experiment_list", project_id=project_id)
    return redirect("project_list")


def toggle_star(request, exp_id):
    """Ajax: is_starred を反転して返す"""
    if request.method == "POST":
        try:
            exp = Experiment.objects.get(id=exp_id)
            exp.is_starred = not exp.is_starred
            exp.save(update_fields=["is_starred"])
            return JsonResponse({"starred": exp.is_starred})
        except Experiment.DoesNotExist:
            return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse({"error": "method not allowed"}, status=405)


def compare_view(request):
    ids = request.GET.getlist("ids")
    if len(ids) != 2:
        return redirect("project_list")
    data = services.build_compare_data(int(ids[0]), int(ids[1]))
    return render(request, "rag_tr_tool/compare.html", data)


def update_name(request, exp_id):
    if request.method == "POST":
        data = json.loads(request.body)
        Experiment.objects.filter(id=exp_id).update(name=data.get("name", ""))
        return JsonResponse({"status": "ok"})
    return JsonResponse({"status": "error"})


def result_view(request, exp_id):
    data = services.get_result_data(exp_id)
    return render(request, "rag_tr_tool/result.html", data)