"""rewrite_store.py - Rewrite/Multi Query Analysisデータの保存・読み込み・集計"""
from pathlib import Path
import json

from app.rag_tr_tool.utils.log_formatter import get_logs_dir


def save_rwa_json(exp_id: int, queries: list, project_id: int) -> Path:
    logs_dir = get_logs_dir(project_id)
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"exp_{exp_id}_rewrite.json"
    path.write_text(json.dumps(queries, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_rwa_json(exp_id: int, project_id: int) -> list | None:
    logs_dir = get_logs_dir(project_id)
    path = logs_dir / f"exp_{exp_id}_rewrite.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    # 旧形式 {"queries": [...]} と新形式 [...] の両方に対応
    if isinstance(data, dict):
        return data.get("queries", [])
    return data


def calc_rewrite_data(rewrite_data: list) -> tuple[list, dict]:
    """rewrite_dataにis_new/rank/delta/gainフラグを付与し、summaryを返す。
    true/multiどちらのmodeにも対応。
    """
    improved = degraded = unchanged = gain = 0
    for q in rewrite_data:
        delta = q["mrr_rewrite"] - q["mrr_original"]
        if delta > 0:
            improved += 1
        elif delta < 0:
            degraded += 1
        else:
            unchanged += 1
        orig_sources = {r["source"] for r in q["results_original"]}
        for r in q["results_rewrite"]:
            r["is_new"] = r["source"] not in orig_sources
            if r["is_new"]:
                gain += 1
        relevant = set(q.get("relevant_sources", []))
        q["original_rank"] = next(
            (r["rank"] for r in q["results_original"] if r["source"] in relevant), None
        )
        q["rewrite_rank"] = next(
            (r["rank"] for r in q["results_rewrite"] if r["source"] in relevant), None
        )
        q["mrr_delta"] = round(q["mrr_rewrite"] - q["mrr_original"], 4)
        q["rewrite_gain"] = q["mrr_delta"] > 0
    summary = {"improved": improved, "degraded": degraded, "unchanged": unchanged, "gain": gain}
    return rewrite_data, summary