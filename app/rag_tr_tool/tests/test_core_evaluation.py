"""層B: core/evaluation の純ロジック（外部依存ゼロ）。

実験を回しても正しさが分からず、間違っても例外を出さずに数字だけが狂う箇所。
テストの価値が最も高いため SimpleTestCase で網羅する。
"""
from django.test import SimpleTestCase

from app.rag_tr_tool.core.evaluation.metrics import reciprocal_rank, recall_at_k
from app.rag_tr_tool.core.evaluation.params import EvalParams
from app.rag_tr_tool.core.evaluation.query_logic import (
    is_gated,
    merge_by_score,
    merge_results,
    normalize_query_option,
)


def hit(rank, source, score=0.5, text=""):
    """検索結果1件分のダミー。"""
    return {"rank": rank, "score": score, "text": text, "metadata": {"source": source}}


class ReciprocalRankTest(SimpleTestCase):
    def test_returns_zero_when_no_hit(self):
        results = [hit(1, "a.md"), hit(2, "b.md")]
        self.assertEqual(reciprocal_rank(results, ["z.md"]), 0.0)

    def test_returns_one_when_hit_at_rank1(self):
        results = [hit(1, "a.md"), hit(2, "b.md")]
        self.assertEqual(reciprocal_rank(results, ["a.md"]), 1.0)

    def test_uses_rank_field_not_list_position(self):
        # rank はフィルタ後に振り直される場合があるため、リスト位置ではなく rank を見る
        results = [hit(3, "a.md"), hit(4, "b.md")]
        self.assertAlmostEqual(reciprocal_rank(results, ["a.md"]), 1 / 3)

    def test_returns_first_hit_only(self):
        results = [hit(1, "a.md"), hit(2, "b.md")]
        # 両方 relevant でも先頭のみ採用
        self.assertEqual(reciprocal_rank(results, ["a.md", "b.md"]), 1.0)

    def test_empty_results(self):
        self.assertEqual(reciprocal_rank([], ["a.md"]), 0.0)

    def test_empty_relevant_sources(self):
        self.assertEqual(reciprocal_rank([hit(1, "a.md")], []), 0.0)


class RecallAtKTest(SimpleTestCase):
    def test_hit_inside_k(self):
        results = [hit(1, "a.md"), hit(2, "b.md"), hit(3, "c.md")]
        self.assertEqual(recall_at_k(results, ["c.md"], 3), 1)

    def test_hit_outside_k_is_not_counted(self):
        results = [hit(1, "a.md"), hit(2, "b.md"), hit(3, "c.md")]
        self.assertEqual(recall_at_k(results, ["c.md"], 2), 0)

    def test_k_boundary_is_inclusive(self):
        results = [hit(1, "a.md"), hit(2, "b.md")]
        self.assertEqual(recall_at_k(results, ["b.md"], 2), 1)

    def test_k_zero_returns_zero(self):
        self.assertEqual(recall_at_k([hit(1, "a.md")], ["a.md"], 0), 0)

    def test_slices_by_list_position_not_rank(self):
        # recall は results[:k] でスライスする。rank 値ではなくリスト位置で切られる
        results = [hit(10, "a.md"), hit(11, "b.md")]
        self.assertEqual(recall_at_k(results, ["b.md"], 1), 0)

    def test_empty_results(self):
        self.assertEqual(recall_at_k([], ["a.md"], 5), 0)


class NormalizeQueryOptionTest(SimpleTestCase):
    def test_multi(self):
        self.assertEqual(normalize_query_option("multi"), "multi")
        self.assertEqual(normalize_query_option("MULTI"), "multi")

    def test_rewrite_aliases(self):
        # 旧表記 "true" は "rewrite" に正規化される
        self.assertEqual(normalize_query_option("rewrite"), "rewrite")
        self.assertEqual(normalize_query_option("true"), "rewrite")
        self.assertEqual(normalize_query_option("TRUE"), "rewrite")

    def test_unknown_string_is_none(self):
        self.assertIsNone(normalize_query_option("false"))
        self.assertIsNone(normalize_query_option(""))

    def test_non_string_is_truthiness(self):
        self.assertEqual(normalize_query_option(True), "rewrite")
        self.assertIsNone(normalize_query_option(False))
        self.assertIsNone(normalize_query_option(None))


