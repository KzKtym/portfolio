from typing import List, Dict


def split_text_fixed(
    document: Dict,
    chunk_size: int = 500,
    overlap: int = 0
) -> List[Dict]:

    text = document["text"]
    doc_id = document["doc_id"]

    chunks = []
    start = 0
    chunk_index = 0

    while start < len(text):
        end = start + chunk_size
        chunk_text = text[start:end]

        chunks.append({
            "chunk_id": f"{doc_id}::chunk_{chunk_index:03d}",
            "doc_id": doc_id,
            "text": chunk_text
        })

        start = end - overlap
        chunk_index += 1

    return chunks


def split_documents(
    documents: List[Dict],
    chunk_size: int = 500,
    overlap: int = 0
) -> List[Dict]:

    all_chunks = []

    for doc in documents:
        chunks = split_text_fixed(doc, chunk_size, overlap)
        all_chunks.extend(chunks)

    return all_chunks
