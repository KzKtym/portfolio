from typing import List, Dict
from sentence_transformers import CrossEncoder


class CrossEncoderReranker:
    """Cross-Encoderによるre-ranker。
    retriever.search()が返した結果リストを query × chunk テキストで再スコアリングし、
    降順ソート済みのリストを返す。件数絞り込みは呼び出し側（_apply_score_threshold）に委ねる。
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, results: List[Dict], rerank_score: bool = False) -> List[Dict]:
        """resultsをre-rankして降順ソート済みリストを返す（件数は絞らない）。

        Args:
            query: 元のクエリ文字列
            results: retriever.search()が返したリスト（"text"キーを含むこと）
            rerank_score: Trueの場合はCross-Encoderスコアでscoreを上書きする。
                          False（既定）の場合は元のretrievalスコアを保持する。

        Returns:
            re-rank済み・rank振り直し済みのリスト（入力と同件数）
        """
        if not results:
            return results

        pairs = [(query, r.get("text", "")) for r in results]
        # SPEC_cross: 45/Re-ranking/Cross-Encoder/ms-marco-MiniLM系
        scores = self.model.predict(pairs, show_progress_bar=False)

        scored = sorted(
            zip(scores, results),
            key=lambda x: x[0],
            reverse=True,
        )

        reranked = []
        for rank, (score, result) in enumerate(scored, start=1):
            entry = dict(result)
            entry["rank"] = rank
            if rerank_score:
                entry["score"] = float(score)
            reranked.append(entry)

        return reranked