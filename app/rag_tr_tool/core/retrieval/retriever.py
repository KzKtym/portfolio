from typing import List, Dict
import numpy as np


class Retriever:

    def __init__(self, store, embedder):
        self.store = store
        self.embedder = embedder
        self._bm25_fallback_count = 0
        self._bm25_fallback_query_indices = []

    def search(self, query: str, k: int = 5,
               search_type: str = "similarity",
               fetch_k: int = 20,
               lambda_mult: float = 0.5,
               rrf_k: int = 60) -> List[Dict]:

        # 1️⃣ embed query
        raw_query = query                        # BM25検索用に元クエリを退避
        query = "query: " + query
        query_vector = self.embedder.embed([query])[0]
        query_vector = np.array([query_vector]).astype("float32")

        if search_type == "mmr":
            # SPEC_mmr: 40/Retrieval/MMR/fetch_k,lambda_mult
            return self._search_mmr(query_vector, k, fetch_k, lambda_mult)
        elif search_type == "hybrid":
            if self._bm25_unavailable(query_vector, k):
                return self._search_similarity(query_vector, k)
            # SPEC_hybrid: 40/Retrieval/Hybrid Search/BM25+Vector/RRF
            return self._search_hybrid(query_vector, raw_query, k, fetch_k, rrf_k)
        elif search_type == "bm25":
            if self._bm25_unavailable(query_vector, k):
                return self._search_similarity(query_vector, k)
            # SPEC_bm25: 40/Retrieval/BM25単独検索
            return self._search_bm25(raw_query, k)
        else:
            # SPEC_similarity: 40/Retrieval/Similarity検索
            return self._search_similarity(query_vector, k)

    def _bm25_unavailable(self, query_vector: np.ndarray, k: int) -> bool:
        """BM25が利用不可の場合にフォールバックカウントを増やしTrueを返す。
        旧インデックス（bm25.pkl未存在）はsimilarityにフォールバック。
        """
        if self.store.bm25 is None:
            self._bm25_fallback_count += 1
            return True
        return False

    def log_bm25_fallback(self, query_index: int):
        """フォールバック発生クエリ番号を記録する（runner.pyから呼び出す）。"""
        self._bm25_fallback_query_indices.append(query_index)

    def _search_similarity(self, query_vector: np.ndarray, k: int) -> List[Dict]:
        distances, indices = self.store.index.search(query_vector, k)
        results = []
        for rank, idx in enumerate(indices[0]):
            if idx == -1:
                continue
            metadata = self.store.metadata[idx]
            text = self.store.texts[idx] if self.store.texts else ""
            results.append({
                "rank": rank + 1,
                "score": float(distances[0][rank]),
                "metadata": metadata,
                "text": text,
            })
        return results

    def _search_mmr(self, query_vector: np.ndarray, k: int,
                    fetch_k: int, lambda_mult: float) -> List[Dict]:
        # fetch_k件候補取得
        distances, indices = self.store.index.search(query_vector, fetch_k)

        candidates = []
        for rank, idx in enumerate(indices[0]):
            if idx == -1:
                continue
            candidates.append({
                "idx": int(idx),
                "score": float(distances[0][rank]),
            })

        if not candidates:
            return []

        # 候補ベクトルを取得（選択済みとの多様性計算用）
        candidate_indices = [c["idx"] for c in candidates]
        all_vectors = self.store.index.reconstruct_batch(candidate_indices)
        # L2正規化（選択済みとのコサイン類似度計算用）
        norms = np.linalg.norm(all_vectors, axis=1, keepdims=True) + 1e-10
        all_vectors_norm = all_vectors / norms

        # MMR選択ループ
        selected = []
        remaining = list(range(len(candidates)))

        while len(selected) < k and remaining:
            best_score = -np.inf
            best_pos = None

            for pos in remaining:
                # クエリとの類似度
                # IndexFlatIP: スコアが大きいほど類似（符号そのまま）
                # IndexFlatL2: 距離が小さいほど類似（符号反転）
                if self.store.faiss_index_type == "flatip":
                    sim_query = candidates[pos]["score"]
                else:
                    sim_query = -candidates[pos]["score"]

                # 選択済みとの最大コサイン類似度（多様性ペナルティ）
                if selected:
                    sim_selected = float(np.max(
                        all_vectors_norm[selected] @ all_vectors_norm[pos]
                    ))
                else:
                    sim_selected = 0.0

                mmr_score = lambda_mult * sim_query - (1 - lambda_mult) * sim_selected

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_pos = pos

            selected.append(best_pos)
            remaining.remove(best_pos)

        results = []
        for rank, pos in enumerate(selected):
            idx = candidates[pos]["idx"]
            metadata = self.store.metadata[idx]
            text = self.store.texts[idx] if self.store.texts else ""
            results.append({
                "rank": rank + 1,
                "score": candidates[pos]["score"],
                "metadata": metadata,
                "text": text,
            })
        return results

    def _search_hybrid(self, query_vector: np.ndarray, query_text: str,
                       k: int, fetch_k: int, rrf_k: int) -> List[Dict]:
        """BM25 + Vector のHybrid検索。RRFでスコアを統合する。"""

        # --- Vector検索: fetch_k件取得 ---
        distances, indices = self.store.index.search(query_vector, fetch_k)
        vector_hits = {}  # idx -> vector_rank (1-indexed)
        for rank, idx in enumerate(indices[0]):
            if idx == -1:
                continue
            vector_hits[int(idx)] = rank + 1

        # --- BM25検索: 全文書スコアリングして上位fetch_k件取得 ---
        tokenized_query = query_text.split()
        bm25_scores = self.store.bm25.get_scores(tokenized_query)
        # 上位fetch_k件のインデックスを取得（スコア降順）
        bm25_top_indices = np.argsort(bm25_scores)[::-1][:fetch_k]
        bm25_hits = {}  # idx -> bm25_rank (1-indexed)
        for rank, idx in enumerate(bm25_top_indices):
            bm25_hits[int(idx)] = rank + 1

        # --- RRF統合 ---
        all_indices = set(vector_hits.keys()) | set(bm25_hits.keys())
        rrf_scores = {}
        for idx in all_indices:
            score = 0.0
            if idx in vector_hits:
                score += 1.0 / (rrf_k + vector_hits[idx])
            if idx in bm25_hits:
                score += 1.0 / (rrf_k + bm25_hits[idx])
            rrf_scores[idx] = score

        # RRFスコア降順でtop_k件を選択
        sorted_indices = sorted(rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True)[:k]

        results = []
        for rank, idx in enumerate(sorted_indices):
            metadata = self.store.metadata[idx]
            text = self.store.texts[idx] if self.store.texts else ""
            results.append({
                "rank": rank + 1,
                "score": rrf_scores[idx],
                "metadata": metadata,
                "text": text,
            })
        return results

    def _search_bm25(self, query_text: str, k: int) -> List[Dict]:
        """BM25のみによる検索。ベクトル検索は使用しない。"""
        tokenized_query = query_text.split()
        bm25_scores = self.store.bm25.get_scores(tokenized_query)
        top_indices = np.argsort(bm25_scores)[::-1][:k]
        results = []
        for rank, idx in enumerate(top_indices):
            metadata = self.store.metadata[idx]
            text = self.store.texts[idx] if self.store.texts else ""
            results.append({
                "rank": rank + 1,
                "score": float(bm25_scores[idx]),
                "metadata": metadata,
                "text": text,
            })
        return results