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


def recursive_split(text: str, max_chars: int, overlap: int):
    if len(text) <= max_chars:
        return [text]

    paragraphs = safe_split_paragraphs(text)

    chunks = []
    current = ""

    for p in paragraphs:
        if len(current) + len(p) < max_chars:
            current += "\n\n" + p
        else:
            chunks.append(current.strip())
            current = p

    if current:
        chunks.append(current.strip())

    # hard split fallback
    final_chunks = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            final_chunks.append(chunk)
        else:
            for i in range(0, len(chunk), max_chars - overlap):
                final_chunks.append(chunk[i:i + max_chars])

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
            all_chunks.append({
                "chunk_id": f"{source}::chunk_{chunk_counter:04d}",
                "source": source,
                "section_title": title,
                "header_path": header_path,
                "chunk_index": idx,
                "token_count": len(chunk),
                "text": chunk.strip()
            })
            chunk_counter += 1

    return all_chunks