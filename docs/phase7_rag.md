# Phase 7 · RAG: the knowledge assistant

Phase 6 let operators *command* the warehouse; Phase 7 lets them *ask about the rules*:
"What do we do when a robot overheats?", "When is a product reordered?". The answers are in the
warehouse documents, not in any model's memory. **Retrieval-augmented generation (RAG)** finds the
right passages first, then answers from them only, citing each one, or says the documents do not
cover the question.

Details: [model card](model_cards/rag.md) · design decisions: [ADR 007](adr/007-rag-sections-rerank-extractive-default.md)
· experiment: `notebooks/12_rag.ipynb`.

## 1. How a question is answered

```
"What do we do when a robot overheats?"
   │ 1. retrieve   BM25 (keywords) + MiniLM embeddings (meaning) → fused ranking (RRF)
   │               → cross-encoder re-reads question + passage, keeps the best 3
   │               SOP-04 (6.78) · MG-6.2 (4.43) · RM-5.3 (3.63)
   │ 2. check      best score ≥ 0.663?  no → "not covered" + the closest passages
   ▼ 3. answer     the best section, quoted, with its id [SOP-04]   (or Claude, if configured)
```

* **Chunk**: the unit that is searched. Here one numbered section (SOP-04, WM-2.1 …), embedded
  together with its document title and heading.
* **Embedding**: a list of 384 numbers that places texts with similar meaning close together, so
  "the robot is too hot" finds "motor temperature above 60 C".
* **BM25**: keyword search; exact on ids and numbers ("CHG_3", "SOP-04"), blind to synonyms.
* **Reciprocal Rank Fusion**: merges two ranked lists by rank (1 / (60 + rank)), no score tuning.
* **Cross-encoder (reranker)**: reads question and passage *together*; slower but much better at
  putting the right passage first.

## 2. What was built

| Part | What | Where |
|---|---|---|
| Ingestion | PDF text (pypdf) → cleaned lines → section chunks or fixed windows | `ai/rag/ingest.py` |
| Embeddings | MiniLM wrapper (+ a hashing stand-in for tests) | `ai/embeddings/embedder.py` |
| Retrieval | BM25, dense, hybrid (RRF), rerank; doc-type filter | `ai/rag/retriever.py` |
| Vector store | pgvector table `warehouse_docs` (migration 003, HNSW index) or in memory | `ai/rag/store.py`, `scripts/ingest_documents.py` |
| Answers | extractive (sentences / whole section); optional Claude | `ai/rag/generator.py` |
| Pipeline | retrieve → not covered? → answer, settings from `models/rag_v1.json` | `ai/rag/pipeline.py` |
| Evaluation | hit@k, all@k, MRR, cite@1, token F1, not-covered decision | `ai/rag/evaluation.py`, `notebooks/12_rag.ipynb` |
| API | `POST /rag/query`, `GET /rag/status`, `/rag/documents`, `/rag/sections/{id}` | `apps/backend/app/api/v1/rag.py`, `services/knowledge.py` |
| Copilot | "what does the SOP say about …" is answered from the documents | `apps/backend/app/services/copilot.py` |
| Knowledge page | question box, document filter, answer with clickable citations, sources, section viewer, document browser | `apps/frontend/app/knowledge/page.tsx` |

## 3. Results (56 test questions; all choices made on 38 development questions)

| Setup | hit@3 | MRR | cite@1 | words read | time |
|---|---|---|---|---|---|
| Section chunks + dense search | 0.981 | 0.869 | 0.769 | 165 | 20 ms |
| **Section chunks + hybrid + rerank (chosen)** | 0.962 | **0.910** | **0.865** | 163 | ~0.7 s |

Development comparison (k = 3): 120-word windows reached hit@3 0.97 but cite@1 only 0.22 (one
window spans ~4 sections), sections + rerank cite@1 0.81. BM25 alone or dense alone: MRR ~0.68.

* **Not covered:** 3 of 4 unanswerable test questions refused; 7 of 52 answerable ones also
  refused (questions worded unlike the documents). The threshold was fixed on development data.
* **Answers:** cite a right section 0.889; word overlap with the reference answers 0.475 (whole
  section) vs 0.316 (3 best sentences).

## 4. Why extractive by default, and when to use Claude

Extractive answers are free, offline, instant and cannot invent anything, and their citation is
exact. They cannot combine two sections or rephrase a procedure. Setting `LLM_PROVIDER=anthropic`
and `LLM_API_KEY` in `.env` makes Claude write the answer from the same 3 sections, citing them,
replying NOT_COVERED when they do not answer the question; the threshold check still runs first,
and an API failure falls back to the extractive answer. Each question is then a paid API call, and
the question and sections are sent to Anthropic.

## 5. Run it

```bash
python scripts/build_knowledge_base.py      # Markdown sources -> PDFs, sections, questions
python scripts/train.py --model rag         # notebook 12: choose settings, evaluate (~5 min)
python scripts/ingest_documents.py --db     # optional: store chunks in pgvector
```

Open **Knowledge** in the app, or ask the Copilot "what does the SOP say about overheating?".
Without pgvector (e.g. a plain PostgreSQL on Windows) the backend reads the PDFs at start-up and
searches in memory; `GET /api/v1/rag/status` shows which.

Tests: `tests/unit/test_rag.py`, `apps/backend/tests/test_rag_api.py` (the pgvector test runs in
CI, where the database image has the extension), `tests/e2e/test_ui.py`.

## 6. Limits and next steps

* Real manuals: scanned pages (OCR), figures, versions, conflicting rules.
* Better "not covered": a trained relevance classifier, or let an LLM judge with the threshold.
* Query rewriting for questions phrased unlike the documents; multi-hop retrieval for questions
  that need two sections.
* Phase 8: the knowledge search becomes one tool of the agents.
