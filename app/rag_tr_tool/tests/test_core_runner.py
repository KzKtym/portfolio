"""層B: evaluation/runner の分岐。

build_index / Retriever / rewrite 系をモックし、外部依存なしで経路だけを検証する。
特に status="error" 経路は、失敗が「成功」として保存される事故の起点だったため重点的に固定する。
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from app.rag_tr_tool.core.evaluation import runner


def hit(rank, source, score=0.9, text="本文"):
    return {"rank": rank, "score": score, "text": text, "metadata": {"source": source}}


class RunEvaluationTestBase(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        (self.data_dir / "pj_1").mkdir(parents=True)
        self._write_queries([
            {"query": "質問1", "relevant_sources": ["s0.md"]},
        ])
        patcher = patch.object(runner, "_DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_queries(self, queries):
        (self.data_dir / "pj_1" / "evaluation_queries.json").write_text(
            json.dumps(queries, ensure_ascii=False), encoding="utf-8"
        )

    def _store(self, ntotal=10, texts=("あ" * 100, "い" * 200)):
        store = MagicMock()
        store.index.ntotal = ntotal
        store.texts = list(texts)
        return store

    def _run(self, params=None, results=None, store=None, retriever_side_effect=None):
        results = results if results is not None else [hit(1, "s0.md")]
        retriever = MagicMock()
        if retriever_side_effect is not None:
            retriever.search.side_effect = retriever_side_effect
        else:
            retriever.search.return_value = results
        retriever._bm25_fallback_count = 0
        retriever._bm25_fallback_query_indices = []
        with patch.object(runner, "build_index",
                          return_value=(store or self._store(), MagicMock(), "0:00:03")), \
             patch.object(runner, "Retriever", return_value=retriever):
            return runner.run_evaluation(params or {}, project_id=1), retriever


class RunEvaluationSuccessTest(RunEvaluationTestBase):
    def test_success_status_and_metrics(self):
        result, _ = self._run()
        self.assertEqual(result["status"], "success")
        self.assertAlmostEqual(result["metrics"]["mrr"], 1.0)
        self.assertAlmostEqual(result["metrics"]["recall_at_5"], 1.0)

    def test_meta_fields(self):
        result, _ = self._run()
        meta = result["meta"]
        self.assertEqual(meta["query_count"], 1)
        self.assertEqual(meta["total_chunks"], 10)
        self.assertEqual(meta["index_creation_time"], "0:00:03")
        self.assertEqual(meta["skipped_count"], 0)

    def test_chunk_stats(self):
        result, _ = self._run(store=self._store(texts=("a" * 100, "b" * 200)))
        self.assertEqual(result["meta"]["chunk_stats"],
                         {"avg": 150, "max": 200, "min": 100})

    def test_chunk_stats_empty_when_no_texts(self):
        result, _ = self._run(store=self._store(texts=()))
        self.assertEqual(result["meta"]["chunk_stats"], {"avg": 0, "max": 0, "min": 0})

    def test_details_contain_query_and_correct_rank(self):
        result, _ = self._run()
        d = result["details"][0]
        self.assertEqual(d["query"], "質問1")
        self.assertEqual(d["correct_rank"], 1)
        self.assertAlmostEqual(d["mrr"], 1.0)

    def test_detail_text_is_truncated(self):
        result, _ = self._run(results=[hit(1, "s0.md", text="あ" * 500)])
        self.assertEqual(len(result["details"][0]["results"][0]["text"]), 300)

    def test_miss_produces_zero_metrics(self):
        result, _ = self._run(results=[hit(1, "zzz.md")])
        self.assertAlmostEqual(result["metrics"]["mrr"], 0.0)
        self.assertIsNone(result["details"][0]["correct_rank"])

    def test_no_rwa_queries_for_plain_search(self):
        result, _ = self._run()
        self.assertEqual(result["rwa_queries"], [])


class RunEvaluationErrorTest(RunEvaluationTestBase):
    def test_build_index_failure_returns_error_status(self):
        with patch.object(runner, "build_index", side_effect=RuntimeError("boom")):
            result = runner.run_evaluation({}, project_id=1)
        self.assertEqual(result["status"], "error")
        self.assertIn("boom", result["error"])
        self.assertEqual(result["error_type"], "RuntimeError")

    def test_error_result_has_no_metrics_key(self):
        # metrics を返さないため、呼び出し側が 0.0 を保存できないようにしてある
        with patch.object(runner, "build_index", side_effect=RuntimeError("boom")):
            result = runner.run_evaluation({}, project_id=1)
        self.assertNotIn("metrics", result)

    def test_error_meta_is_zeroed(self):
        with patch.object(runner, "build_index", side_effect=RuntimeError("boom")):
            result = runner.run_evaluation({}, project_id=1)
        self.assertEqual(result["meta"]["query_count"], 0)
        self.assertEqual(result["meta"]["total_chunks"], 0)
        self.assertIsNone(result["meta"]["index_creation_time"])

    def test_missing_queries_file_is_reported_as_error(self):
        (self.data_dir / "pj_1" / "evaluation_queries.json").unlink()
        result, _ = self._run()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "FileNotFoundError")

    def test_search_failure_is_reported_as_error(self):
        result, _ = self._run(retriever_side_effect=ValueError("検索失敗"))
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_type"], "ValueError")

    def test_exception_is_logged_with_traceback(self):
        with patch.object(runner, "build_index", side_effect=RuntimeError("boom")), \
             self.assertLogs(runner.logger, level="ERROR") as cm:
            runner.run_evaluation({}, project_id=1)
        self.assertIn("run_evaluation failed", cm.output[0])
        self.assertIn("Traceback", cm.output[0])


class RunEvaluationSkipTest(RunEvaluationTestBase):
    def test_skip_no_answer_excludes_empty_relevant_sources(self):
        self._write_queries([
            {"query": "回答あり", "relevant_sources": ["s0.md"]},
            {"query": "回答なし", "relevant_sources": []},
        ])
        result, _ = self._run(params={"skip_no_answer": "true"})
        self.assertEqual(result["meta"]["skipped_count"], 1)
        self.assertEqual(result["meta"]["query_count"], 1)
        self.assertEqual(len(result["details"]), 1)

    def test_without_skip_flag_all_queries_are_evaluated(self):
        self._write_queries([
            {"query": "回答あり", "relevant_sources": ["s0.md"]},
            {"query": "回答なし", "relevant_sources": []},
        ])
        result, _ = self._run()
        self.assertEqual(result["meta"]["skipped_count"], 0)
        self.assertEqual(result["meta"]["query_count"], 2)

    def test_all_skipped_yields_zero_metrics_without_zero_division(self):
        self._write_queries([{"query": "回答なし", "relevant_sources": []}])
        result, _ = self._run(params={"skip_no_answer": "true"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["metrics"]["mrr"], 0.0)
        self.assertEqual(result["meta"]["query_count"], 0)


class RunEvaluationSearchParamsTest(RunEvaluationTestBase):
    def test_top_k_used_when_no_reranker_or_candidate_k(self):
        _, retriever = self._run(params={"top_k": 7})
        self.assertEqual(retriever.search.call_args.kwargs["k"], 7)

    def test_candidate_k_takes_priority_over_top_k(self):
        _, retriever = self._run(params={"top_k": 5, "candidate_k": 30})
        self.assertEqual(retriever.search.call_args.kwargs["k"], 30)

    def test_search_params_are_forwarded(self):
        _, retriever = self._run(params={
            "search_type": "hybrid", "fetch_k": 25, "lambda_mult": 0.3, "rrf_k": 10,
        })
        kwargs = retriever.search.call_args.kwargs
        self.assertEqual(kwargs["search_type"], "hybrid")
        self.assertEqual(kwargs["fetch_k"], 25)
        self.assertAlmostEqual(kwargs["lambda_mult"], 0.3)
        self.assertEqual(kwargs["rrf_k"], 10)


class RunEvaluationScoreThresholdTest(RunEvaluationTestBase):
    def test_filters_below_threshold(self):
        results = [hit(1, "s0.md", 1.0), hit(2, "s1.md", 0.9), hit(3, "s2.md", 0.0)]
        result, _ = self._run(params={"score_threshold": 0.5, "top_k": 5}, results=results)
        sources = [r["source"] for r in result["details"][0]["results"]]
        self.assertEqual(sources, ["s0.md", "s1.md"])

    def test_falls_back_to_unfiltered_when_all_filtered_out(self):
        # フィルタ後 0 件になる場合は元の結果を返す
        results = [hit(1, "s0.md", 1.0), hit(2, "s1.md", 1.0)]
        result, _ = self._run(params={"score_threshold": 1.5, "top_k": 5}, results=results)
        self.assertEqual(len(result["details"][0]["results"]), 2)

    def test_threshold_none_only_truncates_to_top_k(self):
        results = [hit(i + 1, f"s{i}.md", 1.0 - i * 0.1) for i in range(5)]
        result, _ = self._run(params={"top_k": 2}, results=results)
        self.assertEqual(len(result["details"][0]["results"]), 2)


class RunEvaluationRewriteTest(RunEvaluationTestBase):
    def test_rewrite_path_records_rwa_queries(self):
        with patch("app.rag_tr_tool.core.rewrite.query_rewriter.rewrite_query",
                   return_value="言い換え"):
            result, _ = self._run(params={"query_option": "rewrite"})
        self.assertEqual(result["status"], "success")
        rwa = result["rwa_queries"][0]
        self.assertEqual(rwa["mode"], "rewrite")
        self.assertEqual(rwa["rewrite_query"], "言い換え")
        self.assertIn("results_original", rwa)
        self.assertIn("results_rewrite", rwa)

    def test_multi_path_records_generated_queries(self):
        with patch("app.rag_tr_tool.core.rewrite.query_rewriter.generate_queries",
                   return_value=["生成1", "生成2"]):
            result, _ = self._run(params={"query_option": "multi"})
        self.assertEqual(result["status"], "success")
        rwa = result["rwa_queries"][0]
        self.assertEqual(rwa["mode"], "multi")
        self.assertEqual(rwa["generated_queries"], ["生成1", "生成2"])
        self.assertIn("gated", rwa)

    def test_multi_path_gated_skips_generation(self):
        # gate_top1 を下回らせて gated=True にする
        with patch("app.rag_tr_tool.core.rewrite.query_rewriter.generate_queries",
                   return_value=["生成1"]) as mock_gen:
            result, _ = self._run(params={
                "query_option": "multi", "gate_mode": "top1", "gate_top1": 0.5,
            })
        self.assertTrue(result["rwa_queries"][0]["gated"])
        self.assertEqual(result["rwa_queries"][0]["generated_queries"], [])
        mock_gen.assert_not_called()
