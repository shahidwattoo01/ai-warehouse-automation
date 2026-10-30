"""Top-k retrieval with doc_type filter; grounded answer with citations; 'not covered' when nothing
relevant.

Retrievers (compared in notebooks/12_rag.ipynb):

* BM25: keyword search. Scores a chunk by the question's words it contains, rare words counting
  more (IDF) and long chunks counting less. Exact on ids ("SOP-04", "CHG_3"), blind to synonyms.
* Dense: cosine similarity of embeddings (ai/embeddings/embedder.py). Finds meaning ("too hot"
  ~ "overheating") but can miss exact ids and numbers.
* Hybrid: both lists merged with Reciprocal Rank Fusion (score = sum of 1 / (60 + rank)), which
  needs no score calibration between the two.
* Rerank: a cross-encoder reads question and chunk *together* and scores the pair; slower, so it
  only re-orders the hybrid top candidates.

The vector part runs in memory (exact search; the knowledge base has ~180 chunks) or in
PostgreSQL with pgvector (ai/rag/store.py), with the same results.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np

from ai.rag.ingest import Chunk

RRF_K = 60
STOPWORDS = set(
    "a an and are as at be by can do does for from has have how i if in is it its me my of on "
    "or should so that the their them then there these they this to was what when where which "
    "who why will with you your".split()
)
TOKEN = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")


def tokens(text: str) -> list[str]:
    """Lower-case words; ids stay whole ("sop-04", "chg_3", "r22") and are also split."""
    out = []
    for t in TOKEN.findall(text.lower()):
        if t in STOPWORDS:
            continue
        out.append(t)
        if re.search(r"[-_.]", t):
            out.extend(p for p in re.split(r"[-_.]", t) if p and p not in STOPWORDS)
    return out


class BM25:
    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = [Counter(tokens(t)) for t in texts]
        self.lengths = np.array([sum(d.values()) for d in self.docs], dtype=float)
        self.avg = float(self.lengths.mean()) if len(self.docs) else 1.0
        df = Counter(w for d in self.docs for w in d)
        n = len(self.docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}
        self.k1, self.b = k1, b

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(len(self.docs))
        norm = self.k1 * (1 - self.b + self.b * self.lengths / self.avg)
        for w in set(tokens(query)):
            if w not in self.idf:
                continue
            tf = np.array([d.get(w, 0) for d in self.docs], dtype=float)
            out += self.idf[w] * tf * (self.k1 + 1) / (tf + norm)
        return out


@dataclass
class Hit:
    chunk: Chunk
    score: float  # the score of the last stage (cosine, BM25, RRF or cross-encoder logit)
    dense: float = 0.0  # cosine similarity, kept for the "not covered" decision

    def to_dict(self) -> dict:
        c = self.chunk
        return {
            "chunk_id": c.chunk_id,
            "doc_id": c.doc_id,
            "doc_type": c.doc_type,
            "title": c.title,
            "section_id": c.section_id,
            "heading": c.heading,
            "text": c.text,
            "score": round(float(self.score), 4),
        }


def rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal Rank Fusion of several ranked lists of chunk indexes."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


class Retriever:
    """mode: bm25 | dense | hybrid | rerank (hybrid candidates re-ordered by a cross-encoder)."""

    def __init__(
        self,
        chunks: list[Chunk],
        embedder,
        mode: str = "hybrid",
        reranker=None,
        vectors: np.ndarray | None = None,
        candidates: int = 20,
        vector_index=None,
    ) -> None:
        self.chunks = chunks
        self.embedder = embedder
        self.mode = mode
        self.reranker = reranker
        self.candidates = candidates
        self.bm25 = BM25([c.for_embedding() for c in chunks])
        self.vector_index = vector_index  # PgVectorIndex (ai/rag/store.py), else in memory
        if vector_index is not None:
            self.vectors = None
        elif vectors is not None:
            self.vectors = vectors
        else:
            self.vectors = embedder.encode([c.for_embedding() for c in chunks])

    def _cosines(self, query: np.ndarray, allowed: np.ndarray, limit: int, doc_type) -> np.ndarray:
        if self.vector_index is not None:
            return self.vector_index.cosines(query, limit, doc_type)
        return np.where(allowed, self.vectors @ query, -np.inf)

    def _allowed(self, doc_type: str | None) -> np.ndarray:
        if not doc_type:
            return np.ones(len(self.chunks), dtype=bool)
        return np.array([c.doc_type == doc_type for c in self.chunks])

    def search(self, question: str, k: int = 5, doc_type: str | None = None) -> list[Hit]:
        allowed = self._allowed(doc_type)
        query = self.embedder.encode([question])[0]
        cos = self._cosines(query, allowed, max(k, self.candidates * 2), doc_type)
        keyword = np.where(allowed, self.bm25.scores(question), -np.inf)
        dense_rank = [int(i) for i in np.argsort(-cos) if np.isfinite(cos[i])]
        bm25_rank = [int(i) for i in np.argsort(-keyword) if np.isfinite(keyword[i])]

        if self.mode == "dense":
            order = [(i, cos[i]) for i in dense_rank]
        elif self.mode == "bm25":
            order = [(i, keyword[i]) for i in bm25_rank]
        else:
            fused = rrf([dense_rank[: self.candidates * 2], bm25_rank[: self.candidates * 2]])
            order = sorted(fused.items(), key=lambda kv: -kv[1])
            if self.mode == "rerank" and self.reranker is not None:
                pool = [i for i, _ in order[: self.candidates]]
                logits = self.reranker.predict(
                    [(question, self.chunks[i].for_embedding()) for i in pool]
                )
                order = sorted(zip(pool, logits, strict=True), key=lambda kv: -kv[1])
        return [Hit(self.chunks[i], float(s), float(cos[i])) for i, s in order[:k]]


SECTION_LEAD = re.compile(r"^[A-Z]{2,4}-\d+(?:\.\d+)?\s*")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])|\n")
LIST_ITEM = re.compile(r"^(?:- |\d+\. )")
MAX_SENTENCE_WORDS = 60  # longer "sentences" are flattened tables: not useful as an answer


def sentences(chunk: Chunk, max_words: int = MAX_SENTENCE_WORDS) -> list[str]:
    """Sentences and list items of a section: wrapped lines joined, the heading line dropped."""
    lines = SECTION_LEAD.sub("", chunk.text).split("\n")
    if lines and lines[0].strip() == chunk.heading:
        lines = lines[1:]
    body = ""
    for line in lines:  # a new line only where a list item starts
        body += ("\n" if LIST_ITEM.match(line) else " ") + line
    out = []
    for part in SENTENCE.split(body):
        part = LIST_ITEM.sub("", part.strip())
        if 4 <= len(part.split()) <= max_words:
            out.append(part)
    return out


def section_text(chunk: Chunk, max_words: int = 120) -> str:
    """The whole section as plain text (tables included), cut after `max_words` words."""
    words = " ".join(sentences(chunk, max_words=10**6)).split()
    return " ".join(words[:max_words]) + (" …" if len(words) > max_words else "")


def extractive_answer(question: str, hits: list[Hit], scorer, max_sentences: int = 3) -> str:
    """Answer without a language model: the sentences of the retrieved sections that best
    match the question (scored by `scorer(question, sentences) -> scores`), in document order,
    each with its section id. Faithful by construction: every word comes from the documents."""
    candidates: list[tuple[int, int, str, str]] = []  # (hit rank, position, section, sentence)
    for r, hit in enumerate(hits):
        for p, sentence in enumerate(sentences(hit.chunk)):
            candidates.append((r, p, hit.chunk.section_id, sentence))
    if not candidates:
        return ""
    scores = np.asarray(scorer(question, [c[3] for c in candidates]), dtype=float)
    scores -= 0.15 * np.array([c[0] for c in candidates])  # prefer the best-ranked sections
    best = sorted(np.argsort(-scores)[:max_sentences], key=lambda i: candidates[i][:2])
    return " ".join(f"{candidates[i][3]} [{candidates[i][2]}]" for i in best)
