from typing import List, Dict
import faiss
import json
import pickle
import numpy as np
from pathlib import Path


class FAISSStore:

    def __init__(self, dim: int, faiss_index_type: str = "flatip"):
        self.dim = dim
        self.faiss_index_type = faiss_index_type
        if faiss_index_type == "flatip":
            # SPEC_flatip: 20/VectorStore/FAISS/IndexFlatIP
            self.index = faiss.IndexFlatIP(dim)
        else:
            # SPEC_flatl2: 20/VectorStore/FAISS/IndexFlatL2
            self.index = faiss.IndexFlatL2(dim)
        self.metadata: List[Dict] = []
        self.texts: List[str] = []
        self.bm25 = None

    def add(self,
            vectors: List[List[float]],
            metadatas: List[Dict],
            texts: List[str] = None,
            bm25_k1: float = 1.5,
            bm25_b: float = 0.75):

        np_vectors = np.array(vectors).astype("float32")

        if np_vectors.shape[1] != self.dim:
            raise ValueError("Embedding dimension mismatch")

        self.index.add(np_vectors)
        self.metadata.extend(metadatas)
        if texts is not None:
            self.texts.extend(texts)
            # SPEC_hybrid: 20/VectorStore/BM25/BM25Okapi(rank-bm25)/空白トークナイズ
            # SPEC_bm25: 20/VectorStore/BM25/BM25Okapi(rank-bm25)/空白トークナイズ
            from rank_bm25 import BM25Okapi
            tokenized = [t.split() for t in self.texts]
            self.bm25 = BM25Okapi(tokenized, k1=bm25_k1, b=bm25_b)

    def save(self, path: str):

        base = Path(path)
        base.mkdir(parents=True, exist_ok=True)

        faiss.write_index(self.index, str(base / "index.faiss"))

        with open(base / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

        with open(base / "texts.json", "w", encoding="utf-8") as f:
            json.dump(self.texts, f, ensure_ascii=False, indent=2)

        if self.bm25 is not None:
            with open(base / "bm25.pkl", "wb") as f:
                pickle.dump(self.bm25, f)

    @classmethod
    def load(cls, path: str):

        base = Path(path)

        index = faiss.read_index(str(base / "index.faiss"))

        with open(base / "metadata.json", "r", encoding="utf-8") as f:
            metadata = json.load(f)

        texts_path = base / "texts.json"
        texts = []
        if texts_path.exists():
            with open(texts_path, "r", encoding="utf-8") as f:
                texts = json.load(f)

        store = cls(index.d, faiss_index_type="flatip" if isinstance(index, faiss.IndexFlatIP) else "flatl2")
        store.index = index
        store.metadata = metadata
        store.texts = texts

        bm25_path = base / "bm25.pkl"
        if bm25_path.exists():
            with open(bm25_path, "rb") as f:
                store.bm25 = pickle.load(f)
        else:
            store.bm25 = None  # 旧インデックス互換

        return store