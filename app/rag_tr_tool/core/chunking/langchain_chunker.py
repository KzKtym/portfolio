from typing import List, Dict

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


_HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
    ("####", "h4"),
]


# SPEC_langchain: Chunking層/LangChain Markdown Chunking/見出し単位(MarkdownHeaderTextSplitter)
# SPEC_langchain: Chunking層/LangChain Markdown Chunking/token制御再分割(RecursiveCharacterTextSplitter)
# SPEC_langchain: Chunking層/LangChain Markdown Chunking/コードブロック非分断
def langchain_chunk(text: str, source: str,
                    chunk_size: int = 500,
                    overlap: int = 100) -> List[Dict]:

    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS_TO_SPLIT_ON,
        strip_headers=False,
    )
    token_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
    )

    header_docs = md_splitter.split_text(text)
    final_docs = token_splitter.split_documents(header_docs)

    all_chunks = []
    for chunk_index, doc in enumerate(final_docs):
        meta = doc.metadata  # {"h1": "...", "h2": "...", ...} など

        # header_path: 見出し階層リスト（値があるもののみ）
        header_path = [
            meta[k]
            for k in ("h1", "h2", "h3", "h4")
            if meta.get(k)
        ]

        # section_title: 最末端の見出しタイトル
        section_title = header_path[-1] if header_path else "root"

        all_chunks.append({
            "chunk_id": f"{source}::chunk_{chunk_index:04d}",
            "source": source,
            "section_title": section_title,
            "header_path": header_path,
            "chunk_index": chunk_index,
            "token_count": len(doc.page_content),
            "text": doc.page_content.strip(),
        })

    return all_chunks