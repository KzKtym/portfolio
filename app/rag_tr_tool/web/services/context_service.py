"""context_services.py - 画面コンテキスト生成（new / list / result 画面用）"""
import json
from pathlib import Path
from urllib.parse import quote

from django.conf import settings

from ...models import Experiment, RagProject
from app.rag_tr_tool.core.evaluation import EvalParams
from app.rag_tr_tool.core.indexing.index_builder import get_index_info
from app.rag_tr_tool.utils.spec_extractor import resolve_spec
from app.rag_tr_tool.utils.log_formatter import read_log, read_details_json
from app.rag_tr_tool.utils.answers_store import read_answers_json
from app.rag_tr_tool.utils.rewrite_store import read_rwa_json, calc_rewrite_data

# DBに実験が1件もない場合のデフォルトパラメータ
_DEFAULT_PARAMS = {
    "top_k": 5,
    "chunk_size": 500,
    "overlap": 100,
    "chunker": "langchain",
}

_CONFIG_PATH = Path(settings.BASE_DIR) / "app" / "rag_tr_tool" / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_new_experiment_context(params_from_list: str | None, project_id: int = 1) -> dict:
    """new_experiment_view用のテンプレートコンテキストを返す。

    Returns:
        {
            "last_exp": Experiment | _FakeExp,
            "last_params_json": str,
            "last_name": str,
            "index_exists": bool,
            "index_info": dict,
            "query_count": int | None,
            "spec_text": str,
        }
    """
    if params_from_list:
        last_params = json.loads(params_from_list)
        last_exp = Experiment.objects.filter(project_id=project_id).order_by("-created_at").first()
        if last_exp:
            last_exp.parameters = last_params
        else:
            class _FakeExp:
                parameters = last_params
                name = ""
            last_exp = _FakeExp()
    else:
        last_exp = Experiment.objects.filter(project_id=project_id).order_by("-created_at").first()
        last_params = last_exp.parameters if last_exp else _DEFAULT_PARAMS

    index_info = get_index_info(last_params, project_id=project_id) if last_params else {"exists": False}

    queries_path = Path(settings.BASE_DIR) / "data" / "rag_tr_tool" / f"pj_{project_id}" / "evaluation_queries.json"
    try:
        query_count = len(json.loads(queries_path.read_text(encoding="utf-8")))
    except Exception:
        query_count = None

    return {
        "last_exp": last_exp,
        "last_params_json": json.dumps(last_params, ensure_ascii=False),
        "last_name": last_exp.name if last_exp else "",
        "index_exists": index_info["exists"],
        "index_info": index_info,
        "query_count": query_count,
        "spec_text": resolve_spec(last_params),
    }


def get_experiment_list(project_id: int) -> list:
    """実験一覧を表示用データに整形して返す。"""
    experiments = list(Experiment.objects.filter(project_id=project_id).order_by("-mrr"))
    for e in experiments:
        e.parameters_json = json.dumps(e.parameters, ensure_ascii=False)
        e.parameters_display = e.parameters_json.strip("{}").replace('"', '')
        e.has_log = read_log(e.id, project_id=project_id) is not None
        saved = read_details_json(e.id, project_id=project_id)
        e.query_count = saved.get("meta", {}).get("query_count", 0) if saved else 0

    # QRY降順 → MRR降順 → Recall@K降順 → ID降順
    experiments.sort(key=lambda e: (-e.query_count, -e.mrr, -e.recall_at_5, -e.id))

    # New / 1st / 2nd アイコン判定（ID降順で上位3件）
    sorted_by_id = sorted(experiments, key=lambda e: e.id, reverse=True)
    icon_map = {}
    for rank, exp in enumerate(sorted_by_id[:3]):
        icon_map[exp.id] = ["new", "1st", "2nd"][rank]
    for e in experiments:
        e.icon = icon_map.get(e.id, "")

    return experiments


def get_result_data(exp_id: int) -> dict:
    """result_view用のテンプレートコンテキストを返す。

    Returns:
        {
            "exp": Experiment,
            "exp_params_urlenc": str,
            "exp_params_json": str,
            "prev_exp": Experiment | None,
            "has_log": bool,
            "details": list,
            "meta": dict,
            "answers": list,
            "has_answers": bool,
            "rewrite_data": list,
            "has_rewrite_data": bool,
            "rewrite_summary": dict | None,
        }
    """
    exp = Experiment.objects.get(id=exp_id)
    project_id = exp.project_id
    prev_exp = Experiment.objects.filter(id__lt=exp.id).order_by("-id").first()
    saved = read_details_json(exp_id, project_id=project_id)
    answers = read_answers_json(exp_id, project_id=project_id)
    rewrite_data = read_rwa_json(exp_id, project_id=project_id)

    rewrite_summary = None
    if rewrite_data:
        rewrite_data, rewrite_summary = calc_rewrite_data(rewrite_data)

    # details の mrr フォールバック補完（旧データは mrr キーなし → correct_rank から計算）
    details = saved.get("details", []) if saved else []
    for d in details:
        if "mrr" not in d:
            rank = d.get("correct_rank")
            d["mrr"] = round(1.0 / rank, 4) if rank else 0.0

    return {
        "exp": exp,
        "exp_params_urlenc": quote(json.dumps(exp.parameters, ensure_ascii=False)),
        "exp_params_json": json.dumps(exp.parameters, ensure_ascii=False),
        "prev_exp": prev_exp,
        "has_log": saved is not None,
        "details": details,
        "meta": saved.get("meta", {}) if saved else {},
        "answers": answers or [],
        "has_answers": answers is not None,
        "rewrite_data": rewrite_data or [],
        "has_rewrite_data": rewrite_data is not None,
        "rewrite_summary": rewrite_summary,
    }


def get_current_project_context(project_id: int | None) -> dict:
    """context_processor用。現在選択中のプロジェクト情報を返す。

    Returns:
        {
            "current_project": RagProject | None,
            "project_description_preview": str,
        }
    """
    if project_id is None:
        return {"current_project": None, "project_description_preview": ""}

    try:
        project = RagProject.objects.get(id=project_id)
    except RagProject.DoesNotExist:
        return {"current_project": None, "project_description_preview": ""}

    config = _load_config()
    max_len = config.get("project_description_max_length", 40)
    preview = project.description[:max_len] if project.description else ""

    return {
        "current_project": project,
        "project_description_preview": preview,
    }