# Model card · Operator command understanding (Copilot, v1)

| | DistilBERT (live) | TF-IDF (fallback) | Rules (last resort) |
|---|---|---|---|
| **Task** | Read an operator's message: intent (17 kinds) + entities (13 types, BIO tags) | intent only (entities by regex) | keywords + regex |
| **Algorithm** | `distilbert-base-uncased` (66 M parameters) fine-tuned with two heads: intent on [CLS], tag on each word's first sub-word | word 1-2 + char 2-5 n-grams, Logistic Regression (C = 10) | hand-written patterns |
| **File** | `models/nlp_distilbert_v1/` (254 MB) · `notebooks/11_nlp_transformer.ipynb` | `models/nlp_tfidf_v1.joblib` · `notebooks/10_nlp_commands_baselines.ipynb` | `ai/nlp/intent_parser.py` |
| **Switch** | default when the folder exists | `WAREHOUSE_NLP_MODEL=tfidf` | `WAREHOUSE_NLP_MODEL=rules` |

## Intended use
Turn typed operator commands into tool calls for the Copilot page. The model only **understands**
the message; fixed code (`ai/nlp/commands.py`) builds the action, the live warehouse is checked,
and every action that changes the warehouse needs the operator's approval (ADR 006). Read-only
questions (robot status, waiting orders, stock, routes) are answered at once.

## Data
5,461 commands generated from phrasing templates (`scripts/generate_nlp_data.py`), with typos,
casing, fillers and number words; labels made by the same `normalize()` / `tool_calls()` functions
used live. Split by **template**: the test set (1,130) and the validation set (796, "honest
validation": whole templates held out from training) contain phrasings never seen in training.
No personal data.

## Evaluation (test, new phrasings)

| Parser | Intent accuracy | Entity F1 | **Exact tool call** | With typos | Approval right |
|---|---|---|---|---|---|
| Rules | 0.657 | 1.000 | 0.656 | 0.526 | 0.823 |
| TF-IDF + LR | 0.695 | 1.000 | 0.725 | 0.679 | 0.933 |
| **DistilBERT** | **0.803** | 0.999 | **0.807** | **0.762** | **0.965** |

* *Exact tool call* = intent, every entity value and the resulting action all right.
* **Confidence:** above 0.99 the intent is right 98.5 % of the time (531 messages); between 0.5
  and 0.9 about 55 %. Live: below 0.5 the copilot asks; below 0.9 a write proposal is marked
  "not sure, check first".
* Out-of-scope requests ("order me a pizza") recognised 52 % (TF-IDF 4 %).
* Speed on a laptop CPU: 18 ms per message in a batch, ~46 ms for a single message.

## Limitations
* **Opposites are the main error:** open → close aisle (25 test messages), resume → pause (23),
  reroute → close aisle (41). The live checks catch the opposites (an open aisle cannot be
  opened, a moving robot cannot be resumed) and the approval step stops the rest.
* Template-generated English only. Real operators' phrasing, other languages and voice input must
  be collected and labelled before trusting these numbers on a real site.
* `knowledge_query` is recognised but answered only from Phase 7 (RAG).
* One training seed; 5 epochs, best validation epoch kept (epoch 4).

## Licence
DistilBERT and the Hugging Face libraries are Apache-2.0 (see `THIRD_PARTY_LICENSES.md`).
