'''
改善余地：
* 本当のtokenベース分割（tiktoken）
* コードブロック完全保護
* sentence boundary NLP対応
'''
import re
from typing import List, Dict


HEADER_PATTERN = re.compile(r'^(#{1,6})\s+(.*)', re.MULTILINE)
CODE_BLOCK_PATTERN = re.compile(r'```.*?```', re.DOTALL)


def extract_sections(text: str):
    matches = list(HEADER_PATTERN.finditer(text))

    if not matches:
        return [("root", [], text)]

    sections = []
    header_stack = []

    # 最初の見出しより前の本文（前書き）も 1 セクションとして保持する。
    # 見出し位置から読み始めると、ここが丸ごと欠落する。
    preamble = text[:matches[0].start()].strip()
    if preamble:
        sections.append(("root", [], preamble))

    for i, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()

        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

        content = text[start:end].strip()

        # update header hierarchy
        header_stack = header_stack[:level - 1]
        header_stack.append(title)

        sections.append((title, header_stack.copy(), content))

    return sections


def safe_split_paragraphs(text: str):
    return [p.strip() for p in text.split("\n\n") if p.strip()]


SEPARATOR = "\n\n"


def _validate_split_params(max_chars: int, overlap: int) -> None:
    """分割パラメータを検証する。

    不正値を黙って丸めると、実験レコードに残るパラメータと実際の挙動がずれ、
    計測結果が信用できなくなるため、明示的に失敗させる。
    """
    if max_chars <= 0:
        raise ValueError(f"max_chars は正の整数である必要があります: {max_chars}")
    if overlap < 0:
        raise ValueError(f"overlap は 0 以上である必要があります: {overlap}")
    if overlap >= max_chars:
        raise ValueError(
            f"overlap は max_chars より小さい必要があります: "
            f"overlap={overlap}, max_chars={max_chars}"
        )


def _hard_split(text: str, max_chars: int, overlap: int):
    """max_chars を超えるテキストを overlap 付きで機械的に分割する。"""
    step = max_chars - overlap  # _validate_split_params により 1 以上が保証される
    pieces = []
    start = 0
    while start < len(text):
        piece = text[start:start + max_chars]
        if piece.strip():
            pieces.append(piece)
        if start + max_chars >= len(text):
            break
        start += step
    return pieces


def recursive_split(text: str, max_chars: int, overlap: int):
    _validate_split_params(max_chars, overlap)

    if len(text) <= max_chars:
        return [text] if text.strip() else []

    paragraphs = safe_split_paragraphs(text)

    chunks = []
    current = ""

    for p in paragraphs:
        candidate = (current + SEPARATOR + p) if current else p

        if len(candidate) <= max_chars:
            current = candidate
            continue

        # current を確定させ、その末尾 overlap 文字を次チャンクの先頭へ引き継ぐ。
        # 引き継ぎが無いと、段落パッキング経路では overlap が無視される。
        carry = ""
        if current.strip():
            chunks.append(current.strip())
            if overlap:  # overlap=0 のとき text[-0:] は全文になるため必ず分岐する
                carry = current[-overlap:]
        current = (carry + SEPARATOR + p) if carry else p

    if current.strip():
        chunks.append(current.strip())

    # hard split fallback
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final_chunks.append(chunk)
        else:
            final_chunks.extend(_hard_split(chunk, max_chars, overlap))

    return final_chunks


def markdown_chunk(text: str, source: str,
                   max_chars: int = 1000,
                   overlap: int = 150) -> List[Dict]:

    sections = extract_sections(text)

    all_chunks = []
    chunk_counter = 0

    for title, header_path, content in sections:
        sub_chunks = recursive_split(content, max_chars, overlap)

        for idx, chunk in enumerate(sub_chunks):
            chunk_text = chunk.strip()
            all_chunks.append({
                "chunk_id": f"{source}::chunk_{chunk_counter:04d}",
                "source": source,
                "section_title": title,
                "header_path": header_path,
                "chunk_index": idx,
                "token_count": len(chunk_text),
                "text": chunk_text
            })
            chunk_counter += 1

    return all_chunks