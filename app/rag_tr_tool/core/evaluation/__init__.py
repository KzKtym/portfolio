"""evaluation パッケージ。
呼び出し側は従来通り core.evaluation から import できる。
"""
from .runner import run_evaluation, save_log, save_details_json
from .query_logic import normalize_query_option, is_gated, merge_results, merge_by_score
from .metrics import reciprocal_rank, recall_at_k
from .params import EvalParams

__all__ = [
    "run_evaluation",
    "save_log",
    "save_details_json",
    "normalize_query_option",
    "is_gated",
    "merge_results",
    "merge_by_score",
    "reciprocal_rank",
    "recall_at_k",
    "EvalParams",
]