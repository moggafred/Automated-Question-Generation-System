"""In-memory retrieval layer used by the RAG pipeline.

Design
------
The index is built with a deterministic hashed bag-of-n-grams embedding so the
platform has no external vector database dependency and works fully offline.
Similarity is IDF-weighted cosine over FAISS when the wheel is available, and
falls back to an identical pure-Python scan otherwise -- both paths return the
same ranking, which keeps tests stable across environments.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional

try:
    import numpy as np
    import faiss

    FAISS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only on minimal installs
    np = None
    faiss = None
    FAISS_AVAILABLE = False


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    """
    a an and are as at be been being but by can could did do does for from had has have
    he her his how i if in into is it its may might must no nor not of on or other our
    should so some such than that the their them then there these they this those through
    to too under up use used using was we were what when where which while who will with
    would you your
    """.split()
)


@dataclass(slots=True)
class RetrievedChunk:
    """A retrieved context window plus its similarity score and position."""

    text: str
    score: float
    index: int

    def as_dict(self) -> dict:
        return {"index": self.index, "score": round(float(self.score), 6), "text": self.text}


def _tokenize(text: str) -> List[str]:
    """Lower-cases, strips punctuation and removes stopwords."""
    return [token for token in _TOKEN_PATTERN.findall((text or "").lower()) if token not in _STOPWORDS]


def _features(text: str) -> dict[str, int]:
    """Builds a term-frequency map over unigrams and adjacent bigrams.

    Bigrams are what let the retriever match multi-word concepts such as
    "association rule mining" instead of only single tokens.
    """
    tokens = _tokenize(text)
    counts: dict[str, int] = {}

    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    for left, right in zip(tokens, tokens[1:]):
        key = f"{left}_{right}"
        counts[key] = counts.get(key, 0) + 1

    return counts


class DocumentRetriever:
    """FAISS-backed retrieval over every parsed context chunk of one document."""

    def __init__(self, dim: int = 512):
        self.dim = int(dim)
        self.chunks: List[str] = []
        self.index = None
        self.vectors: Optional[list] = None
        self._idf: dict[str, float] = {}
        self._bucket_weights: Optional[list[tuple[int, float, float]]] = None

    # -- Index construction ---------------------------------------------
    def index_chunks(self, chunks: List[str]) -> None:
        """Embeds and indexes the supplied chunks, computing corpus IDF weights."""
        self.chunks = [str(chunk).strip() for chunk in (chunks or []) if str(chunk).strip()]

        if not self.chunks:
            self.index = None
            self.vectors = None
            self._idf = {}
            self._bucket_weights = None
            return

        feature_maps = [_features(chunk) for chunk in self.chunks]
        self._idf = self._compute_idf(feature_maps)
        bucket_weights = self._build_buckets(feature_maps)

        self._bucket_weights = bucket_weights

        if FAISS_AVAILABLE:
            matrix = np.array(
                [self._vectorize(counts) for counts in feature_maps],
                dtype="float32",
            )
            self.index = faiss.IndexFlatIP(self.dim)
            self.index.add(matrix)
            self.vectors = None
        else:
            self.vectors = [self._vectorize(counts) for counts in feature_maps]
            self.index = None

    def _compute_idf(self, feature_maps: list[dict[str, int]]) -> dict[str, float]:
        """Smoothed inverse document frequency, then rare terms dominate ranking."""
        total = max(1, len(feature_maps))
        document_frequency: dict[str, int] = {}
        for counts in feature_maps:
            for feature in counts:
                document_frequency[feature] = document_frequency.get(feature, 0) + 1
        return {feature: math.log((1 + total) / (1 + freq)) + 1.0 for feature, freq in document_frequency.items()}

    def _hash_bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.md5(feature.encode("utf-8")).hexdigest()
        return int(digest, 16) % self.dim, 1.0 if (int(digest[8:12], 16) & 1) else -1.0

    def _build_buckets(self, feature_maps: list[dict[str, int]]) -> list[tuple[int, float, float]]:
        """Precomputes (bucket, sign, max IDF) per unique feature for fast queries."""
        weights: dict[str, tuple[int, float, float]] = {}
        for counts in feature_maps:
            for feature in counts:
                if feature not in weights:
                    bucket, sign = self._hash_bucket(feature)
                    weights[feature] = (bucket, sign, self._idf.get(feature, 1.0))
        return list(weights.values())

    def _vectorize(self, counts: dict[str, int]) -> list[float]:
        """Projects a term-frequency map into a sublinear, IDF-weighted L2 vector."""
        vector = [0.0] * self.dim
        for feature, frequency in counts.items():
            bucket, sign = self._hash_bucket(feature)
            idf = self._idf.get(feature, 1.0)
            vector[bucket] += sign * (1.0 + math.log(frequency)) * idf

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _embed(self, text: str) -> list[float]:
        """Embeds a free-text query using the corpus IDF table."""
        return self._vectorize(_features(text))

    # -- Retrieval --------------------------------------------------------
    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        """Returns the top-k most semantically relevant chunks, most relevant first."""
        return [chunk.text for chunk in self.retrieve_scored(query, top_k=top_k)]

    def retrieve_scored(self, query: str, top_k: int = 3) -> List[RetrievedChunk]:
        """Same ranking as :meth:`retrieve` but keeps the similarity scores."""
        if not self.chunks or top_k < 1:
            return []
        top_k = min(int(top_k), len(self.chunks))

        query_vector = self._embed(query)

        if FAISS_AVAILABLE and self.index is not None:
            query_matrix = np.array([query_vector], dtype="float32")
            scores, indices = self.index.search(query_matrix, top_k)
            return [
                RetrievedChunk(text=self.chunks[idx], score=float(score), index=int(idx))
                for score, idx in zip(scores[0], indices[0])
                if 0 <= idx < len(self.chunks)
            ]

        vectors = self.vectors or [self._embed(chunk) for chunk in self.chunks]
        scored = [
            RetrievedChunk(text=chunk, score=sum(a * b for a, b in zip(query_vector, vector)), index=idx)
            for idx, (chunk, vector) in enumerate(zip(self.chunks, vectors))
        ]
        scored.sort(key=lambda item: (-item.score, item.index))
        return scored[:top_k]

    def build_context(self, query: str, top_k: Optional[int] = None, max_chars: Optional[int] = None) -> tuple[str, list[RetrievedChunk]]:
        """Builds the prompt context string from the highest-scoring chunks.

        Returns the joined context plus the scored chunks so callers can persist
        grounding references alongside the generated content.
        """
        limit = top_k if top_k is not None else settings_top_k()
        ceiling = max_chars if max_chars is not None else settings_max_chars()

        retrieved = self.retrieve_scored(query, top_k=limit)
        if not retrieved:
            return "", []

        selected: list[RetrievedChunk] = []
        used = 0
        for chunk in retrieved:
            addition = len(chunk.text) + 2
            if used + addition > ceiling and selected:
                break
            selected.append(chunk)
            used += addition

        context = "\n\n".join(chunk.text for chunk in selected)
        return context, selected


def settings_top_k() -> int:
    from config.settings import settings

    return settings.RAG_TOP_K


def settings_max_chars() -> int:
    from config.settings import settings

    return settings.RAG_MAX_CONTEXT_CHARS


__all__ = ["DocumentRetriever", "RetrievedChunk", "FAISS_AVAILABLE"]