def reciprocal_rank(results: list, relevant_sources: list) -> float:
    """MRR計算。relevant_sourcesの最初のhitの逆数を返す。"""
    for r in results:
        if r["metadata"]["source"] in relevant_sources:
            return 1.0 / r["rank"]
    return 0.0


def recall_at_k(results: list, relevant_sources: list, k: int) -> int:
    """Recall@k計算。top-k内にhitがあれば1、なければ0。"""
    for r in results[:k]:
        if r["metadata"]["source"] in relevant_sources:
            return 1
    return 0
