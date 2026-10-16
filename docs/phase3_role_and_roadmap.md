---
doc_id: phase3_role_and_roadmap
title: Phase 3 Role and the Remaining Phases
version: 1.0
effective: 2026-10-13
owner: NetSol training project
---

# Phase 3 Role and the Remaining Phases

## Is Phase 3 only for showing these four things?

Not just showing. Right now the four predictions are **advisory**: they tell the operator what is likely to happen, and the warehouse still runs on the old rules. Their real role starts in the next phases, where **the system uses them to make decisions automatically**.

## Phase 3: what it does now vs. later

| Model | Now (Phase 3) | Later, when it drives decisions |
|---|---|---|
| **ETA** | Shows when each order will arrive | **Phase 4:** the dispatcher gives each order to the robot predicted to finish **first**, not just the nearest |
| **Demand** | Shows the next-hour forecast | **Phase 4:** robots charge before a predicted rush and park near the zones about to get busy |
| **Late risk** | Warns about risky orders | **Phases 8-9:** an agent reprioritises or reassigns at-risk orders automatically |
| **Anomaly** | Flags abnormal robots (Alerts 5) | **Phases 8-9:** the maintenance agent pauses the robot, reassigns its work and raises a ticket (SOP-04) |

**In one line:** Phase 3 = the warehouse can **predict**. The next phases = it **acts** on those predictions.

## The remaining phases, up to the end

| Phase | What we build | What you'll see in the app |
|---|---|---|
| **4. Optimisation** | A* routing with traffic costs, ETA-based assignment, demand-based parking/charging, dynamic rerouting | A strategy switch (Baseline / AI) with KPIs compared side by side: completion time, late %, throughput |
| **5. Deep learning + vision** | LSTM/MLP vs. classical ML (benchmark); a YOLO detector trained on our 2,400 images | A "camera" view with boxes around robots, workers, parcels and closed aisles; detected hazards appear on the map |
| **6. NLP + Transformers** | Intent + entity model on the 5,461 commands (TF-IDF baseline, then a Transformer) | Type "pause robot 7" or "avoid aisle 12": understood and turned into the right command |
| **7. RAG** | PDFs, chunks, embeddings, pgvector, retrieval, LLM answer with its source | Knowledge page / copilot: "What do we do when a robot overheats?" gives the SOP-04 steps with the citation |
| **8. Tools + AI agents** | 15 safe tools, a supervisor agent with fleet, maintenance and knowledge agents; actions need approval | The **Copilot** chat runs tasks: "Robot 7 is blocking the lane, handle it": plan, approve, done; actions logged |
| **9. Advanced** | Multi-agent coordination, RL navigation prototype (rewards: delivery +10, collision -10) | An RL-controlled robot compared with A* |
| **10. Integration** | Everything connected: Frontend, API, AI orchestrator, models / RAG / agents, simulator, database | One working system, with predictions saved to the `predictions` table and agent actions to `agent_actions` |
| **11. Evaluation** | The progressive experiments: random, rules, ML, A*, agents, RL, all on the same seed | Analytics page with graphs: how much each layer improved the KPIs |
| **12. Finalisation** | Docker, documentation, final report, demo scenarios, presentation | A deployable project plus the final presentation |

## The full story in one line

**Phases 1-2:** a warehouse that runs. **Phase 3:** it predicts. **Phase 4:** it optimises. **Phase 5:** it sees. **Phase 6:** it understands language. **Phase 7:** it knows the rules. **Phases 8-9:** it acts by itself. **Phases 10-12:** everything connected, measured and delivered.

**Next step: Phase 4.** It's the first phase where the warehouse **behaves differently** because of AI. The ETA and demand models start making decisions, and we measure the improvement against today's rules.
