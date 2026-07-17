"""views_api.py - Ajax系ビュー（generate_answers / rwa_view / log_text / download_log）"""
import json
from django.http import JsonResponse, FileResponse, HttpResponse, Http404

from .models import Experiment
from . import services
from app.rag_tr_tool.utils.log_formatter import format_log_form1, format_log_form2, read_details_json, get_logs_dir
from app.rag_tr_tool.utils.rewrite_store import read_rwa_json


def log_text(request, exp_id):
    """Ajax: 書式1または書式2のプレーンテキストを返す"""
    fmt = request.GET.get("fmt", "1")
    try:
        exp = Experiment.objects.get(id=exp_id)
        project_id = exp.project_id
    except Experiment.DoesNotExist:
        project_id = None
    saved = read_details_json(exp_id, project_id=project_id)
    if not saved:
        from django.http import HttpResponseNotFound
        return HttpResponseNotFound("No log data")
    details = saved.get("details", [])
    meta = saved.get("meta", {})
    kwargs = dict(
        details=details,
        total_chunks=meta.get("total_chunks", 0),
        index_creation_time=meta.get("index_creation_time"),
        evaluation_time_sec=meta.get("evaluation_time_sec", 0),
        query_count=meta.get("query_count", 0),
        mrr=0.0,
        recall_at_5=0.0,
    )
    try:
        kwargs["mrr"] = exp.mrr
        kwargs["recall_at_5"] = exp.recall_at_5
    except Exception:
        pass

    text = format_log_form1(**kwargs) if fmt == "1" else format_log_form2(**kwargs)
    return HttpResponse(text, content_type="text/plain; charset=utf-8")


def download_log(request, exp_id):
    try:
        exp = Experiment.objects.get(id=exp_id)
        log_path = get_logs_dir(exp.project_id) / f"exp_{exp_id}.log"
    except Experiment.DoesNotExist:
        raise Http404
    if not log_path.exists():
        raise Http404
    return FileResponse(open(log_path, "rb"), as_attachment=True, filename=f"exp_{exp_id}.log")


def generate_answers(request, exp_id):
    """Ajax POST: 実験のdetailsを再検索し、LLMで回答生成してファイル保存・返却する"""
    if request.method != "POST":
        return JsonResponse({"error": "method not allowed"}, status=405)

    try:
        result = services.generate_answers_service(exp_id)
    except Experiment.DoesNotExist:
        return JsonResponse({"error": "experiment not found"}, status=404)
    except Exception as e:
        return JsonResponse({"error": f"インデックスのロードに失敗しました: {e}"}, status=500)

    if "status" in result:
        return JsonResponse(
            {"error": result["error"], "answers": result["answers"]},
            status=result["status"],
        )
    return JsonResponse({"answers": result["answers"]})


def rwa_view(request):
    """Ajax GET: 2実験のrwaデータを取得して返す"""
    id_a = request.GET.get("id_a")
    id_b = request.GET.get("id_b")
    if not id_a or not id_b:
        return JsonResponse({"error": "id_a・id_b が必要です"}, status=400)

    def _get_exp_info(exp_id):
        try:
            exp = Experiment.objects.get(id=exp_id)
            qr = exp.parameters.get("query_rewrite", False)
            if isinstance(qr, str):
                qr = qr.lower() == "true"
            return {"id": exp_id, "qr": qr, "qr_label": str(qr).lower(), "project_id": exp.project_id}
        except Experiment.DoesNotExist:
            return {"id": exp_id, "qr": False, "qr_label": "?", "project_id": 1}

    info_a = _get_exp_info(int(id_a))
    info_b = _get_exp_info(int(id_b))

    # false側を左・true側を右に並べ替え。両方同じ値の場合はID昇順
    if info_a["qr"] == info_b["qr"]:
        if info_a["id"] > info_b["id"]:
            info_a, info_b = info_b, info_a
    elif info_a["qr"]:
        info_a, info_b = info_b, info_a

    rwa_left = read_rwa_json(info_a["id"], project_id=info_a["project_id"])
    rwa_right = read_rwa_json(info_b["id"], project_id=info_b["project_id"])

    return JsonResponse({
        "rwa_a": rwa_left or [],
        "rwa_b": rwa_right or [],
        "has_rwa_a": rwa_left is not None,
        "has_rwa_b": rwa_right is not None,
        "label_a": f"{info_a['id']}:{info_a['qr_label']}",
        "label_b": f"{info_b['id']}:{info_b['qr_label']}",
    })