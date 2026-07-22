"""層B: retrieval / llm / rewrite。

store と embedder はフェイクを注入するため faiss は不要。
LLM 系は urlopen をモックし、実通信なしでエラー分岐とパースを検証する。
"""
import io
import json
import urllib.error
from unittest.mock import MagicMock, patch

import numpy as np
from django.test import SimpleTestCase

from app.rag_tr_tool.core.llm import openai_client
from app.rag_tr_tool.core.retrieval.cross_encoder_reranker import CrossEncoderReranker
from app.rag_tr_tool.core.retrieval.retriever import Retriever
from app.rag_tr_tool.core.rewrite import query_rewriter


class FakeIndex:
    """faiss インデックスの最小フェイク。search は指定の (distances, indices) を返す。"""

    def __init__(self, distances, indices, vectors=None):
        self._distances = distances
        self._indices = indices
        self._vectors = vectors

    def search(self, query_vector, k):
        return (np.array([self._distances[:k]]), np.array([self._indices[:k]]))

    def reconstruct_batch(self, indices):
        return np.array([self._vectors[i] for i in indices], dtype="float32")


class FakeStore:
    def __init__(self, distances, indices, n=3, bm25=None,
                 faiss_index_type="flatip", vectors=None, texts=True):
        self.index = FakeIndex(distances, indices, vectors)
        self.metadata = [{"source": f"s{i}.md"} for i in range(n)]
        self.texts = [f"text{i}" for i in range(n)] if texts else []
        self.bm25 = bm25
        self.faiss_index_type = faiss_index_type


class FakeEmbedder:
    def embed(self, texts):
        self.last = texts
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


class FakeBM25:
    def __init__(self, scores):
        self._scores = np.array(scores, dtype="float64")
        self.last_query = None

    def get_scores(self, tokenized_query):
        self.last_query = tokenized_query
        return self._scores


class RetrieverSimilarityTest(SimpleTestCase):
    def test_returns_ranked_results(self):
        store = FakeStore([0.9, 0.5, 0.1], [0, 1, 2])
        r = Retriever(store, FakeEmbedder())
        results = r.search("質問", k=3)
        self.assertEqual([x["rank"] for x in results], [1, 2, 3])
        self.assertEqual([x["metadata"]["source"] for x in results],
                         ["s0.md", "s1.md", "s2.md"])
        self.assertAlmostEqual(results[0]["score"], 0.9)

    def test_skips_index_minus_one(self):
        # faiss は候補不足のとき -1 を返す
        store = FakeStore([0.9, 0.0], [0, -1])
        results = Retriever(store, FakeEmbedder()).search("質問", k=2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["metadata"]["source"], "s0.md")

    def test_query_prefix_is_added(self):
        embedder = FakeEmbedder()
        Retriever(FakeStore([0.9], [0]), embedder).search("質問", k=1)
        self.assertEqual(embedder.last, ["query: 質問"])

    def test_text_empty_when_store_has_no_texts(self):
        store = FakeStore([0.9], [0], texts=False)
        results = Retriever(store, FakeEmbedder()).search("質問", k=1)
        self.assertEqual(results[0]["text"], "")

    def test_unknown_search_type_falls_back_to_similarity(self):
        store = FakeStore([0.9], [0])
        results = Retriever(store, FakeEmbedder()).search("質問", k=1, search_type="bogus")
        self.assertEqual(len(results), 1)


