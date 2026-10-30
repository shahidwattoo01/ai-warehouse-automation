# ADR 008 — Inventory as a WMS ledger with GS1 identification, beside the simple model

**Status:** Accepted · 2026-10-28

## Context

Inventory was one number per rack bay: stock fell when a robot picked and reappeared by itself
when low. Nothing was reserved for orders, there were no lots, locations beyond the bay, suppliers,
receiving, counts or audit trail. Real warehouses run all of this in a WMS, and the professional
backlog (PR-07, PR-09, PR-11, PR-14) asks for it. Dataset v3, the trained models and the Phase 4
experiments were produced with the simple model and must stay reproducible.

## Decision

1. **A separate domain package (`wms/`), pure Python and deterministic** (its own random
   stream), used by the simulator, the API and the tests alike.
2. **Stock keyed by item × location × lot × status × license plate; every change is an
   append-only ledger transaction** (type, quantity, from/to, lot, plate, status, reason, reference,
   user, serials). Corrections are new transactions, never edits.
3. **Two books, system and physical.** The simulation changes only the physical shelf
   (shrinkage, finds); the system learns through short picks and blind cycle counts. This makes
   accuracy measurable.
4. **Allocation at order creation (FEFO/FIFO) at pick faces;** an order is released to robots
   only when fully allocated; reserve stock refills pick faces through replenishment tasks.
5. **GS1 identification:** GTIN-13/14 for items and cases, SSCC-18 for license plates, GS1-128
   application identifiers for lot, expiry, serial and quantity; one scan parser for everything;
   printable labels from the same encoder (reportlab).
6. **Associates as a labour pool with per-task automation switches,** so the work can be done by
   the simulation or by operators with scanners.
7. **The simple model stays** (`inventory_model: simple`); the backend defaults to `wms`.

## Consequences

* The simulator does more work per order: about 24 ms extra to list orderable items, measured on
  the large layout; robot path planning still dominates.
* Reproducibility tests and the Phase 3-5 results are unchanged (the simple model is the
  default in configs/simulation.yaml).
* KPIs that need the WMS (fill rate, inventory record accuracy, dock-to-stock) exist only in WMS
  runs; the Phase 4 experiments do not report them.
* The ledger can grow large over long runs; it is kept in memory for the run and stored in
  PostgreSQL (`wms_transactions`) when runs are recorded.
