# Project documents

| Document | Purpose | Link |
| --- | --- | --- |
| Product Requirements (PRD) | What to build, scope, use cases, acceptance | https://claude.ai/code/artifact/433602ac-2463-4534-8ca3-9ad250104835 |
| Technical Requirements (TRD) | Architecture, simulator spec, API, AI module specs | https://claude.ai/code/artifact/ff69b626-c751-4431-8279-7ccc779d9550 |
| App Flow | Screens and operator / system flows | https://claude.ai/code/artifact/8bd65b78-7b00-4013-8668-4c5b92fd274b |
| UI/UX Design Brief | Visual direction, layout, components | https://claude.ai/code/artifact/a3876243-dfdd-4d2f-8923-b58866b1ee7e |
| Backend Schema | PostgreSQL tables, DDL, Pydantic models | https://claude.ai/code/artifact/b96b5e37-a986-4551-8108-37c1649c73b5 |
| Implementation Plan | 12 phases, tasks, exit criteria, tracker | https://claude.ai/code/artifact/5e318026-7ff9-43e0-a170-393cb9bcb714 |

## In this folder

| Document | Purpose |
| --- | --- |
| [phase4_optimization.md](phase4_optimization.md) | Phase 4: routing, assignment, positioning, charging; experiment design and results |
| [phase5_deep_learning_vision.md](phase5_deep_learning_vision.md) | Phase 5: deep learning for faults and demand, the YOLO detector, live integration, results |
| [phase6_nlp.md](phase6_nlp.md) | Phase 6: operator commands — dataset, baselines, DistilBERT, the Copilot and its approval step |
| [phase7_rag.md](phase7_rag.md) | Phase 7: the knowledge assistant — chunking, hybrid retrieval and reranking, not-covered, the Knowledge page |
| [wms_inventory.md](wms_inventory.md) | Inventory management (WMS): GS1 barcodes, lots and expiry, receiving and putaway, allocation, replenishment, purchasing, cycle counts, the ledger |
| [events.md](events.md) | Platform events for other systems: CloudEvents on MQTT topics, Server-Sent Events, replay, the catalogue |
| [erp.md](erp.md) | ERP connection: sales orders in (pull and signed webhook), ship confirmations and stock out (outbox), the mock ERP |
| [vda5050.md](vda5050.md) | VDA 5050 robot interface: the simulated robots as vehicles, the platform as master control, MQTT or in-process |
| [alerts.md](alerts.md) | Alert centre: rules, incidents, acknowledge / escalate / resolve, email and webhook notifications |
| [safety.md](safety.md) | Fleet safety: emergency and zone stops, release and reset, slow zones near people, the safety log, and what stays with certified robot safety (ISO 3691-4, ANSI/RIA R15.08) |
| [wms_outbound.md](wms_outbound.md) | Outbound: customer orders, holds, cancellations, backorders, waves, packing with weight check, GS1 shipping labels, carrier trucks and cut-offs |
| [authentication.md](authentication.md) | Users, roles and login: the permission table, how tokens work, setting up the first admin |
| [phase4_phase5_explained.md](phase4_phase5_explained.md) | Beginner's guide: every technique of Phases 4-5, how it works, why, and where the code is |
| [phase3_role_and_roadmap.md](phase3_role_and_roadmap.md) | Phase 3 role and the roadmap of all phases |
| [class_overview.md](class_overview.md) | Technical overview and dataset v3 |
| [model_cards/](model_cards/README.md) | One card per model: use, data, test results, limitations |
| [adr/](adr/) | Architecture decision records (001 3D rendering · 002 LSTM live · 003 demand default · 004 detector process · 005 safety thresholds · 006 copilot approvals · 007 RAG design · 008 WMS ledger · 009 login and roles) |

The main progress report (phase by phase, with KPIs) is `reports/Project_Progress_Report.pdf`;
security and licences: [SECURITY.md](../SECURITY.md), [THIRD_PARTY_LICENSES.md](../THIRD_PARTY_LICENSES.md).
