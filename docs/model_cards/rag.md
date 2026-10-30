# Model card · Knowledge assistant (RAG v1, knowledge base v2)

| | |
|---|---|
| **Task** | Answer operators' questions from the warehouse documents, citing the sections used; say "not covered" otherwise |
| **Documents** | 7 PDFs (operations manual, robot manual, safety rules, maintenance guide, SOPs, inventory policies, shipping policies), 178 section chunks |
| **Retrieval** | BM25 + `all-MiniLM-L6-v2` embeddings (384-dim), Reciprocal Rank Fusion, `ms-marco-MiniLM-L6-v2` cross-encoder reranks the 10 best; top 3 used |
| **Answer** | Extractive: the best section, up to 120 words, with its id (default). Optional: Claude (`claude-opus-5-5`) from the same 3 sections |
| **Not covered** | best reranker score below -0.656 (chosen on development data) |
| **Files** | `models/rag_v1.json` · `notebooks/12_rag.ipynb` · `ai/rag/` · `apps/backend/app/services/knowledge.py` |
| **Store** | pgvector (`warehouse_docs`, `scripts/ingest_documents.py --db`) or in memory |

## Intended use
The Knowledge page and the Copilot's knowledge questions ("what does the SOP say about
overheating?", "when does the express truck leave?"). Answers are information for the operator;
the assistant takes no actions.

## Knowledge base versions

| | v1 (Phase 7, 25 Oct 2026) | v2 (30 Oct 2026, PR-27) |
|---|---|---|
| Documents | 6, simple stock rules | 7: inventory policies rewritten for the WMS, shipping policies added, emergency stop / slow zones / safety log, SOP-11 and SOP-12 |
| Questions (dev / test) | 94 (38 / 56) | 119 (48 / 71) |

The retrieval and answer design is unchanged; settings were chosen again on the v2 development
questions (the same chunking, retriever, k and answer style won; the threshold moved).

## Evaluation (v2: 71 test questions; every choice made on 48 development questions)

| | Chosen (section + rerank) | Simple (section + dense) |
|---|---|---|
| Right section in the top 3 (hit@3) | 0.970 | 0.896 |
| All needed sections in the top 3 (all@3) | 0.910 | 0.836 |
| MRR | **0.908** | 0.761 |
| First passage is a right citation (cite@1) | **0.851** | 0.642 |
| Time per question (laptop CPU) | ~0.6 s | ~20 ms |

* **Not covered:** 4 of 4 unanswerable test questions refused; 4 of 67 answerable ones wrongly
  refused (6 %). (v1: 3 of 4, and 7 of 52 = 13 %.)
* **Answers (extractive, whole section):** cite a right section 0.841; token F1 against the
  reference answers 0.495 (3-best-sentences style: 0.347).
* v1 test results for comparison: hit@3 0.962, MRR 0.910, cite@1 0.865.

## Limitations
* Extractive answers cannot combine sections or rephrase; when the reranker puts a neighbouring
  section first, the answer quotes it (the right one is then among the sources).
* More documents compete for the same words: "How long does a robot spend picking and unloading?"
  now retrieves shipping sections before the warehouse manual's WM-5.5.
* The threshold cannot separate every unanswerable question: retrieval scores of answerable and
  unanswerable questions overlap.
* 119 evaluation questions are few; the documents were written for this simulator. Real manuals
  bring scanned pages, figures, versions and contradictions.
* An LLM writer (optional) is a paid external service: questions and the retrieved sections are
  sent to the Anthropic API.

## Licences
sentence-transformers, both MiniLM models and pypdf are open source (Apache-2.0 / BSD-3-Clause);
see `THIRD_PARTY_LICENSES.md`.
