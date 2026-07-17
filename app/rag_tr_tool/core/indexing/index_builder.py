import json
import time
import datetime
import hashlib
import shutil
from pathlib import Path

from django.conf import settings

from ..ingest.loader import load_markdown_documents
from ..chunking.markdown_chunker import markdown_chunk
from ..chunking.langchain_chunker import langchain_chunk
from ..embedding.local_embedder import LocalEmbedder
from ..vectorstore.faiss_store import FAISSStore

_DATA_DIR = Path(settings.BASE_DIR) / "data" / "rag_tr_tool"
_DOCS_DIR = _DATA_DIR / "raw" / "fastapi" / "docs"

# インデックス構築に使用するパラメータキー（ハッシュ計算対象、top_kは除外）
# search_type / bm25_k1 / bm25_b はRetriever層のパラメータのためハッシュに含めない
# → 全search_typeが同一コーパスのインデックスを共有し、正確な比較が可能
_INDEX_PARAM_KEYS = {"chunk_size", "overlap", "chunker", "faiss_index_type"}
# BM25インデックス（bm25.pkl）を必要とするsearch_type一覧
# 新たにBM25インデックスが必要なsearch_typeを追加した際はここに追記する
_BM25_SEARCH_TYPES = {"hybrid", "bm25"}


def get_index_base_dir(project_id: int) -> Path:
    """プロジェクトIDからインデックスベースディレクトリパスを返す。"""
    return _DATA_DIR / f"pj_{project_id}" / "index"


def get_index_dir(params: dict, project_id: int) -> Path:
    """インデックスパラメータからディレクトリパスを返す。
    ハッシュキーは_INDEX_PARAM_KEYSのみをソートして生成。
    search_type / bm25_k1 / bm25_b はハッシュに含めないため、
    全search_typeが同一チャンク・Embedding設定なら同じディレクトリを参照する。
    """
    index_params = {k: v for k, v in params.items() if k in _INDEX_PARAM_KEYS}
    key = ",".join(f"{k}={v}" for k, v in sorted(index_params.items()))
    hash_str = hashlib.md5(key.encode()).hexdigest()[:8]
    return get_index_base_dir(project_id) / hash_str


def build_index(params: dict, rebuild: bool = False, project_id: int = 1):
    """インデックスを構築またはキャッシュからロードして返す。

    Returns:
        (store, embedder, index_creation_time)
    """
    chunk_size = int(params.get("chunk_size", 500))
    overlap = int(params.get("overlap", 100))
    chunker = params.get("chunker", "langchain")
    faiss_index_type = params.get("faiss_index_type", "flatip")

    index_dir = get_index_dir(params, project_id)

    if rebuild and index_dir.exists():
        shutil.rmtree(index_dir)

    # キャッシュ済みなら即ロード
    if (index_dir / "index.faiss").exists():
        store = FAISSStore.load(str(index_dir))
        embedder = LocalEmbedder()
        creation_time = None
        params_path = index_dir / "params.json"
        if params_path.exists():
            p = json.loads(params_path.read_text(encoding="utf-8"))
            creation_time = p.get("creation_time")
        return store, embedder, creation_time

    # 未生成なら構築
    index_start = time.time()
    docs = load_markdown_documents(str(_DOCS_DIR))

    all_chunks = []
    for doc in docs:
        if chunker == "langchain":
            # SPEC_langchain: 30/Chunking層/LangChain Markdown Chunking/見出し単位(MarkdownHeaderTextSplitter)
            # SPEC_langchain: 30/Chunking層/LangChain Markdown Chunking/token制御再分割(RecursiveCharacterTextSplitter)
            chunks = langchain_chunk(
                text=doc["text"],
                source=doc["source"],
                chunk_size=chunk_size,
                overlap=overlap,
            )
        else:
            # SPEC_legacy: 30/Chunking層/構造保存型Markdown Chunking/見出し単位,コードブロック非分断,文境界優先,max_tokens制限付き再帰分割
            chunks = markdown_chunk(
                text=doc["text"],
                source=doc["source"],
                max_chars=chunk_size,
                overlap=overlap,
            )
        all_chunks.extend(chunks)
        # ※SPEC表の記載順調整のため、この位置にコメント実装
        # SPEC: 30/Chunking層/Parameter/chunk_size,overlap

    # 空チャンク除去
    all_chunks = [c for c in all_chunks if c["text"].strip()]

    # SPEC: Embedding/Local/BGE-small-en-v1.5
    #   * BAAI公開の一般埋め込みモデル(BGE=BAAI General Embedding)
    #   * 文章をコンパクトにベクトル変換する技術のスタンダード
    # SPEC: Embedding/Local/normalize_embeddings=True
    embedder = LocalEmbedder()

    embed_texts = ["passage: " + c["text"] for c in all_chunks]
    store_texts = [c["text"] for c in all_chunks]
    metadatas = [
        {
            "source": c["source"],
            "section_title": c["section_title"],
            "header_path": c["header_path"],
            "chunk_index": c["chunk_index"],
        }
        for c in all_chunks
    ]

    vectors = []
    for i in range(0, len(embed_texts), 100):
        vectors.extend(embedder.embed(embed_texts[i:i + 100]))

    bm25_k1 = float(params.get("bm25_k1", 1.5))
    bm25_b = float(params.get("bm25_b", 0.75))

    store = FAISSStore(dim=len(vectors[0]), faiss_index_type=faiss_index_type)
    store.add(vectors, metadatas, store_texts, bm25_k1=bm25_k1, bm25_b=bm25_b)
    store.save(str(index_dir))

    index_elapsed = time.time() - index_start
    index_creation_time = str(datetime.timedelta(seconds=int(index_elapsed)))

    with open(index_dir / "params.json", "w", encoding="utf-8") as f:
        json.dump({
            **{k: v for k, v in params.items() if k in _INDEX_PARAM_KEYS},
            "creation_time": index_creation_time,
        }, f, ensure_ascii=False)

    return store, embedder, index_creation_time


def get_index_info(params: dict, project_id: int = 1) -> dict:
    """Indexの存在確認と作成日時・所要時間・chunk統計を返す。
    search_type が _BM25_SEARCH_TYPES の場合、bm25.pkl の存在も「有無」判定に加える。
    """
    import datetime
    index_dir = get_index_dir(params, project_id)
    if not index_dir.exists():
        return {"exists": False}
    faiss_path = index_dir / "index.faiss"
    if not faiss_path.exists():
        return {"exists": False}
    # BM25を必要とするsearch_typeでbm25.pklが未存在の場合は「無」
    if params.get("search_type") in _BM25_SEARCH_TYPES:
        if not (index_dir / "bm25.pkl").exists():
            return {"exists": False}
    created_at = datetime.datetime.fromtimestamp(faiss_path.stat().st_mtime).strftime("%Y/%m/%d %H:%M")
    params_path = index_dir / "params.json"
    creation_time = ""
    if params_path.exists():
        p = json.loads(params_path.read_text(encoding="utf-8"))
        creation_time = p.get("creation_time", "")
    chunk_stats = {}
    texts_path = index_dir / "texts.json"
    if texts_path.exists():
        texts = json.loads(texts_path.read_text(encoding="utf-8"))
        if texts:
            lengths = [len(t) for t in texts]
            chunk_stats = {
                "total": len(lengths),
                "avg": round(sum(lengths) / len(lengths)),
                "max": max(lengths),
                "min": min(lengths),
            }
    return {
        "exists": True,
        "created_at": created_at,
        "creation_time": creation_time,
        "chunk_stats": chunk_stats,
    }