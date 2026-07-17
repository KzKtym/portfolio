"""llm_service.py - LLM回答生成（generate_answers）"""
from ..models import Experiment
from app.rag_tr_tool.core.evaluation import EvalParams, merge_results, merge_by_score, is_gated
from app.rag_tr_tool.core.indexing.index_builder import build_index
from app.rag_tr_tool.core.retrieval.retriever import Retriever
from app.rag_tr_tool.core.rewrite.query_rewriter import rewrite_query, generate_queries
from app.rag_tr_tool.core.llm.prompt_template import build_prompt
from app.rag_tr_tool.core.llm.openai_client import generate_answer
from app.rag_tr_tool.utils.log_formatter import read_details_json
from app.rag_tr_tool.utils.answers_store import save_answers_json


def generate_answers_service(exp_id: int) -> dict:
    """実験のdetailsを再検索し、LLMで回答生成してファイル保存・結果を返す。

    Returns:
        {"answers": list}  成功時
        {"error": str, "answers": list, "status": int}  エラー時
    """
    exp = Experiment.objects.get(id=exp_id)
    project_id = exp.project_id
    p = EvalParams.from_dict(exp.parameters)

    store, embedder, _ = build_index(exp.parameters, rebuild=False, project_id=project_id)
    retriever = Retriever(store, embedder)

    saved = read_details_json(exp_id, project_id=project_id)
    if not saved:
        return {"error": "詳細データが存在しません", "answers": [], "status": 404}

    def _search(query):
        return retriever.search(
            query, k=p.top_k, search_type=p.search_type,
            fetch_k=p.fetch_k, lambda_mult=p.lambda_mult,
        )

    queries = [d["query"] for d in saved.get("details", [])]
    answers = []

    for query in queries:
        if p.query_rewrite == "true":
            rewritten = rewrite_query(query)
            results = merge_results(_search(query), _search(rewritten), p.top_k)
        elif p.query_rewrite == "multi":
            results_original = _search(query)
            gated, _, _ = is_gated(results_original, p.gate_mode, p.gate_top1, p.gate_margin)
            if gated:
                results = results_original
            else:
                generated = generate_queries(query)
                all_results = [results_original] + [_search(q) for q in generated]
                results = merge_by_score(
                    all_results, p.top_k,
                    original_boost=p.original_boost,
                    boost_threshold=p.boost_threshold,
                    merge_mode=p.merge_mode,
                    normalize=p.normalize,
                )
        else:
            results = _search(query)

        context = "\n\n".join(r["text"] for r in results if r.get("text"))
        prompt = build_prompt(context=context, question=query)

        try:
            answer = generate_answer(prompt)
            answers.append({"query": query, "answer": answer})
        except RuntimeError as e:
            # 429/401: 即時中断（生成済み分は保存しない）
            return {"error": str(e), "answers": answers, "status": 502}
        except Exception as e:
            # その他: スキップして続行
            answers.append({"query": query, "answer": f"Error: {e}"})

    save_answers_json(exp_id, answers, project_id=project_id)
    return {"answers": answers}