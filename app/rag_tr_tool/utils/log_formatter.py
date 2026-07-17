import json
from pathlib import Path

from django.conf import settings

_DATA_DIR = Path(settings.BASE_DIR) / "data" / "rag_tr_tool"


def get_logs_dir(project_id: int) -> Path:
    """プロジェクトIDからログディレクトリパスを返す。"""
    return _DATA_DIR / f"pj_{project_id}" / "logs"


def read_log(exp_id: int, project_id: int) -> str | None:
    """ログファイルを読み込んで返す。なければNone"""
    logs_dir = get_logs_dir(project_id)
    log_path = logs_dir / f"exp_{exp_id}.log"
    if log_path.exists():
        return log_path.read_text(encoding="utf-8")
    return None


def read_details_json(exp_id: int, project_id: int) -> dict | None:
    """details JSONを読み込んで返す。なければNone"""
    logs_dir = get_logs_dir(project_id)
    json_path = logs_dir / f"exp_{exp_id}.json"
    if json_path.exists():
        return json.loads(json_path.read_text(encoding="utf-8"))
    return None


def format_log_form1(details: list, total_chunks: int, index_creation_time: str | None,
                     evaluation_time_sec: float, query_count: int,
                     mrr: float, recall_at_5: float) -> str:
    """書式１（表形式）ログテキストを生成"""
    lines = []
    if index_creation_time:
        lines.append(f"Index creation time : {index_creation_time}")
    lines.append(f"Total chunks : {total_chunks}")
    lines.append(f"MRR : {mrr}  Recall@5 : {recall_at_5}  ({query_count} queries / {evaluation_time_sec}s)")
    lines.append("")
    for i, d in enumerate(details, 1):
        # mrrキーがない過去データはcorrect_rankからフォールバック計算
        q_mrr = d.get("mrr")
        if q_mrr is None:
            cr = d.get("correct_rank")
            q_mrr = round(1.0 / cr, 4) if cr else 0.0
        lines.append(f"Query {i}: {d['query']}")
        lines.append(f"Correct No: {d['correct_rank'] if d['correct_rank'] else '-'}  MRR: {q_mrr:.4f}")
        lines.append(f"{'rank':<6}{'score':<9}source")
        for r in d["results"]:
            lines.append(f"{r['rank']:<6}{r['score']:<9}{r['source']}")
        lines.append("")
    return "\n".join(lines)


def format_log_form2(details: list, total_chunks: int, index_creation_time: str | None,
                     evaluation_time_sec: float, query_count: int,
                     mrr: float, recall_at_5: float) -> str:
    """書式２（text追加形式）ログテキストを生成"""
    lines = []
    if index_creation_time:
        lines.append(f"Index creation time : {index_creation_time}")
    lines.append(f"Total chunks : {total_chunks}")
    lines.append(f"MRR : {mrr}  Recall@5 : {recall_at_5}  ({query_count} queries / {evaluation_time_sec}s)")
    lines.append("")
    for i, d in enumerate(details, 1):
        # mrrキーがない過去データはcorrect_rankからフォールバック計算
        q_mrr = d.get("mrr")
        if q_mrr is None:
            cr = d.get("correct_rank")
            q_mrr = round(1.0 / cr, 4) if cr else 0.0
        lines.append(f"Query {i}: {d['query']}")
        lines.append(f"Correct No: {d['correct_rank'] if d['correct_rank'] else '-'}  MRR: {q_mrr:.4f}")
        lines.append("")
        for r in d["results"]:
            lines.append(f"--- Rank {r['rank']} ---")
            lines.append(f"Score: {r['score']}")
            lines.append(f"Source: {r['source']}")
            lines.append(f"Text:\n{r.get('text', '')}")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def format_log_full(details: list, total_chunks: int, index_creation_time: str | None,
                    evaluation_time_sec: float, query_count: int,
                    mrr: float, recall_at_5: float) -> str:
    """書式１と書式２を両方含むログテキストを生成（.logファイル保存用）"""
    sep1 = "=" * 40 + " FORMAT 1 (Table) " + "=" * 40
    sep2 = "=" * 40 + " FORMAT 2 (With Text) " + "=" * 40
    kwargs = dict(
        details=details,
        total_chunks=total_chunks,
        index_creation_time=index_creation_time,
        evaluation_time_sec=evaluation_time_sec,
        query_count=query_count,
        mrr=mrr,
        recall_at_5=recall_at_5,
    )
    return "\n".join([
        sep1, "",
        format_log_form1(**kwargs),
        sep2, "",
        format_log_form2(**kwargs),
    ])