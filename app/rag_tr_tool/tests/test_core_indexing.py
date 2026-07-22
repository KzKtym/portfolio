"""層B: indexing / ingest / llm(prompt) / vectorstore。

index ディレクトリのハッシュ安定性は、実験の同一性判定そのもの。
ここが揺れると「同じ設定なのに別インデックス」「違う設定なのに同一インデックス」が起き、
比較実験の前提が崩れる。
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from app.rag_tr_tool.core import indexing
from app.rag_tr_tool.core.indexing.index_builder import (
    get_index_base_dir,
    get_index_dir,
    get_index_info,
)
from app.rag_tr_tool.core.ingest.loader import (
    load_markdown_documents,
    strip_frontmatter,
)
from app.rag_tr_tool.core.llm.prompt_template import build_prompt
from app.rag_tr_tool.core.vectorstore.faiss_store import FAISSStore


class GetIndexDirTest(SimpleTestCase):
    def test_key_order_does_not_change_hash(self):
        a = get_index_dir({"chunk_size": 500, "overlap": 100, "chunker": "legacy"}, 1)
        b = get_index_dir({"chunker": "legacy", "overlap": 100, "chunk_size": 500}, 1)
        self.assertEqual(a, b)

    def test_top_k_is_ignored(self):
        a = get_index_dir({"chunk_size": 500, "top_k": 5}, 1)
        b = get_index_dir({"chunk_size": 500, "top_k": 20}, 1)
        self.assertEqual(a, b)

    def test_search_type_and_bm25_params_are_ignored(self):
        # 全 search_type が同一コーパスのインデックスを共有する設計
        a = get_index_dir({"chunk_size": 500, "search_type": "similarity"}, 1)
        b = get_index_dir({"chunk_size": 500, "search_type": "hybrid",
                           "bm25_k1": 2.0, "bm25_b": 0.9}, 1)
        self.assertEqual(a, b)

    def test_chunk_size_change_produces_different_hash(self):
        a = get_index_dir({"chunk_size": 500}, 1)
        b = get_index_dir({"chunk_size": 800}, 1)
        self.assertNotEqual(a, b)

    def test_each_index_param_affects_hash(self):
        base = {"chunk_size": 500, "overlap": 100, "chunker": "legacy",
                "faiss_index_type": "flatip"}
        baseline = get_index_dir(base, 1)
        for key, changed in [("chunk_size", 800), ("overlap", 50),
                             ("chunker", "langchain"), ("faiss_index_type", "flatl2")]:
            with self.subTest(key=key):
                self.assertNotEqual(get_index_dir({**base, key: changed}, 1), baseline)

    def test_project_id_separates_directories(self):
        a = get_index_dir({"chunk_size": 500}, 1)
        b = get_index_dir({"chunk_size": 500}, 2)
        self.assertNotEqual(a, b)
        self.assertEqual(a.name, b.name)  # ハッシュ部分は同一

    def test_string_and_int_values_hash_alike(self):
        # ハッシュキーは f"{k}={v}" のため、500 と "500" は同一になる
        self.assertEqual(
            get_index_dir({"chunk_size": 500}, 1),
            get_index_dir({"chunk_size": "500"}, 1),
        )

    def test_float_value_produces_different_hash(self):
        # 一方 500.0 は "500.0" となり別ハッシュになる。
        # EvalParams.normalize() が整数値の float を int へ落としているのはこのため
        self.assertNotEqual(
            get_index_dir({"chunk_size": 500}, 1),
            get_index_dir({"chunk_size": 500.0}, 1),
        )

    def test_hash_is_8_chars(self):
        self.assertEqual(len(get_index_dir({"chunk_size": 500}, 1).name), 8)

    def test_base_dir_layout(self):
        self.assertEqual(get_index_base_dir(3).parts[-2:], ("pj_3", "index"))


class GetIndexInfoTest(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(
            indexing.index_builder, "_DATA_DIR", Path(self._tmp.name)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.params = {"chunk_size": 500}
        self.index_dir = get_index_dir(self.params, 1)

    def _make_index(self, *, with_bm25=False, texts=None, creation_time="0:00:05"):
        self.index_dir.mkdir(parents=True, exist_ok=True)
        (self.index_dir / "index.faiss").write_bytes(b"dummy")
        (self.index_dir / "params.json").write_text(
            json.dumps({"chunk_size": 500, "creation_time": creation_time}),
            encoding="utf-8",
        )
        if texts is not None:
            (self.index_dir / "texts.json").write_text(
                json.dumps(texts, ensure_ascii=False), encoding="utf-8"
            )
        if with_bm25:
            (self.index_dir / "bm25.pkl").write_bytes(b"dummy")

    def test_missing_directory(self):
        self.assertEqual(get_index_info(self.params, 1), {"exists": False})

    def test_directory_without_faiss_file(self):
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.assertEqual(get_index_info(self.params, 1), {"exists": False})

    def test_existing_index(self):
        self._make_index()
        info = get_index_info(self.params, 1)
        self.assertTrue(info["exists"])
        self.assertEqual(info["creation_time"], "0:00:05")
        self.assertTrue(info["created_at"])

    def test_bm25_search_type_requires_bm25_file(self):
        self._make_index(with_bm25=False)
        params = {**self.params, "search_type": "hybrid"}
        self.assertEqual(get_index_info(params, 1), {"exists": False})

    def test_bm25_search_type_with_bm25_file(self):
        self._make_index(with_bm25=True)
        for search_type in ("hybrid", "bm25"):
            with self.subTest(search_type=search_type):
                info = get_index_info({**self.params, "search_type": search_type}, 1)
                self.assertTrue(info["exists"])

    def test_non_bm25_search_type_ignores_bm25_file(self):
        self._make_index(with_bm25=False)
        info = get_index_info({**self.params, "search_type": "similarity"}, 1)
        self.assertTrue(info["exists"])

    def test_chunk_stats(self):
        self._make_index(texts=["12345", "1234567", "123"])
        stats = get_index_info(self.params, 1)["chunk_stats"]
        self.assertEqual(stats, {"total": 3, "avg": 5, "max": 7, "min": 3})

    def test_chunk_stats_empty_when_texts_missing(self):
        self._make_index()
        self.assertEqual(get_index_info(self.params, 1)["chunk_stats"], {})

    def test_chunk_stats_empty_when_texts_empty(self):
        self._make_index(texts=[])
        self.assertEqual(get_index_info(self.params, 1)["chunk_stats"], {})


class StripFrontmatterTest(SimpleTestCase):
    def test_removes_frontmatter(self):
        text = "---\ntitle: A\n---\n\n本文"
        self.assertEqual(strip_frontmatter(text), "本文")

    def test_no_frontmatter_returns_as_is(self):
        self.assertEqual(strip_frontmatter("本文のみ"), "本文のみ")

    def test_unterminated_frontmatter_returns_as_is(self):
        text = "---\ntitle: A"
        self.assertEqual(strip_frontmatter(text), text)

    def test_horizontal_rule_in_body_is_not_frontmatter(self):
        # 先頭が --- でなければ影響を受けない
        text = "本文\n\n---\n\n続き"
        self.assertEqual(strip_frontmatter(text), text)


class LoadMarkdownDocumentsTest(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_loads_recursively_with_posix_relative_source(self):
        (self.base / "sub").mkdir()
        (self.base / "a.md").write_text("A本文", encoding="utf-8")
        (self.base / "sub" / "b.md").write_text("B本文", encoding="utf-8")
        docs = load_markdown_documents(str(self.base))
        by_source = {d["source"]: d["text"] for d in docs}
        self.assertEqual(by_source, {"a.md": "A本文", "sub/b.md": "B本文"})

    def test_ignores_non_markdown(self):
        (self.base / "a.md").write_text("A", encoding="utf-8")
        (self.base / "b.txt").write_text("B", encoding="utf-8")
        docs = load_markdown_documents(str(self.base))
        self.assertEqual([d["source"] for d in docs], ["a.md"])

    def test_empty_directory(self):
        self.assertEqual(load_markdown_documents(str(self.base)), [])

    def test_frontmatter_is_not_stripped(self):
        # 現行の load_markdown_documents は frontmatter を除去しない
        (self.base / "a.md").write_text("---\ntitle: A\n---\n本文", encoding="utf-8")
        docs = load_markdown_documents(str(self.base))
        self.assertIn("title: A", docs[0]["text"])


class BuildPromptTest(SimpleTestCase):
    def test_contains_context_and_question(self):
        prompt = build_prompt(context="コンテキスト本文", question="質問文")
        self.assertIn("コンテキスト本文", prompt)
        self.assertIn("質問文", prompt)

    def test_instructs_to_use_only_context(self):
        prompt = build_prompt(context="c", question="q")
        self.assertIn("ONLY the provided context", prompt)
        self.assertIn("I don't know", prompt)

    def test_empty_context_is_allowed(self):
        self.assertIn("Question:", build_prompt(context="", question="q"))

    def test_braces_in_input_do_not_break_formatting(self):
        # str.format 使用のため、入力の波括弧が壊さないこと
        prompt = build_prompt(context="{not_a_field}", question="q")
        self.assertIn("{not_a_field}", prompt)


class FAISSStoreRoundTripTest(SimpleTestCase):
    """faiss は pip パッケージとして導入済みで、往復テストは1秒未満で終わる。
    保存形式の互換性はモックでは代替できないため、実インデックスで検証する。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = str(Path(self._tmp.name) / "index")
        self.vectors = [[1.0, 0.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0, 0.0],
                        [0.0, 0.0, 1.0, 0.0]]
        self.metadatas = [{"source": f"s{i}.md", "chunk_index": i} for i in range(3)]
        self.texts = ["alpha beta", "gamma delta", "epsilon zeta"]

    def _build(self, faiss_index_type="flatip", with_texts=True):
        store = FAISSStore(dim=4, faiss_index_type=faiss_index_type)
        store.add(self.vectors, self.metadatas,
                  self.texts if with_texts else None)
        return store

    def test_round_trip_preserves_vectors_and_metadata(self):
        self._build().save(self.path)
        loaded = FAISSStore.load(self.path)
        self.assertEqual(loaded.index.ntotal, 3)
        self.assertEqual(loaded.dim, 4)
        self.assertEqual(loaded.metadata, self.metadatas)
        self.assertEqual(loaded.texts, self.texts)

    def test_round_trip_preserves_search_order(self):
        self._build().save(self.path)
        loaded = FAISSStore.load(self.path)
        import numpy as np
        query = np.array([[1.0, 0.0, 0.0, 0.0]]).astype("float32")
        _, idx = loaded.index.search(query, 3)
        self.assertEqual(idx[0][0], 0)  # 最も近いのは1本目

    def test_bm25_is_persisted_when_texts_given(self):
        self._build().save(self.path)
        self.assertTrue((Path(self.path) / "bm25.pkl").exists())
        self.assertIsNotNone(FAISSStore.load(self.path).bm25)

    def test_bm25_absent_when_no_texts(self):
        self._build(with_texts=False).save(self.path)
        self.assertFalse((Path(self.path) / "bm25.pkl").exists())
        loaded = FAISSStore.load(self.path)
        self.assertIsNone(loaded.bm25)
        self.assertEqual(loaded.texts, [])

    def test_index_type_is_restored(self):
        for index_type in ("flatip", "flatl2"):
            with self.subTest(index_type=index_type):
                path = f"{self.path}_{index_type}"
                self._build(faiss_index_type=index_type).save(path)
                self.assertEqual(FAISSStore.load(path).faiss_index_type, index_type)

    def test_dimension_mismatch_raises(self):
        store = FAISSStore(dim=4)
        with self.assertRaises(ValueError):
            store.add([[1.0, 2.0]], [{"source": "a.md"}], ["text"])

    def test_save_creates_directory(self):
        nested = str(Path(self._tmp.name) / "a" / "b" / "index")
        self._build().save(nested)
        self.assertTrue((Path(nested) / "index.faiss").exists())
