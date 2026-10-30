# ADR 007 — RAG: section chunks, reranked hybrid retrieval, extractive answers by default

**Status:** Accepted · 2026-10-24

## Context

The knowledge assistant (Phase 7) answers operators' questions from six warehouse documents
(120 numbered sections). Three choices shape it: how documents are cut into chunks, how chunks
are found, and who writes the answer. Answers must cite their source, and the assistant must say
when the documents do not cover a question instead of quoting the nearest passage.

All choices were made on 38 development questions; 56 test questions were scored once
(`notebooks/12_rag.ipynb`).

## Decision

1. **One chunk per numbered section** (WM-2.1, SOP-04 …), embedded with its document title and
   heading. Fixed 120-word windows found the right text slightly more often (they are three times
   longer) but their first passage was a correct citation only 22 % of the time, against 81 %.
2. **Hybrid retrieval (BM25 + MiniLM embeddings, Reciprocal Rank Fusion), then a cross-encoder
   reranks the 10 best**; the top 3 are used. The reranker lifts "right section first" from 0.67
   to 0.81 (development); test: hit@3 0.962, MRR 0.910, cite@1 0.865.
3. **"Not covered" before answering**: the best passage's reranker score must reach 0.663, the
   5th percentile of answerable development questions. The closest passages are still shown.
4. **Extractive answers by default**: the whole best section (up to 120 words) with its section
   id. Claude writes the answer instead only when `LLM_PROVIDER=anthropic` and a key are
   configured; it reads the same passages under the same threshold and falls back to the
   extractive answer if the API fails.
5. **pgvector when available, in-memory search otherwise**, with identical ranking (tested).

## Consequences

* Answers are faithful and exactly cited, free, and work offline; but they cannot combine two
  sections or rephrase (token F1 vs the reference answers 0.475), so some answers quote a
  neighbouring section (e.g. "can a person enter a closed aisle?" quotes the closing rule, while
  the entry rule is the second source).
* The threshold refuses 3 of 4 unanswerable test questions but also 7 of 52 answerable ones;
  questions phrased unlike the documents are the weak spot. It was not retuned on test.
* About 1 s of CPU per question (the cross-encoder), run in a worker thread so the simulator never
  waits. An LLM writer adds API latency and a per-question cost.
* The settings live in code defaults and `models/rag_v1.json` (equal; a test checks it).
