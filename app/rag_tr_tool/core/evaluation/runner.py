import json
import logging
import time
from pathlib import Path

from django.conf import settings

from app.rag_tr_tool.utils.rewrite_store import save_rwa_json
from app.rag_tr_tool.core.indexing.index_builder import build_index
from app.rag_tr_tool.core.retrieval.retriever import Retriever
from .metrics import reciprocal_rank, recall_at_k
from .query_logic import is_gated, merge_results, merge_by_score
from .params import EvalParams
from app.rag_tr_tool.utils.log_formatter import get_logs_dir

logger = logging.getLogger(__name__)

_DATA_DIR = Path(settings.BASE_DIR) / "data" / "rag_tr_tool"


def save_log(exp_id: int, log_text: str, project_id: int) -> Path:
    """ログファイルを保存し、パスを返す"""
    logs_dir = get_logs_dir(project_id)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"exp_{exp_id}.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(log_text)
    return log_path


def save_details_json(exp_id: int, details: list, meta: dict, project_id: int) -> Path:
    """details+metaをJSONで保存し、パスを返す"""
    logs_dir = get_logs_dir(project_id)
    logs_dir.mkdir(parents=True, exist_ok=True)
    json_path = logs_dir / f"exp_{exp_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"details": details, "meta": meta}, f, ensure_ascii=False, indent=2)
    return json_path


