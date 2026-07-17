from typing import List
from abc import ABC, abstractmethod


class BaseEmbedder(ABC):

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        pass