class IsGatedTest(SimpleTestCase):
    def setUp(self):
        # top1=0.9, margin=0.9-0.4=0.5
        self.results = [hit(1, "a.md", 0.9), hit(2, "b.md", 0.4)]

    def test_gate_mode_none_never_gates(self):
        gated, t1, mg = is_gated(self.results, None, 0.1, 0.1)
        self.assertFalse(gated)
        self.assertAlmostEqual(t1, 0.9)
        self.assertAlmostEqual(mg, 0.5)

    def test_top1_mode(self):
        self.assertTrue(is_gated(self.results, "top1", 0.5, 0.0)[0])
        self.assertFalse(is_gated(self.results, "top1", 0.95, 0.0)[0])

    def test_top1_boundary_is_strict(self):
        # 閾値ちょうどは gated にならない（> 判定）
        self.assertFalse(is_gated(self.results, "top1", 0.9, 0.0)[0])

    def test_margin_mode(self):
        self.assertTrue(is_gated(self.results, "margin", 0.0, 0.4)[0])
        self.assertFalse(is_gated(self.results, "margin", 0.0, 0.6)[0])

    def test_standard_mode_requires_both(self):
        self.assertTrue(is_gated(self.results, "standard", 0.5, 0.4)[0])
        # top1 は満たすが margin が足りない
        self.assertFalse(is_gated(self.results, "standard", 0.5, 0.6)[0])
        # margin は満たすが top1 が足りない
        self.assertFalse(is_gated(self.results, "standard", 0.95, 0.4)[0])

    def test_single_result_uses_top1_as_margin(self):
        single = [hit(1, "a.md", 0.7)]
        _, t1, mg = is_gated(single, None, 1.1, 0.0)
        self.assertAlmostEqual(t1, 0.7)
        self.assertAlmostEqual(mg, 0.7)

    def test_empty_results_returns_not_gated(self):
        # 元クエリで何も引けていない以上、Multi Query を禁止する理由が無い
        self.assertEqual(is_gated([], "standard", 0.5, 0.4), (False, 0.0, 0.0))
        self.assertEqual(is_gated([], None, 0.5, 0.4), (False, 0.0, 0.0))

    def test_unknown_gate_mode_raises(self):
        with self.assertRaises(AssertionError):
            is_gated(self.results, "bogus", 0.5, 0.4)


class MergeResultsTest(SimpleTestCase):
    def test_duplicate_source_keeps_original(self):
        original = [hit(1, "a.md", 0.9)]
        rewrite = [hit(1, "a.md", 0.1), hit(2, "b.md", 0.8)]
        merged = merge_results(original, rewrite, 10)
        self.assertEqual([r["metadata"]["source"] for r in merged], ["a.md", "b.md"])
        # a.md は original 側のスコアが残る
        self.assertAlmostEqual(merged[0]["score"], 0.9)

    def test_rank_is_renumbered(self):
        original = [hit(5, "a.md")]
        rewrite = [hit(9, "b.md")]
        merged = merge_results(original, rewrite, 10)
        self.assertEqual([r["rank"] for r in merged], [1, 2])

    def test_truncated_to_top_k(self):
        original = [hit(1, "a.md"), hit(2, "b.md")]
        rewrite = [hit(1, "c.md")]
        merged = merge_results(original, rewrite, 2)
        self.assertEqual(len(merged), 2)
        self.assertEqual([r["rank"] for r in merged], [1, 2])

    def test_empty_inputs(self):
        self.assertEqual(merge_results([], [], 5), [])