def run_evaluation(params: dict, rebuild: bool = False, project_id: int = 1) -> dict:
    p = EvalParams.from_dict(params)
    start = time.time()

    try:
        store, embedder, index_creation_time = build_index(params, rebuild=rebuild, project_id=project_id)
        total_chunks = store.index.ntotal
        logger.debug("total chunks: %s", total_chunks)

        retriever = Retriever(store, embedder)

        # Re-rankerのロード（評価ループ前に一度だけ）
        reranker = None
        if p.reranker == "cross":
            from app.rag_tr_tool.core.retrieval.cross_encoder_reranker import CrossEncoderReranker
            reranker = CrossEncoderReranker()
            # reranker + candidate_k 同時指定の警告
            if p.candidate_k is not None:
                logger.warning("reranker と candidate_k が同時指定されています。rerank_k を優先し candidate_k は無視します。")

        if p.query_option == "rewrite":
            # SPEC_rewrite: 35/Query Rewrite/original+rewrite 2系統検索→rankベースmerge→top_k絞り込み
            from app.rag_tr_tool.core.rewrite.query_rewriter import rewrite_query
        elif p.query_option == "multi":
            # SPEC_multi_query_merge_max: 35/Multi Query/merge:max
            # SPEC_multi_query_merge_weighted: 35/Multi Query/merge:weighted
            # SPEC_multi_query_norm_minmax: 35/Multi Query/normalize:minmax
            # SPEC_multi_query_norm_none: 35/Multi Query/normalize:none
            # SPEC_multi_query_gate_standard: 35/Multi Query/gate:standard
            # SPEC_multi_query_gate_top1: 35/Multi Query/gate:top1
            # SPEC_multi_query_gate_margin: 35/Multi Query/gate:margin
            from app.rag_tr_tool.core.rewrite.query_rewriter import generate_queries

        with open(_DATA_DIR / f"pj_{project_id}" / "evaluation_queries.json", encoding="utf-8") as f:
            queries = json.load(f)

        total_mrr = 0.0
        total_recall = 0.0
        details = []
        rwa_queries = []

        def _to_list(rs):
            return [{"rank": r["rank"],
                     "score": round(float(r["score"]), 4),
                     "source": r["metadata"]["source"]} for r in rs]

        def _apply_score_threshold(results):
            """正規化後スコアでscore_threshold未満を除外。0件になる場合は元の結果を返す。
            candidate_k指定時は既に多め取得済みのresultsを受け取るため、
            フィルタ後にtop_k件に絞る。
            """
            if p.score_threshold is None or not results:
                return results[:p.top_k]
            # SPEC_score_threshold: 40/Retrieval/Score Filter/Post-Normalization/Threshold
            scores = [r['score'] for r in results]
            s_min, s_max = min(scores), max(scores)
            denom = s_max - s_min if s_max != s_min else 1.0
            filtered = [r for r in results
                        if (r['score'] - s_min) / denom >= p.score_threshold]
            filtered = filtered[:p.top_k]
            return filtered if filtered else results[:p.top_k]

        def _search(query, query_no=None):
            # Re-ranker有効時はrerank_k件取得（candidate_kは無視）
            # Re-ranker無効時はcandidate_k指定があればcandidate_k件、なければtop_k件取得
            if reranker is not None:
                k_for_search = p.rerank_k
            elif p.candidate_k is not None:
                k_for_search = p.candidate_k
            else:
                k_for_search = p.top_k
            results = retriever.search(query, k=k_for_search,
                                       search_type=p.search_type,
                                       fetch_k=p.fetch_k,
                                       lambda_mult=p.lambda_mult,
                                       rrf_k=p.rrf_k)
            # BM25フォールバック発生時にクエリ番号を記録
            if query_no is not None and retriever._bm25_fallback_count > len(retriever._bm25_fallback_query_indices):
                retriever._bm25_fallback_query_indices.append(query_no)
            if reranker is not None:
                results = reranker.rerank(query, results)
            return _apply_score_threshold(results)

        skipped_count = 0
        for i, q in enumerate(queries):
            query_no = i + 1
            if p.skip_no_answer and not q.get("relevant_sources"):
                skipped_count += 1
                continue
            if p.query_option == "rewrite":
                rewritten = rewrite_query(q["query"])
                results_original = _search(q["query"], query_no)
                results_rewrite = _search(rewritten)
                results = merge_results(results_original, results_rewrite, p.top_k)
                # Re-ranker有効時：merge後にre-rank（_search内では実施済みのため、merge後の統合結果に再適用）
                if reranker is not None:
                    results = reranker.rerank(q["query"], results)

            elif p.query_option == "multi":
                results_original = _search(q["query"], query_no)
                if p.gate_score == "raw":
                    # SPEC_gate_score_raw: 35/Multi Query/Gate Score/Pre-Normalization(Raw)
                    gated, g_top1, g_margin = is_gated(results_original, p.gate_mode, p.gate_top1, p.gate_margin)
                else:
                    gated, g_top1, g_margin = False, 0.0, 0.0

                if gated:
                    generated = []
                    all_queries = [q["query"]]
                    all_results = [results_original]
                    results = results_original
                else:
                    generated = generate_queries(q["query"])
                    all_queries = [q["query"]] + generated
                    all_results = [results_original] + [_search(qtext) for qtext in generated]
                    results, gated, g_top1, g_margin = merge_by_score(
                        all_results, p.top_k,
                        original_boost=p.original_boost,
                        boost_threshold=p.boost_threshold,
                        merge_mode=p.merge_mode,
                        normalize=p.normalize,
                        gate_score=p.gate_score,
                        gate_mode=p.gate_mode,
                        gate_top1=p.gate_top1,
                        gate_margin=p.gate_margin,
                    )
                    # Re-ranker有効時：merge後にre-rank（score_thresholdより先に適用）
                    if reranker is not None:
                        results = reranker.rerank(q["query"], results)
                    results = _apply_score_threshold(results)
                    if gated:
                        generated = []
                        all_queries = [q["query"]]
                        all_results = [results_original]
            else:
                results = _search(q["query"], query_no)

            mrr = reciprocal_rank(results, q["relevant_sources"])
            recall = recall_at_k(results, q["relevant_sources"], p.top_k)
            total_mrr += mrr
            total_recall += recall

            correct_rank = None
            for r in results:
                if r["metadata"]["source"] in q["relevant_sources"]:
                    correct_rank = r["rank"]
                    break

            details.append({
                "query": q["query"],
                "correct_rank": correct_rank,
                "mrr": round(mrr, 4),
                "results": [{"rank": r["rank"],
                              "score": round(float(r["score"]), 4),
                              "source": r["metadata"]["source"],
                              "text": r.get("text", "")[:300]} for r in results],
            })

            if p.query_option == "rewrite":
                mrr_original = reciprocal_rank(results_original, q["relevant_sources"])
                mrr_rewrite = reciprocal_rank(results_rewrite, q["relevant_sources"])
                rwa_queries.append({
                    "mode": "rewrite",
                    "query": q["query"],
                    "rewrite_query": rewritten,
                    "relevant_sources": q["relevant_sources"],
                    "mrr_original": round(mrr_original, 4),
                    "mrr_rewrite": round(mrr_rewrite, 4),
                    "results_original": _to_list(results_original),
                    "results_rewrite": _to_list(results_rewrite),
                })
            elif p.query_option == "multi":
                mrr_original = reciprocal_rank(all_results[0], q["relevant_sources"])
                mrr_merged = reciprocal_rank(results, q["relevant_sources"])
                rwa_queries.append({
                    "mode": "multi",
                    "query": q["query"],
                    "generated_queries": generated,
                    "relevant_sources": q["relevant_sources"],
                    "mrr_original": round(mrr_original, 4),
                    "mrr_rewrite": round(mrr_merged, 4),
                    "results_original": _to_list(all_results[0]),
                    "results_rewrite": _to_list(results),
                    "results_per_query": [
                        {"query": all_queries[i], "results": _to_list(all_results[i])}
                        for i in range(1, len(all_queries))
                    ],
                    "gated": gated,
                    "gate_top1": round(g_top1, 4),
                    "gate_margin": round(g_margin, 4),
                })

        n = len(queries) - skipped_count
        elapsed = time.time() - start
        mrr_val = round(total_mrr / n, 4) if n > 0 else 0.0
        recall_val = round(total_recall / n, 4) if n > 0 else 0.0

        # BM25フォールバック発生時のみWARNINGを1行出力
        if retriever._bm25_fallback_count > 0:
            indices_str = ", ".join(str(i) for i in retriever._bm25_fallback_query_indices)
            logger.warning(
                "BM25 not available, fell back to similarity search. count=%s/%s, query_no=[%s]",
                retriever._bm25_fallback_count, n, indices_str,
            )

        chunk_lengths = [len(t) for t in store.texts] if store.texts else []
        chunk_stats = {
            "avg": round(sum(chunk_lengths) / len(chunk_lengths)) if chunk_lengths else 0,
            "max": max(chunk_lengths) if chunk_lengths else 0,
            "min": min(chunk_lengths) if chunk_lengths else 0,
        }

        return {
            "status": "success",
            "metrics": {"mrr": mrr_val, "recall_at_5": recall_val},
            "meta": {
                "evaluation_time_sec": round(elapsed, 2),
                "query_count": n,
                "skipped_count": skipped_count,
                "total_chunks": total_chunks,
                "index_creation_time": index_creation_time,
                "chunk_stats": chunk_stats,
            },
            "details": details,
            "rwa_queries": rwa_queries,
        }

    except Exception as e:
        # 呼び出し側は status を必ず判定すること。
        # 例外を dict に畳むとトレースバックが失われるため、ここで必ずログに残す。
        elapsed = time.time() - start
        logger.exception(
            "run_evaluation failed (project_id=%s, params=%s)", project_id, params
        )
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
            "meta": {
                "evaluation_time_sec": round(elapsed, 2),
                "query_count": 0,
                "total_chunks": 0,
                "index_creation_time": None,
            },
        }