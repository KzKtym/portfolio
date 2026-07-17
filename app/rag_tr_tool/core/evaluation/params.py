from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EvalParams:
    """実験パラメータの入口。JSONパラメータdictからの変換・デフォルト値管理を担う。
    各コアモジュールへは必要な値だけ個別に渡すこと（EvalParamsを直接渡さない）。
    """
    top_k: int = 5
    search_type: str = "similarity"
    fetch_k: int = 20
    lambda_mult: float = 0.5
    query_option: Optional[str] = None   # None / "rewrite" / "multi"
    # Multi Query関連
    original_boost: float = 1.0
    boost_threshold: float = 0.0
    gate_top1: float = 1.1         # デフォルト1.1→ゲーティング無効
    gate_margin: float = 0.0
    merge_mode: str = "max"        # "max" / "weighted"
    normalize: str = "minmax"      # "minmax" / "none"
    gate_mode: Optional[str] = None  # None=無効 / "top1" / "margin" / "standard"
    gate_score: str = "raw"            # "raw"=生スコアで判定 / "normalized"=正規化後スコアで判定
    score_threshold: Optional[float] = None  # None=フィルタ無効 / 小数=正規化後スコアの下限
    candidate_k: Optional[int] = None        # None=top_kと同値 / 整数=フィルタ前取得件数
    # BM25関連（hybrid検索時に使用）
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    # RRF関連（hybrid検索時に使用）
    rrf_k: int = 60
    # 評価制御
    skip_no_answer: bool = False  # True=relevant_sourcesが空のクエリをスキップ
    # Re-ranker関連
    reranker: Optional[str] = None   # None=無効 / "cross"=Cross-Encoder
    rerank_k: int = 20               # Re-rankerへの入力候補数（reranker指定時のみ使用）

    @staticmethod
    def normalize(raw_dict: dict) -> dict:
        """リクエスト由来の生dictを正規化して返す。
        キー・値の不要なクォートを除去し、数値文字列を適切な型に変換する。
        戻り値はfrom_dict()に渡せるクリーンなdict。
        """
        result = {}
        for k, v in raw_dict.items():
            key = str(k).replace('"', '').replace("'", "").strip()
            if isinstance(v, str):
                val = v.replace('"', '').replace("'", "").strip()
                if val.isdigit():
                    val = int(val)
                else:
                    try:
                        val = float(val)
                    except ValueError:
                        pass
            else:
                val = v
            # 整数値であれば確実に int 型へ（キャッシュの一致に不可欠）
            if isinstance(val, float) and val.is_integer():
                val = int(val)
            result[key] = val
        return result

    @classmethod
    def from_dict(cls, params: dict) -> "EvalParams":
        """JSONパラメータdictからEvalParamsを生成する。
        query_optionはbool/文字列を正規化して格納。
        gate_modeが未指定の場合はgate_top1/gate_marginの有無から自動推論。
        """
        from app.rag_tr_tool.core.evaluation.query_logic import normalize_query_option
        gate_mode = params.get("gate_mode", None)
        if gate_mode is None:
            has_top1 = "gate_top1" in params
            has_margin = "gate_margin" in params
            if has_top1 and has_margin:
                gate_mode = "standard"
            elif has_top1:
                gate_mode = "top1"
            elif has_margin:
                gate_mode = "margin"
            # どちらもなければNone（ゲーティング無効）のまま
        return cls(
            top_k=int(params.get("top_k", 5)),
            search_type=params.get("search_type", "similarity"),
            fetch_k=int(params.get("fetch_k", 20)),
            lambda_mult=float(params.get("lambda_mult", 0.5)),
            query_option=normalize_query_option(params.get("query_option", None)),
            original_boost=float(params.get("original_boost", 1.0)),
            boost_threshold=float(params.get("boost_threshold", 0.0)),
            gate_top1=float(params.get("gate_top1", 1.1)),
            gate_margin=float(params.get("gate_margin", 0.0)),
            merge_mode=params.get("merge_mode", "max"),
            normalize=params.get("normalize", "minmax"),
            gate_mode=gate_mode,
            gate_score=params.get("gate_score", "raw"),
            score_threshold=float(params["score_threshold"]) if "score_threshold" in params and params["score_threshold"] is not None else None,
            candidate_k=int(params["candidate_k"]) if "candidate_k" in params and params["candidate_k"] is not None else None,
            bm25_k1=float(params.get("bm25_k1", 1.5)),
            bm25_b=float(params.get("bm25_b", 0.75)),
            rrf_k=int(params.get("rrf_k", 60)),
            skip_no_answer=str(params.get("skip_no_answer", "false")).lower() == "true",
            reranker=params.get("reranker", None) or None,
            rerank_k=int(params.get("rerank_k", 20)),
        )