class MergeByScoreTest(SimpleTestCase):
    def test_minmax_normalization_per_group(self):
        # group0 は 0.9/0.1 → 1.0/0.0、group1 は 0.5/0.3 → 1.0/0.0 に正規化される
        g0 = [hit(1, "a.md", 0.9), hit(2, "b.md", 0.1)]
        g1 = [hit(1, "c.md", 0.5), hit(2, "d.md", 0.3)]
        merged, gated, _, _ = merge_by_score([g0, g1], 10, normalize="minmax")
        self.assertFalse(gated)
        by_source = {r["metadata"]["source"]: r["score"] for r in merged}
        self.assertAlmostEqual(by_source["a.md"], 1.0)
        self.assertAlmostEqual(by_source["b.md"], 0.0)
        self.assertAlmostEqual(by_source["c.md"], 1.0)
        self.assertAlmostEqual(by_source["d.md"], 0.0)

    def test_all_same_score_uses_denom_one(self):
        # s_max == s_min のとき denom=1.0 とし、ゼロ除算を避ける
        g0 = [hit(1, "a.md", 0.5), hit(2, "b.md", 0.5)]
        merged, _, _, _ = merge_by_score([g0], 10, normalize="minmax")
        self.assertEqual([r["score"] for r in merged], [0.0, 0.0])

    def test_normalize_none_keeps_raw_scores(self):
        g0 = [hit(1, "a.md", 0.9)]
        g1 = [hit(1, "b.md", 0.4)]
        merged, _, _, _ = merge_by_score([g0, g1], 10, normalize="none")
        by_source = {r["metadata"]["source"]: r["score"] for r in merged}
        self.assertAlmostEqual(by_source["a.md"], 0.9)
        self.assertAlmostEqual(by_source["b.md"], 0.4)

    def test_weighted_mode_discounts_generated_only(self):
        # generated 側だけ 0.8 倍。original(index 0) は等倍
        g0 = [hit(1, "a.md", 1.0)]
        g1 = [hit(1, "b.md", 1.0)]
        merged, _, _, _ = merge_by_score(
            [g0, g1], 10, normalize="none", merge_mode="weighted"
        )
        by_source = {r["metadata"]["source"]: r["score"] for r in merged}
        self.assertAlmostEqual(by_source["a.md"], 1.0)
        self.assertAlmostEqual(by_source["b.md"], 0.8)

    def test_same_source_takes_max_across_groups(self):
        g0 = [hit(1, "a.md", 0.2)]
        g1 = [hit(1, "a.md", 0.7)]
        merged, _, _, _ = merge_by_score([g0, g1], 10, normalize="none")
        self.assertEqual(len(merged), 1)
        self.assertAlmostEqual(merged[0]["score"], 0.7)

    def test_original_boost_applied_above_threshold(self):
        g0 = [hit(1, "a.md", 0.5)]
        merged, _, _, _ = merge_by_score(
            [g0], 10, normalize="none", original_boost=2.0, boost_threshold=0.4
        )
        self.assertAlmostEqual(merged[0]["score"], 1.0)

    def test_original_boost_skipped_below_threshold(self):
        g0 = [hit(1, "a.md", 0.3)]
        merged, _, _, _ = merge_by_score(
            [g0], 10, normalize="none", original_boost=2.0, boost_threshold=0.4
        )
        self.assertAlmostEqual(merged[0]["score"], 0.3)

    def test_rank_renumbered_and_truncated(self):
        g0 = [hit(7, "a.md", 0.9), hit(8, "b.md", 0.5), hit(9, "c.md", 0.1)]
        merged, _, _, _ = merge_by_score([g0], 2, normalize="none")
        self.assertEqual([r["rank"] for r in merged], [1, 2])
        self.assertEqual([r["metadata"]["source"] for r in merged], ["a.md", "b.md"])

    def test_gate_score_raw_does_not_gate_here(self):
        # gate_score="raw" のときは呼び出し側が is_gated() を使う契約
        g0 = [hit(1, "a.md", 0.9), hit(2, "b.md", 0.1)]
        _, gated, t1, mg = merge_by_score(
            [g0], 10, gate_score="raw", gate_mode="top1", gate_top1=0.0
        )
        self.assertFalse(gated)
        self.assertEqual((t1, mg), (0.0, 0.0))

    def test_gate_score_normalized_gates_on_normalized_scores(self):
        g0 = [hit(1, "a.md", 0.9), hit(2, "b.md", 0.1)]
        g1 = [hit(1, "c.md", 0.5)]
        merged, gated, t1, mg = merge_by_score(
            [g0, g1], 10, gate_score="normalized", gate_mode="top1", gate_top1=0.5
        )
        # 正規化後の top1 は 1.0 > 0.5 なので gated
        self.assertTrue(gated)
        self.assertAlmostEqual(t1, 1.0)
        # gated 時は統合せず original のみを返す
        self.assertEqual([r["metadata"]["source"] for r in merged], ["a.md", "b.md"])

    def test_gate_score_normalized_without_gate_mode_does_not_gate(self):
        g0 = [hit(1, "a.md", 0.9)]
        _, gated, _, _ = merge_by_score(
            [g0], 10, gate_score="normalized", gate_mode=None
        )
        self.assertFalse(gated)

    def test_empty_group_is_tolerated(self):
        # 生成クエリが1件も引けないケース
        g0 = [hit(1, "a.md", 0.9)]
        for normalize in ("minmax", "none"):
            with self.subTest(normalize=normalize):
                merged, gated, _, _ = merge_by_score([g0, []], 10, normalize=normalize)
                self.assertFalse(gated)
                self.assertEqual([r["metadata"]["source"] for r in merged], ["a.md"])

    def test_all_groups_empty(self):
        for normalize in ("minmax", "none"):
            with self.subTest(normalize=normalize):
                merged, gated, _, _ = merge_by_score([[], []], 10, normalize=normalize)
                self.assertEqual(merged, [])
                self.assertFalse(gated)

    def test_empty_original_with_normalized_gate(self):
        # groups[0] が空でも gate 判定で IndexError にならない
        merged, gated, t1, mg = merge_by_score(
            [[], [hit(1, "a.md", 0.5)]], 10,
            gate_score="normalized", gate_mode="top1", gate_top1=0.1,
        )
        self.assertFalse(gated)
        self.assertEqual((t1, mg), (0.0, 0.0))
        self.assertEqual([r["metadata"]["source"] for r in merged], ["a.md"])


