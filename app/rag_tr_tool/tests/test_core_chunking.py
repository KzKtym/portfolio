"""層B: core/chunking/markdown_chunker の純ロジック。

チャンキングの欠陥は「実験を回しても MRR が低いとしか見えない」ため、
実行では守れない。修正済みの既知不具合4件も回帰テストとして固定する。
"""
from django.test import SimpleTestCase

from app.rag_tr_tool.core.chunking.markdown_chunker import (
    extract_sections,
    markdown_chunk,
    recursive_split,
    safe_split_paragraphs,
)


class ExtractSectionsTest(SimpleTestCase):
    def test_no_header_returns_single_root_section(self):
        sections = extract_sections("見出しのない本文だけ")
        self.assertEqual(sections, [("root", [], "見出しのない本文だけ")])

    def test_preamble_before_first_header_is_kept(self):
        # 回帰: 最初の見出しより前の本文が丸ごと消えていた
        text = "この前書きは重要な内容です。\n\n# 見出し1\n本文A"
        sections = extract_sections(text)
        self.assertEqual(sections[0], ("root", [], "この前書きは重要な内容です。"))
        self.assertEqual(sections[1][0], "見出し1")
        self.assertEqual(sections[1][2], "本文A")

    def test_no_preamble_section_when_text_starts_with_header(self):
        sections = extract_sections("# 見出し1\n本文A")
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0][0], "見出し1")

    def test_whitespace_only_preamble_is_dropped(self):
        sections = extract_sections("\n\n  \n# 見出し1\n本文A")
        self.assertEqual(len(sections), 1)

    def test_header_hierarchy_stack(self):
        text = "# A\na\n## B\nb\n### C\nc\n## D\nd\n# E\ne"
        paths = [path for _, path, _ in extract_sections(text)]
        self.assertEqual(paths, [["A"], ["A", "B"], ["A", "B", "C"], ["A", "D"], ["E"]])

    def test_content_is_split_at_next_header(self):
        text = "# A\n本文A\n\n# B\n本文B"
        sections = extract_sections(text)
        self.assertEqual(sections[0][2], "本文A")
        self.assertEqual(sections[1][2], "本文B")

    def test_empty_section_content_is_kept_as_empty_string(self):
        sections = extract_sections("# A\n# B\n本文B")
        self.assertEqual(sections[0][2], "")


class SafeSplitParagraphsTest(SimpleTestCase):
    def test_splits_on_blank_line(self):
        self.assertEqual(safe_split_paragraphs("a\n\nb"), ["a", "b"])

    def test_drops_empty_and_strips(self):
        self.assertEqual(safe_split_paragraphs("  a  \n\n\n\n  b  "), ["a", "b"])

    def test_empty_text(self):
        self.assertEqual(safe_split_paragraphs(""), [])


class RecursiveSplitValidationTest(SimpleTestCase):
    def test_overlap_equal_to_max_chars_raises(self):
        # 回帰: range() の step が 0 になり ValueError で落ちていた
        with self.assertRaises(ValueError):
            recursive_split("あ" * 1000, max_chars=100, overlap=100)

    def test_overlap_greater_than_max_chars_raises(self):
        with self.assertRaises(ValueError):
            recursive_split("あ" * 1000, max_chars=100, overlap=200)

    def test_non_positive_max_chars_raises(self):
        with self.assertRaises(ValueError):
            recursive_split("あ" * 100, max_chars=0, overlap=0)

    def test_negative_overlap_raises(self):
        with self.assertRaises(ValueError):
            recursive_split("あ" * 100, max_chars=100, overlap=-1)

    def test_validation_runs_even_for_short_text(self):
        # 短文で早期 return する前に検証されること
        with self.assertRaises(ValueError):
            recursive_split("短い", max_chars=10, overlap=10)


