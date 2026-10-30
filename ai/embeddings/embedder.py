"""Embedding model wrapper (TRD decision D2) used by RAG ingestion and queries.

An embedding turns a text into a vector (here 384 numbers) so that texts with a similar meaning
get similar vectors: "the robot is too hot" lands near "motor temperature above 60 C" even
though they share no word. Vectors are L2-normalised, so the dot product is the cosine
similarity.
"""

from __future__ import annotations

import hashlib
import re
import threading

import numpy as np

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # 22 M parameters, 384 dimensions


class Embedder:
    """Sentence-Transformers model, loaded on first use (a few seconds) and kept in memory."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.name = model_name
        self._model = None
        self._lock = threading.Lock()

    @property
    def model(self):
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self.name, device="cpu")
        return self._model

    @property
    def dim(self) -> int:
        return self.model.get_embedding_dimension()

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        vectors = self.model.encode(
            texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vectors, dtype=np.float32)


class HashEmbedder:
    """Tiny deterministic stand-in for tests (no download): hashed bag of words, normalised.
    Similar only when words overlap, which is enough to test the plumbing."""

    name = "hash-bag-of-words"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def encode(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                out[i, h % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)
