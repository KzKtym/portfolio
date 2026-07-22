"""data_services.py - データ操作（Index確認・実験削除・compare用データ構築）"""
import difflib

from ...models import Experiment
from app.rag_tr_tool.core.evaluation import normalize_query_option
from app.rag_tr_tool.core.indexing.index_builder import get_index_info
from app.rag_tr_tool.utils.spec_extractor import resolve_spec
from app.rag_tr_tool.utils.log_formatter import get_logs_dir
from app.rag_tr_tool.utils.rewrite_store import read_rwa_json


def get_index_check(params: dict) -> dict:
    """check_index用のレスポンスデータを返す。"""
    project_id = params.pop("project_id", 1)
    info = get_index_info(params, project_id=project_id)
    info["spec_text"] = resolve_spec(params)
    return info


def delete_experiments_service(id_list: list[str]) -> None:
    """実験レコードとログファイル5種を削除する。"""
    for exp_id in id_list:
        try:
            exp = Experiment.objects.get(id=exp_id)
            logs_dir = get_logs_dir(exp.project_id)
        except Experiment.DoesNotExist:
            continue
        for suffix in [".log", ".json", "_answers.json", "_answers.bak", "_rewrite.json"]:
            f = logs_dir / f"exp_{exp_id}{suffix}"
            if f.exists():
                f.unlink()
    Experiment.objects.filter(id__in=id_list).delete()


def build_compare_data(id1: int, id2: int) -> dict:
    """compare_view用のテンプレートコンテキストを返す。

    Returns:
        {
            "exp_a": Experiment,
            "exp_b": Experiment,
            "spec_diff": list[str],
            "param_comparison": list[dict],
            "mrr_diff": float,
            "recall_diff": float,
            "show_rwa_btn": bool,
            "rwa_disabled_reasons": list[str],
        }
    """
    exp1 = Experiment.objects.get(id=id1)
    exp2 = Experiment.objects.get(id=id2)

    # SPEC比較: 全行表示＋差分箇所のみGit風タグ付け（SequenceMatcher使用）
    s1 = exp1.spec_snapshot.splitlines() if exp1.spec_snapshot else ["(No SPEC)"]
    s2 = exp2.spec_snapshot.splitlines() if exp2.spec_snapshot else ["(No SPEC)"]
    spec_diff = []
    matcher = difflib.SequenceMatcher(None, s1, s2)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            spec_diff.extend(("  " + l) for l in s1[i1:i2])
        elif tag == "replace":
            spec_diff.extend(("- " + l) for l in s1[i1:i2])
            spec_diff.extend(("+ " + l) for l in s2[j1:j2])
        elif tag == "delete":
            spec_diff.extend(("- " + l) for l in s1[i1:i2])
        elif tag == "insert":
            spec_diff.extend(("+ " + l) for l in s2[j1:j2])

    # パラメータ比較
    all_keys = sorted(set(exp1.parameters.keys()) | set(exp2.parameters.keys()))
    param_comparison = [
        {
            "key": key,
            "val1": exp1.parameters.get(key, "-"),
            "val2": exp2.parameters.get(key, "-"),
            "is_diff": exp1.parameters.get(key, "-") != exp2.parameters.get(key, "-"),
        }
        for key in all_keys
    ]

    has_rwa_a = read_rwa_json(exp1.id, project_id=exp1.project_id) is not None
    has_rwa_b = read_rwa_json(exp2.id, project_id=exp2.project_id) is not None
    show_rwa_btn = has_rwa_a and has_rwa_b

    rwa_disabled_reasons = []
    if not show_rwa_btn:
        for exp, has in [(exp1, has_rwa_a), (exp2, has_rwa_b)]:
            if not has:
                # 保存されるキーは query_option（rewrite / multi のとき RWA データが生成される）
                qr = normalize_query_option(exp.parameters.get("query_option")) is not None
                if qr:
                    rwa_disabled_reasons.append(
                        f"Exp {exp.id}: Rewriteデータなし（query_option=rewrite/multi で再実行すると生成されます）"
                    )
                else:
                    rwa_disabled_reasons.append(
                        f"Exp {exp.id}: query_option 未指定（Rewriteデータは生成されません）"
                    )

    return {
        "exp_a": exp1,
        "exp_b": exp2,
        "spec_diff": spec_diff,
        "param_comparison": param_comparison,
        "mrr_diff": round(exp2.mrr - exp1.mrr, 4),
        "recall_diff": round(exp2.recall_at_5 - exp1.recall_at_5, 4),
        "show_rwa_btn": show_rwa_btn,
        "rwa_disabled_reasons": rwa_disabled_reasons,
    }