class RecursiveSplitTest(SimpleTestCase):
    def test_short_text_passes_through(self):
        self.assertEqual(recursive_split("短い本文", 100, 10), ["短い本文"])

    def test_blank_text_returns_empty_list(self):
        self.assertEqual(recursive_split("   ", 100, 10), [])

    def test_overlap_is_applied_in_paragraph_packing(self):
        # 回帰: overlap がハードスプリット経路でしか効かず、段落パッキングでは無視されていた
        paragraphs = ["あ" * 190] * 6
        chunks = recursive_split("\n\n".join(paragraphs), max_chars=200, overlap=50)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0][-50:], chunks[1][:50])

    def test_no_empty_chunk_when_first_paragraph_exceeds_max(self):
        # 回帰: 先頭段落が max_chars 以上のとき空文字チャンクが混入していた
        text = "あ" * 500 + "\n\n" + "い" * 100
        chunks = recursive_split(text, max_chars=200, overlap=50)
        self.assertTrue(all(c.strip() for c in chunks))

    def test_every_chunk_within_max_chars(self):
        text = "\n\n".join(["あ" * 190] * 6)
        chunks = recursive_split(text, max_chars=200, overlap=50)
        self.assertTrue(all(len(c) <= 200 for c in chunks))

    def test_hard_split_covers_whole_text(self):
        # 分割の結果、元テキストの文字が欠落しないこと
        text = "".join(chr(0x30A0 + (i % 90)) for i in range(1000))
        chunks = recursive_split(text, max_chars=200, overlap=50)
        rebuilt = chunks[0]
        for c in chunks[1:]:
            # overlap 分を考慮して、既に含まれる部分を除いて連結
            idx = rebuilt.find(c[:50])
            rebuilt = rebuilt + c if idx == -1 else rebuilt[:idx] + c
        self.assertIn(text[-50:], rebuilt)

    def test_overlap_zero_does_not_carry_over(self):
        # overlap=0 のとき text[-0:] が全文になる罠を踏まないこと。
        # 段落ごとに文字を変え、引き継ぎが起きていないことを判別可能にする
        text = "\n\n".join(["あ" * 190, "い" * 190, "う" * 190])
        chunks = recursive_split(text, max_chars=200, overlap=0)
        self.assertTrue(all(len(c) <= 200 for c in chunks))
        # 引き継ぎがあれば chunk[1] の先頭に前チャンクの文字が現れる
        self.assertNotIn("あ", chunks[1])


class MarkdownChunkTest(SimpleTestCase):
    def test_chunk_id_format_and_global_counter(self):
        chunks = markdown_chunk("# A\n本文A\n\n# B\n本文B", "doc.md", 1000, 100)
        self.assertEqual([c["chunk_id"] for c in chunks],
                         ["doc.md::chunk_0000", "doc.md::chunk_0001"])

    def test_chunk_index_is_per_section(self):
        # chunk_index はセクション内の連番。セクションが変わると 0 に戻る
        text = "# A\n" + "あ" * 600 + "\n\n# B\n本文B"
        chunks = markdown_chunk(text, "doc.md", 200, 50)
        self.assertEqual(chunks[-1]["chunk_index"], 0)
        self.assertEqual(chunks[0]["chunk_index"], 0)
        self.assertGreater(len(chunks), 2)

    def test_token_count_matches_stripped_text(self):
        chunks = markdown_chunk("# A\n本文A", "doc.md", 1000, 100)
        for c in chunks:
            self.assertEqual(c["token_count"], len(c["text"]))

    def test_header_path_and_section_title(self):
        chunks = markdown_chunk("# A\na\n## B\nb", "doc.md", 1000, 100)
        self.assertEqual(chunks[0]["section_title"], "A")
        self.assertEqual(chunks[0]["header_path"], ["A"])
        self.assertEqual(chunks[1]["header_path"], ["A", "B"])

    def test_source_is_recorded(self):
        chunks = markdown_chunk("本文のみ", "path/to/doc.md", 1000, 100)
        self.assertEqual(chunks[0]["source"], "path/to/doc.md")

    def test_preamble_is_chunked(self):
        chunks = markdown_chunk("前書き本文\n\n# A\n本文A", "doc.md", 1000, 100)
        texts = [c["text"] for c in chunks]
        self.assertIn("前書き本文", texts)

    def test_no_empty_text_chunks(self):
        text = "# A\n" + "あ" * 500 + "\n\n" + "い" * 100
        chunks = markdown_chunk(text, "doc.md", 200, 50)
        self.assertTrue(all(c["text"] for c in chunks))
