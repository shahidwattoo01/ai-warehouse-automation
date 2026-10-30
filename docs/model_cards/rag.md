# Model card · Knowledge assistant (RAG v1)

| | |
|---|---|
| **Task** | Answer operators' questions from the warehouse documents, citing the sections used; say "not covered" otherwise |
| **Documents** | 6 PDFs (operations manual, robot manual, safety rules, maintenance guide, SOPs, inventory policies), 120 numbered sections |
| **Retrieval** | BM25 + `all-MiniLM-L6-v2` embeddings (384-dim), Reciprocal Rank Fusion, `ms-marco-MiniLM-L6-v2` cross-encoder reranks the 10 best; top 3 used |
| **Answer** | Extractive: the best section, up to 120 words, with its id (default). Optional: Claude (`claude-opus-5-5`) from the same 3 sections |
| **Not covered** | best reranker score below 0.663 |
| **Files** | `models/rag_v1.json` · `notebooks/12_rag.ipynb` · `ai/rag/` · `apps/backend/app/services/knowledge.py` |
| **Store** | pgvector (`warehouse_docs`, `scripts/ingest_documents.py --db`) or in memory |

## Intended use
The Knowledge page and the Copilot's knowledge questions ("what does the SOP say about
overheating?"). Answers are information for the operator; the assistant takes no actions.

## Evaluation (56 test questions; every choice made on 38 development questions)

| | Chosen (section + rerank) | Simple (section + dense) |
|---|---|---|
| Right section in the top 3 (hit@3) | 0.962 | 0.981 |
| All needed sections in the top 3 (all@3) | 0.846 | 0.846 |
| MRR | **0.910** | 0.869 |
| First passage is a right citation (cite@1) | **0.865** | 0.769 |
| Time per question (laptop CPU) | ~0.6-1 s | ~20 ms |

* **Not covered:** 3 of 4 unanswerable test questions refused; 7 of 52 answerable ones wrongly
  refused (13 %).
* **Answers (extractive, whole section):** cite a right section 0.889; token F1 against the
  reference answers 0.475 (3-best-sentences style: 0.316).

## Limitations
* Extractive answers cannot combine sections or rephrase; when the reranker puts a neighbouring
  section first, the answer quotes it (the right one is then among the sources).
* "How much does an AMR-500 weigh?" looks like a manual question (score 3.5) and is answered from
  the nearest section: the threshold cannot catch every unanswerable question.
* 94 evaluation questions are few; the documents were written for this simulator. Real manuals
  bring scanned pages, figures, versions and contradictions.
* An LLM writer (optional) is a paid external service: questions and the retrieved sections are
  sent to the Anthropic API.

## Licences
sentence-transformers, both MiniLM models and pypdf are open source (Apache-2.0 / BSD-3-Clause);
see `THIRD_PARTY_LICENSES.md`.
