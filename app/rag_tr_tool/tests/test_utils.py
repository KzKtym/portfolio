"""層B: utils/*。ログ書式・保存・SPEC抽出。

いずれも例外を出さずに内容だけが狂う種類のコード。
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from app.rag_tr_tool.utils import answers_store, log_formatter, rewrite_store, spec_extractor
from app.rag_tr_tool.utils.log_formatter import (
    format_log_form1,
    format_log_form2,
    format_log_full,
    get_logs_dir,
    read_details_json,
    read_log,
)


def detail(query="Q1", correct_rank=1, mrr=1.0, results=None):
    return {
        "query": query,
        "correct_rank": correct_rank,
        "mrr": mrr,
        "results": results if results is not None
        else [{"rank": 1, "score": 0.9, "source": "s0.md", "text": "本文0"}],
    }


LOG_KWARGS = dict(
    total_chunks=100,
    index_creation_time="0:00:05",
    evaluation_time_sec=1.5,
    query_count=2,
    mrr=0.75,
    recall_at_5=1.0,
)


class LogsDirTest(SimpleTestCase):
    def test_path_layout(self):
        self.assertEqual(get_logs_dir(3).parts[-2:], ("pj_3", "logs"))


class FormatLogForm1Test(SimpleTestCase):
    def test_header_lines(self):
        text = format_log_form1(details=[detail()], **LOG_KWARGS)
        self.assertIn("Index creation time : 0:00:05", text)
        self.assertIn("Total chunks : 100", text)
        self.assertIn("MRR : 0.75  Recall@5 : 1.0  (2 queries / 1.5s)", text)

    def test_index_creation_time_omitted_when_none(self):
        text = format_log_form1(details=[detail()], **{**LOG_KWARGS, "index_creation_time": None})
        self.assertNotIn("Index creation time", text)

    def test_query_numbering_is_one_based(self):
        text = format_log_form1(details=[detail("A"), detail("B")], **LOG_KWARGS)
        self.assertIn("Query 1: A", text)
        self.assertIn("Query 2: B", text)

    def test_correct_rank_none_shows_hyphen(self):
        text = format_log_form1(details=[detail(correct_rank=None, mrr=0.0)], **LOG_KWARGS)
        self.assertIn("Correct No: -", text)

    def test_mrr_fallback_from_correct_rank(self):
        # mrr キーが無い過去データは correct_rank から逆数を計算する
        d = detail(correct_rank=4)
        del d["mrr"]
        text = format_log_form1(details=[d], **LOG_KWARGS)
        self.assertIn("MRR: 0.2500", text)

    def test_mrr_fallback_zero_when_no_correct_rank(self):
        d = detail(correct_rank=None)
        del d["mrr"]
        text = format_log_form1(details=[d], **LOG_KWARGS)
        self.assertIn("MRR: 0.0000", text)

    def test_result_rows_are_rendered(self):
        text = format_log_form1(details=[detail()], **LOG_KWARGS)
        self.assertIn("rank", text)
        self.assertIn("s0.md", text)

    def test_does_not_include_text_body(self):
        text = format_log_form1(details=[detail()], **LOG_KWARGS)
        self.assertNotIn("本文0", text)

    def test_empty_details(self):
        text = format_log_form1(details=[], **LOG_KWARGS)
        self.assertIn("Total chunks : 100", text)


class FormatLogForm2Test(SimpleTestCase):
    def test_includes_text_body(self):
        text = format_log_form2(details=[detail()], **LOG_KWARGS)
        self.assertIn("本文0", text)
        self.assertIn("--- Rank 1 ---", text)
        self.assertIn("Source: s0.md", text)

    def test_missing_text_key_is_tolerated(self):
        d = detail(results=[{"rank": 1, "score": 0.9, "source": "s0.md"}])
        text = format_log_form2(details=[d], **LOG_KWARGS)
        self.assertIn("Text:", text)

    def test_mrr_fallback_from_correct_rank(self):
        d = detail(correct_rank=2)
        del d["mrr"]
        text = format_log_form2(details=[d], **LOG_KWARGS)
        self.assertIn("MRR: 0.5000", text)


class FormatLogFullTest(SimpleTestCase):
    def test_contains_both_formats(self):
        text = format_log_full(details=[detail()], **LOG_KWARGS)
        self.assertIn("FORMAT 1 (Table)", text)
        self.assertIn("FORMAT 2 (With Text)", text)
        # 書式2 のみが本文を含む
        self.assertIn("本文0", text)

    def test_format1_appears_before_format2(self):
        text = format_log_full(details=[detail()], **LOG_KWARGS)
        self.assertLess(text.index("FORMAT 1"), text.index("FORMAT 2"))


class LogFileIOTest(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(log_formatter, "_DATA_DIR", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logs_dir = get_logs_dir(1)
        self.logs_dir.mkdir(parents=True)

    def test_read_log_returns_none_when_missing(self):
        self.assertIsNone(read_log(1, 1))

    def test_read_log_returns_content(self):
        (self.logs_dir / "exp_1.log").write_text("ログ本文", encoding="utf-8")
        self.assertEqual(read_log(1, 1), "ログ本文")

    def test_read_details_json_returns_none_when_missing(self):
        self.assertIsNone(read_details_json(1, 1))

    def test_read_details_json_returns_parsed(self):
        (self.logs_dir / "exp_1.json").write_text(
            json.dumps({"details": [{"query": "Q"}], "meta": {}}), encoding="utf-8"
        )
        self.assertEqual(read_details_json(1, 1)["details"], [{"query": "Q"}])


class AnswersStoreTest(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(log_formatter, "_DATA_DIR", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logs_dir = get_logs_dir(1)

    def test_save_creates_file(self):
        answers_store.save_answers_json(1, [{"query": "Q", "answer": "A"}], project_id=1)
        self.assertTrue((self.logs_dir / "exp_1_answers.json").exists())

    def test_read_returns_saved_answers(self):
        answers_store.save_answers_json(1, [{"query": "Q", "answer": "A"}], project_id=1)
        self.assertEqual(answers_store.read_answers_json(1, project_id=1),
                         [{"query": "Q", "answer": "A"}])

    def test_read_returns_none_when_missing(self):
        self.assertIsNone(answers_store.read_answers_json(99, project_id=1))

    def test_existing_file_is_rotated_to_bak(self):
        answers_store.save_answers_json(1, [{"query": "Q", "answer": "旧"}], project_id=1)
        answers_store.save_answers_json(1, [{"query": "Q", "answer": "新"}], project_id=1)
        bak = json.loads((self.logs_dir / "exp_1_answers.bak").read_text(encoding="utf-8"))
        self.assertEqual(bak["answers"][0]["answer"], "旧")
        self.assertEqual(answers_store.read_answers_json(1, project_id=1)[0]["answer"], "新")

    def test_bak_is_overwritten_on_third_save(self):
        for label in ("1回目", "2回目", "3回目"):
            answers_store.save_answers_json(1, [{"query": "Q", "answer": label}], project_id=1)
        bak = json.loads((self.logs_dir / "exp_1_answers.bak").read_text(encoding="utf-8"))
        self.assertEqual(bak["answers"][0]["answer"], "2回目")


class RewriteStoreIOTest(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(log_formatter, "_DATA_DIR", Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logs_dir = get_logs_dir(1)

    def test_save_and_read(self):
        rewrite_store.save_rwa_json(1, [{"query": "Q"}], project_id=1)
        self.assertEqual(rewrite_store.read_rwa_json(1, project_id=1), [{"query": "Q"}])

    def test_read_returns_none_when_missing(self):
        self.assertIsNone(rewrite_store.read_rwa_json(99, project_id=1))

    def test_reads_legacy_dict_format(self):
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "exp_1_rewrite.json").write_text(
            json.dumps({"queries": [{"query": "旧形式"}]}), encoding="utf-8"
        )
        self.assertEqual(rewrite_store.read_rwa_json(1, project_id=1),
                         [{"query": "旧形式"}])


class CalcRewriteDataTest(SimpleTestCase):
    def _entry(self, mrr_original, mrr_rewrite, original=None, rewrite=None, relevant=None):
        return {
            "mrr_original": mrr_original,
            "mrr_rewrite": mrr_rewrite,
            "relevant_sources": relevant if relevant is not None else ["s1.md"],
            "results_original": original if original is not None
            else [{"rank": 1, "source": "s0.md"}],
            "results_rewrite": rewrite if rewrite is not None
            else [{"rank": 1, "source": "s0.md"}],
        }

    def test_counts_improved_degraded_unchanged(self):
        data = [self._entry(0.5, 1.0), self._entry(1.0, 0.5), self._entry(0.5, 0.5)]
        _, summary = rewrite_store.calc_rewrite_data(data)
        self.assertEqual(summary["improved"], 1)
        self.assertEqual(summary["degraded"], 1)
        self.assertEqual(summary["unchanged"], 1)

    def test_is_new_flag_and_gain_count(self):
        data = [self._entry(
            0.5, 1.0,
            original=[{"rank": 1, "source": "s0.md"}],
            rewrite=[{"rank": 1, "source": "s0.md"}, {"rank": 2, "source": "s9.md"}],
        )]
        out, summary = rewrite_store.calc_rewrite_data(data)
        flags = [r["is_new"] for r in out[0]["results_rewrite"]]
        self.assertEqual(flags, [False, True])
        self.assertEqual(summary["gain"], 1)

    def test_ranks_of_relevant_source(self):
        data = [self._entry(
            0.5, 1.0,
            original=[{"rank": 1, "source": "s0.md"}, {"rank": 2, "source": "s1.md"}],
            rewrite=[{"rank": 1, "source": "s1.md"}],
            relevant=["s1.md"],
        )]
        out, _ = rewrite_store.calc_rewrite_data(data)
        self.assertEqual(out[0]["original_rank"], 2)
        self.assertEqual(out[0]["rewrite_rank"], 1)

    def test_rank_is_none_when_not_hit(self):
        data = [self._entry(0.0, 0.0, relevant=["zzz.md"])]
        out, _ = rewrite_store.calc_rewrite_data(data)
        self.assertIsNone(out[0]["original_rank"])
        self.assertIsNone(out[0]["rewrite_rank"])

    def test_mrr_delta_and_gain_flag(self):
        out, _ = rewrite_store.calc_rewrite_data([self._entry(0.25, 1.0)])
        self.assertAlmostEqual(out[0]["mrr_delta"], 0.75)
        self.assertTrue(out[0]["rewrite_gain"])

    def test_gain_flag_false_when_unchanged(self):
        out, _ = rewrite_store.calc_rewrite_data([self._entry(0.5, 0.5)])
        self.assertFalse(out[0]["rewrite_gain"])

    def test_missing_relevant_sources_is_tolerated(self):
        entry = self._entry(0.5, 1.0)
        del entry["relevant_sources"]
        out, _ = rewrite_store.calc_rewrite_data([entry])
        self.assertIsNone(out[0]["original_rank"])

    def test_empty_input(self):
        out, summary = rewrite_store.calc_rewrite_data([])
        self.assertEqual(out, [])
        self.assertEqual(summary,
                         {"improved": 0, "degraded": 0, "unchanged": 0, "gain": 0})


class SpecExtractorTreeTest(SimpleTestCase):
    def test_insert_tree_uses_leading_digit_as_order(self):
        tree = {}
        spec_extractor.insert_tree(tree, ["20", "VectorStore", "FAISS"])
        self.assertIn("VectorStore", tree)
        self.assertNotIn("20", tree)
        self.assertEqual(tree["VectorStore"]["_order"], 20)

    def test_insert_tree_without_order(self):
        tree = {}
        spec_extractor.insert_tree(tree, ["Chunking"])
        self.assertEqual(tree["Chunking"]["_order"], 0)

    def test_format_tree_sorts_by_order(self):
        tree = {}
        spec_extractor.insert_tree(tree, ["40", "Retrieval"])
        spec_extractor.insert_tree(tree, ["20", "VectorStore"])
        lines = spec_extractor.format_tree(tree)
        self.assertEqual(lines, ["* VectorStore", "* Retrieval"])

    def test_format_tree_indents_children(self):
        tree = {}
        spec_extractor.insert_tree(tree, ["20", "VectorStore", "FAISS"])
        self.assertEqual(spec_extractor.format_tree(tree),
                         ["* VectorStore", "  * FAISS"])

    def test_tag_param_map_covers_documented_tags(self):
        # タグ追加時のマッピング漏れを検出する
        self.assertEqual(spec_extractor._TAG_PARAM_MAP["legacy"], "chunker")
        self.assertEqual(spec_extractor._TAG_PARAM_MAP["hybrid"], "search_type")
        self.assertEqual(spec_extractor._TAG_PARAM_MAP["cross"], "reranker")


class SpecExtractorScanFileTest(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sample.py"

    def _scan(self, source, **filters):
        self.path.write_text(source, encoding="utf-8")
        tree = {}
        spec_extractor.scan_file(str(self.path), tree, **filters)
        return spec_extractor.format_tree(tree)

    def test_plain_spec_is_always_emitted(self):
        self.assertEqual(self._scan("# SPEC: 20/VectorStore"), ["* VectorStore"])

    def test_conditional_spec_emitted_when_tag_matches(self):
        lines = self._scan("# SPEC_legacy: 30/Chunking", chunker="legacy")
        self.assertEqual(lines, ["* Chunking"])

    def test_conditional_spec_skipped_when_tag_differs(self):
        lines = self._scan("# SPEC_legacy: 30/Chunking", chunker="langchain")
        self.assertEqual(lines, [])

    def test_conditional_spec_emitted_when_filter_is_none(self):
        # フィルタ未指定なら全出力
        self.assertEqual(self._scan("# SPEC_legacy: 30/Chunking"), ["* Chunking"])

    def test_disabled_sentinel_suppresses_all_tags(self):
        lines = self._scan("# SPEC_rewrite: 35/Query Rewrite", query_option="__disabled__")
        self.assertEqual(lines, [])

    def test_unknown_tag_is_always_emitted(self):
        lines = self._scan("# SPEC_unknown_tag: 10/Always", chunker="legacy")
        self.assertEqual(lines, ["* Always"])

    def test_non_spec_comments_are_ignored(self):
        self.assertEqual(self._scan("# ただのコメント\nx = 1"), [])
