import hashlib
import math
from typing import List, Optional

try:
    import numpy as np
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    np = None
    FAISS_AVAILABLE = False


class DocumentRetriever:
    """In-memory FAISS retrieval layer (RAG) over every parsed context chunk.

    Uses a lightweight hashing bag-of-words embedding with cosine similarity so
    the pipeline works with zero extra dependencies and degrades gracefully to a
    pure-Python cosine scan when the FAISS/numpy wheels are unavailable.
    """

    def __init__(self, dim: int = 512):
        self.dim = dim
        self.chunks: List[str] = []
        self.index = None
        self.vectors: Optional[list] = None

    def _embed(self, text: str) -> list:
        tokens = text.lower().split()
        vec = [0.0] * self.dim
        for tok in tokens:
            digest = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            index = digest % self.dim
            sign = 1.0 if (digest >> 16) & 1 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]

    def index_chunks(self, chunks: List[str]) -> None:
        self.chunks = list(chunks)
        if FAISS_AVAILABLE:
            matrix = np.array([self._embed(c) for c in self.chunks], dtype="float32")
            self.index = faiss.IndexFlatIP(self.dim)
            self.index.add(matrix)
        else:
            self.vectors = [self._embed(c) for c in self.chunks]

    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        """Returns the top-k most semantically relevant chunks for the query."""
        if not self.chunks or top_k < 1:
            return []
        top_k = min(top_k, len(self.chunks))
        query_vec = self._embed(query)

        if FAISS_AVAILABLE:
            q = np.array([query_vec], dtype="float32")
            scores, idxs = self.index.search(q, top_k)
            return [self.chunks[i] for i in idxs[0] if i >= 0]
        else:
            scored = [
                (sum(a * b for a, b in zip(query_vec, vec)), idx)
                for idx, vec in enumerate(self.vectors)
            ]
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [self.chunks[idx] for _, idx in scored[:top_k]]