class EvalParamsNormalizeTest(SimpleTestCase):
    def test_strips_quotes_from_keys_and_values(self):
        out = EvalParams.normalize({'"top_k"': '"5"', "'search_type'": "'mmr'"})
        self.assertEqual(out, {"top_k": 5, "search_type": "mmr"})

    def test_digit_string_becomes_int(self):
        self.assertEqual(EvalParams.normalize({"top_k": "5"})["top_k"], 5)

    def test_decimal_string_becomes_float(self):
        self.assertAlmostEqual(EvalParams.normalize({"lambda_mult": "0.5"})["lambda_mult"], 0.5)

    def test_integral_float_becomes_int(self):
        # キャッシュキー一致のため 5.0 は 5 に落とす
        out = EvalParams.normalize({"top_k": 5.0, "fetch_k": "20.0"})
        self.assertEqual(out["top_k"], 5)
        self.assertEqual(out["fetch_k"], 20)
        self.assertIsInstance(out["top_k"], int)

    def test_non_numeric_string_passes_through(self):
        self.assertEqual(EvalParams.normalize({"search_type": "hybrid"})["search_type"], "hybrid")

    def test_non_string_values_pass_through(self):
        out = EvalParams.normalize({"flag": True, "none": None, "items": [1, 2]})
        self.assertEqual(out, {"flag": True, "none": None, "items": [1, 2]})

    def test_whitespace_is_stripped(self):
        self.assertEqual(EvalParams.normalize({" top_k ": " 5 "})["top_k"], 5)


