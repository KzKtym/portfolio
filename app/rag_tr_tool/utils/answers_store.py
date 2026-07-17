import json
from pathlib import Path

from app.rag_tr_tool.utils.log_formatter import get_logs_dir


def save_answers_json(exp_id: int, answers: list, project_id: int) -> Path:
    """LLM回答をJSONで保存。既存ファイルは .bak にリネームして残す。"""
    logs_dir = get_logs_dir(project_id)
    logs_dir.mkdir(parents=True, exist_ok=True)
    json_path = logs_dir / f"exp_{exp_id}_answers.json"
    bak_path = logs_dir / f"exp_{exp_id}_answers.bak"

    if json_path.exists():
        json_path.rename(bak_path)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"answers": answers}, f, ensure_ascii=False, indent=2)

    return json_path


def read_answers_json(exp_id: int, project_id: int) -> list | None:
    """保存済みLLM回答を読み込む。なければNone。"""
    logs_dir = get_logs_dir(project_id)
    json_path = logs_dir / f"exp_{exp_id}_answers.json"
    if not json_path.exists():
        return None
    return json.loads(json_path.read_text(encoding="utf-8")).get("answers", [])