class RetrieverBM25FallbackTest(SimpleTestCase):
    def test_hybrid_falls_back_when_bm25_missing(self):
        store = FakeStore([0.9, 0.5], [0, 1], bm25=None)
        r = Retriever(store, FakeEmbedder())
        results = r.search("質問", k=2, search_type="hybrid")
        self.assertEqual(r._bm25_fallback_count, 1)
        self.assertEqual([x["rank"] for x in results], [1, 2])

    def test_bm25_falls_back_when_bm25_missing(self):
        store = FakeStore([0.9], [0], bm25=None)
        r = Retriever(store, FakeEmbedder())
        r.search("質問", k=1, search_type="bm25")
        self.assertEqual(r._bm25_fallback_count, 1)

    def test_fallback_count_accumulates(self):
        r = Retriever(FakeStore([0.9], [0], bm25=None), FakeEmbedder())
        for _ in range(3):
            r.search("質問", k=1, search_type="bm25")
        self.assertEqual(r._bm25_fallback_count, 3)

    def test_similarity_does_not_count_fallback(self):
        r = Retriever(FakeStore([0.9], [0], bm25=None), FakeEmbedder())
        r.search("質問", k=1, search_type="similarity")
        self.assertEqual(r._bm25_fallback_count, 0)

    def test_log_bm25_fallback_records_index(self):
        r = Retriever(FakeStore([0.9], [0], bm25=None), FakeEmbedder())
        r.log_bm25_fallback(7)
        self.assertEqual(r._bm25_fallback_query_indices, [7])


class RetrieverBM25SearchTest(SimpleTestCase):
    def test_orders_by_bm25_score_desc(self):
        store = FakeStore([0.0], [0], n=3, bm25=FakeBM25([0.1, 0.9, 0.5]))
        results = Retriever(store, FakeEmbedder()).search("質問", k=3, search_type="bm25")
        self.assertEqual([x["metadata"]["source"] for x in results],
                         ["s1.md", "s2.md", "s0.md"])
        self.assertEqual([x["rank"] for x in results], [1, 2, 3])

    def test_uses_raw_query_not_prefixed(self):
        bm25 = FakeBM25([0.1, 0.2, 0.3])
        store = FakeStore([0.0], [0], n=3, bm25=bm25)
        Retriever(store, FakeEmbedder()).search("hello world", k=1, search_type="bm25")
        # "query: " プレフィックスは BM25 には渡らない
        self.assertEqual(bm25.last_query, ["hello", "world"])

    def test_truncates_to_k(self):
        store = FakeStore([0.0], [0], n=3, bm25=FakeBM25([0.1, 0.9, 0.5]))
        results = Retriever(store, FakeEmbedder()).search("q", k=2, search_type="bm25")
        self.assertEqual(len(results), 2)


class RetrieverHybridRRFTest(SimpleTestCase):
    def test_rrf_score_combines_both_rankings(self):
        # vector: idx0=1位, idx1=2位 / bm25: idx1=1位, idx0=2位
        store = FakeStore([0.9, 0.5], [0, 1], n=2, bm25=FakeBM25([0.1, 0.9]))
        results = Retriever(store, FakeEmbedder()).search(
            "q", k=2, search_type="hybrid", fetch_k=2, rrf_k=60
        )
        # 双方に出るため 1/(60+1) + 1/(60+2) が両者のスコア
        expected = 1 / 61 + 1 / 62
        for r in results:
            self.assertAlmostEqual(r["score"], expected)

    def test_rrf_k_changes_score(self):
        store = FakeStore([0.9], [0], n=1, bm25=FakeBM25([0.5]))
        kwargs = dict(k=1, search_type="hybrid", fetch_k=1)
        a = Retriever(store, FakeEmbedder()).search("q", rrf_k=10, **kwargs)[0]["score"]
        b = Retriever(store, FakeEmbedder()).search("q", rrf_k=60, **kwargs)[0]["score"]
        self.assertNotAlmostEqual(a, b)
        self.assertGreater(a, b)  # rrf_k が小さいほどスコアは大きい

    def test_vector_only_hit_gets_single_term(self):
        # bm25 スコアが全て 0 でも argsort は全件返すため、fetch_k で絞られる
        store = FakeStore([0.9, 0.5], [0, -1], n=2, bm25=FakeBM25([0.0, 0.0]))
        results = Retriever(store, FakeEmbedder()).search(
            "q", k=2, search_type="hybrid", fetch_k=2, rrf_k=60
        )
        self.assertTrue(all(r["score"] > 0 for r in results))

    def test_rank_is_renumbered(self):
        store = FakeStore([0.9, 0.5], [0, 1], n=2, bm25=FakeBM25([0.1, 0.9]))
        results = Retriever(store, FakeEmbedder()).search(
            "q", k=2, search_type="hybrid", fetch_k=2
        )
        self.assertEqual([r["rank"] for r in results], [1, 2])