class EvalParamsFromDictTest(SimpleTestCase):
    def test_defaults(self):
        p = EvalParams.from_dict({})
        self.assertEqual(p.top_k, 5)
        self.assertEqual(p.search_type, "similarity")
        self.assertIsNone(p.query_option)
        self.assertIsNone(p.gate_mode)
        self.assertIsNone(p.reranker)
        self.assertFalse(p.skip_no_answer)

    def test_query_option_is_normalized(self):
        self.assertEqual(EvalParams.from_dict({"query_option": "true"}).query_option, "rewrite")
        self.assertEqual(EvalParams.from_dict({"query_option": "multi"}).query_option, "multi")

    def test_gate_mode_inferred_from_both(self):
        p = EvalParams.from_dict({"gate_top1": 0.8, "gate_margin": 0.2})
        self.assertEqual(p.gate_mode, "standard")

    def test_gate_mode_inferred_from_top1_only(self):
        self.assertEqual(EvalParams.from_dict({"gate_top1": 0.8}).gate_mode, "top1")

    def test_gate_mode_inferred_from_margin_only(self):
        self.assertEqual(EvalParams.from_dict({"gate_margin": 0.2}).gate_mode, "margin")

    def test_gate_mode_not_inferred_when_absent(self):
        self.assertIsNone(EvalParams.from_dict({"top_k": 5}).gate_mode)

    def test_explicit_gate_mode_wins_over_inference(self):
        p = EvalParams.from_dict({"gate_mode": "top1", "gate_top1": 0.8, "gate_margin": 0.2})
        self.assertEqual(p.gate_mode, "top1")

    def test_skip_no_answer_string_parsing(self):
        self.assertTrue(EvalParams.from_dict({"skip_no_answer": "true"}).skip_no_answer)
        self.assertTrue(EvalParams.from_dict({"skip_no_answer": "TRUE"}).skip_no_answer)
        self.assertTrue(EvalParams.from_dict({"skip_no_answer": True}).skip_no_answer)
        self.assertFalse(EvalParams.from_dict({"skip_no_answer": "false"}).skip_no_answer)
        self.assertFalse(EvalParams.from_dict({"skip_no_answer": ""}).skip_no_answer)

    def test_reranker_falsy_becomes_none(self):
        self.assertIsNone(EvalParams.from_dict({"reranker": ""}).reranker)
        self.assertIsNone(EvalParams.from_dict({"reranker": None}).reranker)
        self.assertEqual(EvalParams.from_dict({"reranker": "cross"}).reranker, "cross")

    def test_optional_numerics_stay_none_when_absent(self):
        p = EvalParams.from_dict({})
        self.assertIsNone(p.score_threshold)
        self.assertIsNone(p.candidate_k)

    def test_optional_numerics_none_value_stays_none(self):
        p = EvalParams.from_dict({"score_threshold": None, "candidate_k": None})
        self.assertIsNone(p.score_threshold)
        self.assertIsNone(p.candidate_k)

    def test_optional_numerics_are_cast(self):
        p = EvalParams.from_dict({"score_threshold": "0.3", "candidate_k": "30"})
        self.assertAlmostEqual(p.score_threshold, 0.3)
        self.assertEqual(p.candidate_k, 30)

    def test_numeric_strings_are_cast(self):
        p = EvalParams.from_dict({"top_k": "7", "lambda_mult": "0.25", "rrf_k": "10"})
        self.assertEqual(p.top_k, 7)
        self.assertAlmostEqual(p.lambda_mult, 0.25)
        self.assertEqual(p.rrf_k, 10)
