from typing import List
from sentence_transformers import SentenceTransformer
from .base import BaseEmbedder
import numpy as np


class LocalEmbedder(BaseEmbedder):

    def __init__(self,
                 model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model = SentenceTransformer(model_name)
        self.dim = self.model.get_sentence_embedding_dimension()

    def embed(self, texts: List[str]) -> List[List[float]]:
        vectors = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False
        )
        return vectors.astype(np.float32).tolist()