class RetrieverMMRTest(SimpleTestCase):
    def _store(self):
        vectors = {0: [1.0, 0.0], 1: [1.0, 0.0], 2: [0.0, 1.0]}
        return FakeStore([0.9, 0.85, 0.2], [0, 1, 2], n=3, vectors=vectors)

    def test_selects_diverse_candidate(self):
        # idx0 と idx1 は同方向。多様性重視(lambda小)なら2件目に idx2 が選ばれる
        results = Retriever(self._store(), FakeEmbedder()).search(
            "q", k=2, search_type="mmr", fetch_k=3, lambda_mult=0.1
        )
        self.assertEqual([r["metadata"]["source"] for r in results], ["s0.md", "s2.md"])

    def test_lambda_one_prefers_pure_relevance(self):
        results = Retriever(self._store(), FakeEmbedder()).search(
            "q", k=2, search_type="mmr", fetch_k=3, lambda_mult=1.0
        )
        self.assertEqual([r["metadata"]["source"] for r in results], ["s0.md", "s1.md"])

    def test_empty_candidates_returns_empty(self):
        store = FakeStore([0.0], [-1], n=1, vectors={})
        results = Retriever(store, FakeEmbedder()).search(
            "q", k=2, search_type="mmr", fetch_k=1
        )
        self.assertEqual(results, [])

    def test_k_larger_than_candidates(self):
        results = Retriever(self._store(), FakeEmbedder()).search(
            "q", k=10, search_type="mmr", fetch_k=3
        )
        self.assertEqual(len(results), 3)


class CrossEncoderRerankerTest(SimpleTestCase):
    def _reranker(self, scores):
        # __init__ は実モデルをロードするため迂回する
        reranker = CrossEncoderReranker.__new__(CrossEncoderReranker)
        reranker.model = MagicMock()
        reranker.model.predict.return_value = scores
        return reranker

    def _results(self):
        return [
            {"rank": 1, "score": 0.9, "text": "t0", "metadata": {"source": "s0.md"}},
            {"rank": 2, "score": 0.5, "text": "t1", "metadata": {"source": "s1.md"}},
        ]

    def test_reorders_by_cross_encoder_score(self):
        reranked = self._reranker([0.1, 0.8]).rerank("q", self._results())
        self.assertEqual([r["metadata"]["source"] for r in reranked], ["s1.md", "s0.md"])
        self.assertEqual([r["rank"] for r in reranked], [1, 2])

    def test_keeps_retrieval_score_by_default(self):
        reranked = self._reranker([0.1, 0.8]).rerank("q", self._results())
        self.assertAlmostEqual(reranked[0]["score"], 0.5)  # 元の s1.md のスコア

    def test_overwrites_score_when_requested(self):
        reranked = self._reranker([0.1, 0.8]).rerank("q", self._results(), rerank_score=True)
        self.assertAlmostEqual(reranked[0]["score"], 0.8)

    def test_does_not_change_result_count(self):
        reranked = self._reranker([0.1, 0.8]).rerank("q", self._results())
        self.assertEqual(len(reranked), 2)

    def test_empty_results_returns_as_is(self):
        self.assertEqual(self._reranker([]).rerank("q", []), [])

    def test_pairs_use_query_and_text(self):
        reranker = self._reranker([0.1, 0.8])
        reranker.rerank("質問", self._results())
        pairs = reranker.model.predict.call_args[0][0]
        self.assertEqual(pairs, [("質問", "t0"), ("質問", "t1")])

    def test_does_not_mutate_input(self):
        results = self._results()
        self._reranker([0.1, 0.8]).rerank("q", results)
        self.assertEqual([r["rank"] for r in results], [1, 2])


