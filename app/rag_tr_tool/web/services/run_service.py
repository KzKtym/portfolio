"""run_service.py - 実験実行（評価・DB保存・ログ保存・rewriteデータ保存）"""
import json
from urllib.parse import quote

from ..models import Experiment
from app.rag_tr_tool.core.evaluation import run_evaluation, save_log, save_details_json, EvalParams
from app.rag_tr_tool.utils.spec_extractor import resolve_spec
from app.rag_tr_tool.utils.log_formatter import format_log_full
from app.rag_tr_tool.utils.rewrite_store import save_rwa_json, calc_rewrite_data


def run_experiment_service(name: str, raw_dict: dict, rebuild: bool, project_id: int) -> dict:
    """実験を実行し、DB保存・ログ保存・rewriteデータ保存を行い結果dictを返す。

    Returns:
        {
            "exp": Experiment,
            "exp_params_urlenc": str,
            "exp_params_json": str,
            "prev_exp": Experiment | None,
            "message": str,
            "details": list,
            "meta": dict,
            "has_log": bool,
            "answers": list,
            "has_answers": bool,
            "rewrite_data": list,
            "has_rewrite_data": bool,
            "rewrite_summary": dict | None,
        }
    """
    normalized_params = EvalParams.normalize(raw_dict)
    result = run_evaluation(normalized_params, rebuild=rebuild, project_id=project_id)
    spec_text = resolve_spec(normalized_params)

    metrics = result.get("metrics", {})
    current_exp = Experiment.objects.create(
        name=name,
        mrr=metrics.get("mrr", 0.0),
        recall_at_5=metrics.get("recall_at_5", 0.0),
        parameters=normalized_params,
        spec_snapshot=spec_text,
        project_id=project_id,
    )

    prev_exp = (
        Experiment.objects.filter(created_at__lt=current_exp.created_at)
        .order_by("-created_at")
        .first()
    )

    meta = result.get("meta", {})
    has_log = result.get("status") == "success"
    if has_log:
        log_text = format_log_full(
            details=result.get("details", []),
            total_chunks=meta.get("total_chunks", 0),
            index_creation_time=meta.get("index_creation_time"),
            evaluation_time_sec=meta.get("evaluation_time_sec", 0),
            query_count=meta.get("query_count", 0),
            mrr=metrics.get("mrr", 0.0),
            recall_at_5=metrics.get("recall_at_5", 0.0),
        )
        save_log(current_exp.id, log_text, project_id=project_id)
        save_details_json(current_exp.id, result.get("details", []), meta, project_id=project_id)

    rwa_queries = result.get("rwa_queries", [])
    if rwa_queries:
        save_rwa_json(current_exp.id, rwa_queries, project_id=project_id)

    rewrite_data = rwa_queries or []
    rewrite_summary = None
    if rewrite_data:
        rewrite_data, rewrite_summary = calc_rewrite_data(rewrite_data)

    return {
        "exp": current_exp,
        "exp_params_urlenc": quote(json.dumps(current_exp.parameters, ensure_ascii=False)),
        "exp_params_json": json.dumps(current_exp.parameters, ensure_ascii=False),
        "prev_exp": prev_exp,
        "message": "実行完了（保存OK）",
        "details": result.get("details", []),
        "meta": meta,
        "has_log": has_log,
        "answers": [],
        "has_answers": False,
        "rewrite_data": rewrite_data,
        "has_rewrite_data": bool(rewrite_data),
        "rewrite_summary": rewrite_summary,
    }