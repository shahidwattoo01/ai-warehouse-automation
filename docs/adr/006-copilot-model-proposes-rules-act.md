# ADR 006 — The language model only understands; rules build the action, and the operator approves it

**Status:** Accepted · 2026-10-23

## Context

Phase 6 lets an operator type commands such as "pause R-12 now" or "close aisle 30 for
maintenance". A language model reads the message. A model is never 100 % right, though, and a
wrong action in a warehouse (pausing the wrong robot, closing an aisle with a robot inside it) has
a real cost. The question is how much the model is allowed to decide.

## Decision

1. **The model predicts two things only:** the intent (17 kinds) and the entity spans (BIO tags
   for robot, order, aisle, product …). It never writes the tool call itself.
2. **Deterministic code turns them into the action** (`ai/nlp/commands.py`): `normalize()` maps
   "robot twelve" / "R-12" to `R12`, and `tool_calls()` builds the call from the intent and the
   values. The same functions label the training data, so training and serving cannot disagree.
3. **The live warehouse is checked before anything is proposed** (`Copilot.problems`): the robot
   exists, it is not already paused, the order is still waiting, the aisle has no robot, pick or
   worker inside it …
4. **Read-only tools run at once; every write tool is a proposal.** It runs only after the
   operator clicks *Approve* (checked against the warehouse again at that moment). Proposals
   expire after 5 minutes. Answers and executed actions go into an audit trail.
5. **Low confidence (< 0.5) or a missing entity** gives a question back instead of an action.
6. Write actions use the **same simulator commands as the UI buttons**, never direct state changes.

## Consequences

* A misread message can at worst propose a wrong action that the operator sees and cancels. It
  cannot change the warehouse on its own.
* Tool calls are reproducible and testable without the model (`tests/unit/test_nlp.py`); the
  model can be swapped (rules → TF-IDF → DistilBERT) behind the same `parse()` interface.
* The copilot cannot do things outside the 17 intents, and rephrasings the model has not learned
  fall back to a question. A generative LLM with free tool calling (Phase 8 agents) is more
  flexible; the approval step and the checks stay in place for it.
* An operator must click once more for every write action: deliberate friction for actions that
  move robots or block aisles.