def _http_error(code):
    return urllib.error.HTTPError(
        url="http://x", code=code, msg="err", hdrs=None, fp=io.BytesIO(b"body")
    )


def _ok_response(content):
    resp = MagicMock()
    resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode("utf-8")
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda *a: False
    return resp


class GenerateAnswerTest(SimpleTestCase):
    def test_returns_stripped_content(self):
        with patch.object(openai_client, "_get_api_key", return_value="k"), \
             patch.object(openai_client.urllib.request, "urlopen",
                          return_value=_ok_response("  回答  ")):
            self.assertEqual(openai_client.generate_answer("p"), "回答")

    def test_401_and_429_raise_runtime_error(self):
        for code in (401, 429):
            with self.subTest(code=code):
                with patch.object(openai_client, "_get_api_key", return_value="k"), \
                     patch.object(openai_client.urllib.request, "urlopen",
                                  side_effect=_http_error(code)):
                    with self.assertRaises(RuntimeError):
                        openai_client.generate_answer("p")

    def test_other_http_error_raises_plain_exception(self):
        with patch.object(openai_client, "_get_api_key", return_value="k"), \
             patch.object(openai_client.urllib.request, "urlopen",
                          side_effect=_http_error(500)):
            with self.assertRaises(Exception) as cm:
                openai_client.generate_answer("p")
            self.assertNotIsInstance(cm.exception, RuntimeError)

    def test_missing_api_key_raises_value_error(self):
        with patch.object(openai_client, "config", return_value=""):
            with self.assertRaises(ValueError):
                openai_client.generate_answer("p")


class RewriteQueryTest(SimpleTestCase):
    def test_returns_rewritten(self):
        with patch.object(query_rewriter, "_get_api_key", return_value="k"), \
             patch.object(query_rewriter, "_call_api", return_value="書き直し"):
            self.assertEqual(query_rewriter.rewrite_query("元"), "書き直し")

    def test_falls_back_to_original_on_error(self):
        with patch.object(query_rewriter, "_get_api_key", side_effect=Exception("boom")):
            self.assertEqual(query_rewriter.rewrite_query("元クエリ"), "元クエリ")

    def test_falls_back_on_api_error(self):
        with patch.object(query_rewriter, "_get_api_key", return_value="k"), \
             patch.object(query_rewriter, "_call_api", side_effect=_http_error(500)):
            self.assertEqual(query_rewriter.rewrite_query("元クエリ"), "元クエリ")


class GenerateQueriesTest(SimpleTestCase):
    def _generate(self, response):
        with patch.object(query_rewriter, "_get_api_key", return_value="k"), \
             patch.object(query_rewriter, "_call_api", return_value=response):
            return query_rewriter.generate_queries("元")

    def test_strips_numeric_prefixes(self):
        self.assertEqual(self._generate("1. A\n2. B\n3. C"), ["A", "B", "C"])

    def test_strips_paren_prefixes(self):
        self.assertEqual(self._generate("1) A\n2) B"), ["A", "B"])

    def test_strips_hyphen_prefix(self):
        self.assertEqual(self._generate("- A\n- B"), ["A", "B"])

    def test_skips_blank_lines(self):
        self.assertEqual(self._generate("A\n\n\nB"), ["A", "B"])

    def test_plain_lines_pass_through(self):
        self.assertEqual(self._generate("質問A\n質問B"), ["質問A", "質問B"])

    def test_only_first_matching_prefix_is_removed(self):
        # プレフィックス除去は1回だけ
        self.assertEqual(self._generate("1. - A"), ["- A"])

    def test_line_that_is_only_a_prefix_is_dropped(self):
        self.assertEqual(self._generate("-\nA"), ["A"])

    def test_returns_empty_list_on_error(self):
        with patch.object(query_rewriter, "_get_api_key", side_effect=Exception("boom")):
            self.assertEqual(query_rewriter.generate_queries("元"), [])
