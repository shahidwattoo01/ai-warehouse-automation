# Phase 6 · NLP + Transformers: operator commands

Phases 3-5 made the warehouse predict, decide and see. Phase 6 lets the operator **talk to it**:
typed commands such as "pause R-12 now", "how many high priority orders are waiting?" or "close
aisle 30 for maintenance". Two questions:

1. How well can a model understand commands phrased in ways it has **never seen**?
2. How do we let a model that is sometimes wrong act on a real warehouse **safely**?

Model details are in the [model card](model_cards/nlp.md); the safety design is
[ADR 006](adr/006-copilot-model-proposes-rules-act.md).

## 1. How a message becomes an action

```
"pause R-12 now"
   │ 1. model: intent + entity spans       pause_robot (99.9 %), ROBOT "R-12"
   │ 2. normalize (fixed rules)            ROBOT "R-12" → R12
   │ 3. tool call (fixed rules)            pause_robot(robot_id=R12)   → write tool: needs approval
   │ 4. checks against the live warehouse  R12 exists, is not already paused
   ▼ 5. read tool → answer now · write tool → Approve / Cancel card → simulator command → audit trail
```

* **Intent:** what the operator wants (17 kinds, e.g. `robot_status`, `close_aisle`, `out_of_scope`).
* **Entities:** the things named, found as **BIO tags** (one label per word: B- begins an entity,
  I- continues it, O outside). 13 types: robot, order, product, location, station, charger,
  parking, aisle, zone, priority, quantity, reason, mode.
* Below 0.5 confidence, or with a required entity missing, the copilot asks a question instead.
  Write proposals below 0.9 confidence are marked *not sure, check first*.

## 2. What was built

| Part | What | Where |
|---|---|---|
| Dataset | 5,461 commands from phrasing templates, with typos, casing, fillers, number words; split by template | `scripts/generate_nlp_data.py` → `data/processed/nlp/` |
| Shared rules | Canonical values, tool calls, approval, BIO tags: used both to label the data and live | `ai/nlp/commands.py`, `ai/nlp/understanding.py` |
| Baselines | Keyword rules + regex entities; TF-IDF (words + characters) + Logistic Regression | `ai/nlp/intent_parser.py`, `notebooks/10_nlp_commands_baselines.ipynb` |
| Transformer | DistilBERT with an intent head and a BIO tag head on one encoder | `ai/transformers/intent_transformer.py`, `notebooks/11_nlp_transformer.ipynb` |
| Evaluation | Intent accuracy / F1, entity P/R/F1 on values, exact tool call, approval, typo noise | `ai/nlp/evaluation.py` |
| Engine commands | `close_aisle` (until reopened), `open_aisle`, `reroute_robot` (avoid aisles or a zone) | `simulation/environment/engine.py`, `hazards.py`, `robots/controller.py` |
| Copilot service | Parser loading and fallback, live checks, proposals (5 min), approve / reject, audit trail | `apps/backend/app/services/copilot.py` |
| API | `POST /copilot/chat`, `/parse`, `/actions/{id}/approve`, `/reject`; `GET /status`, `/history` | `apps/backend/app/api/v1/copilot.py` |
| Copilot page | Chat, what the model understood, approval cards, examples, audit trail | `apps/frontend/app/copilot/page.tsx` |

## 3. Results (test: 1,130 messages from templates never seen in training)

| Parser | Intent accuracy | Entity F1 | Exact tool call | With typos | ms / message (CPU) |
|---|---|---|---|---|---|
| Rules | 0.657 | 1.000 | 0.656 | 0.526 | 0.1 |
| TF-IDF + LR | 0.695 | 1.000 | 0.725 | 0.679 | 2.6 |
| **DistilBERT** | **0.803** | 0.999 | **0.807** | **0.762** | 18 |

* **Why the Transformer wins:** it reads words in context and was pretrained on a lot of English,
  so it handles new phrasings that share few words with the training templates. It fixed 164 messages TF-IDF got wrong and broke 41.
* **Entities were already solved** by regexes, because IDs follow fixed patterns (R12, AISLE 30).
  The hard part is the intent.
* **Confidence can be trusted at the top:** above 0.99 → 98.5 % right; 0.5-0.9 → about 55 %.
* **Errors that remain:** opposites and neighbours (open/close aisle, resume/pause,
  reroute/close aisle, route planning/reroute): their templates share almost every word. The
  live checks catch the opposites, and approval stops the rest.
* **Honest validation:** model choices were made on held-out *templates*, not random messages,
  because random messages from the same template are near-copies of training messages. These
  validation scores are pessimistic (baselines about 0.49 vs 0.66-0.72 on test) but never
  over-optimistic.

## 4. Safety: the model proposes, rules and people decide

* The model never writes a tool call; fixed code does, so actions are reproducible and testable.
* Read-only tools run at once; write tools (pause, resume, assign, create order, close / open
  aisle, reroute, assignment mode) need the operator's approval and are checked again when
  approved (the warehouse may have changed).
* Write actions go through the same simulator commands as the UI buttons; every answered or
  executed command is in the audit trail (`GET /copilot/history`).

## 5. Run it

```bash
python scripts/generate_nlp_data.py      # commands -> data/processed/nlp/
python scripts/train.py --phase 6        # notebooks 10 and 11 (~30 min CPU for DistilBERT)
```

Start the app and open **Copilot** (or press the "Ask Copilot" button in the header). Without the
DistilBERT folder the backend uses TF-IDF, then rules (`GET /api/v1/copilot/status` shows which).

Tests: `tests/unit/test_nlp.py`, `tests/unit/test_operator_commands.py`,
`apps/backend/tests/test_copilot_api.py`.

## 6. Limits and next steps

* Synthetic, template-generated English; real operators' phrasing must be collected and labelled.
* More paraphrases or contrastive examples for the confused pairs.
* `knowledge_query` ("what is the battery policy?") is recognised but answered in Phase 7 (RAG).
* Phase 8 replaces fixed intents with an agent that plans several tool calls, keeping the same
  checks and approval step.
