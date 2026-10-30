# Inventory management (WMS)

The platform manages inventory as a warehouse management system (WMS) does. This replaces the
earlier model, which had one stock number per rack bay with deliveries appearing by themselves:
stock now lives by **item × location × lot × status × license plate**, and every change is a
**ledger transaction** with who, when, why and the reference document. Identification follows the **GS1**
standards used on real products and pallets.

Backend code: `wms/` (domain), `simulation/inventory/wms_stock.py` (simulator hook),
`apps/backend/app/api/v1/wms.py` (API). Screen: **Inventory** in the app. Decision record:
[ADR 008](adr/008-wms-inventory-ledger.md). The simple model is still available
(`INVENTORY_MODEL=simple`) because dataset v3 and the Phase 4 experiments were produced with it.

## 1. Master data

| Record | Content | Real-world equivalent |
|---|---|---|
| **Item** (1,584 SKUs) | GTIN-13 (unit, EAN-13 barcode), GTIN-14 (case), case quantity, cases per pallet, unit cost, weight, supplier, lot / expiry / serial control, ABC class, pick-face min/max | Item master |
| **Location** (6,356) | Rack bay × 4 levels: level 1 = the item's **pick face** (robots pick here), levels 2-4 = **reserve** positions holding one license plate each; 6 **dock doors** and their **staging** lanes, **quarantine**, **returns**, **packing** (shipping) | Location master, with check digits for voice or scan confirmation |
| **Supplier** (10) | One per category, lead time 3-10 simulated hours | Vendor master |
| **License plate (LPN)** | SSCC-18: one pallet or case stack, with its item, lot and quantity | Logistic unit |

Expiry-controlled categories (Grocery, Beauty & Health) carry best-before dates and are picked
**FEFO** (first expired, first out). Electronics above $60 are **serial-number** controlled: every
unit's serial is tracked from receipt to the order it shipped in.

## 2. Barcodes (GS1)

| Barcode | Data | Used on |
|---|---|---|
| EAN-13 | GTIN-13 of one unit | item label, the product itself |
| GS1-128 | (01) case GTIN-14 · (30) quantity | case label |
| GS1-128 | (00) SSCC | pallet label: the license plate |
| GS1-128 | (02) content GTIN · (37) count · (17) expiry · (10) lot | pallet label (content) |
| Code 128 | location code, e.g. `A-05-12-1`, + 2 check digits | location label |

`wms/barcodes.py` computes and checks the GS1 check digits and decodes what a scanner sends:
raw GS1 strings (FNC1 / group separators), bracketed text, symbology prefixes (`]C1`), GTINs,
SSCCs, location codes and `LPN…` plate codes. Labels are real PDFs for 4-inch thermal printers
(`wms/labels.py`): item 100 × 50 mm, location 100 × 40 mm, pallet 100 × 150 mm (GS1 logistic
label layout).

**Scanning in the app:** handheld USB or Bluetooth scanners act as keyboards (they type the code
and press Enter), so they work in every scan box. The camera button reads barcodes with a phone
or webcam where the browser supports it.

## 3. Processes

```
supplier ─► purchase order (reorder point reached) ─► ASN: plates with lot / expiry / SSCC
         ─► truck at a free dock door ─► RECEIVE: scan the plate, count, damaged units → quarantine
         ─► staging lane ─► PUTAWAY (directed): top up the pick face, the rest to a free reserve
            position (same bay first) ─► confirmed by scanning the location
order    ─► ALLOCATE at pick faces (FEFO / FIFO) ─► short at the pick face? urgent REPLENISH,
            the order waits ─► released to a robot ─► PICK ─► tote at the packing station
         ─► PACK, LOAD, SHIP when the carrier's truck leaves (outbound: docs/wms_outbound.md)
pick face below min ─► REPLENISH from reserve (whole cases, FEFO)
every simulated hour ─► demand update (per SKU), purchasing, cycle counts, expiry check,
                        returns arriving, (simulated) shrinkage on the shelves
```

* **Allocation:** stock is reserved when an order is created, so one unit is never promised to
  two orders. Available to promise (ATP) = available in storage − allocated.
* **Purchasing:** reorder point = demand over the supplier lead time + safety stock
  (z = 1.65, 95 % service level); order up to that plus 4 hours of demand, in whole plates. Demand
  per SKU is learned from picks (exponential smoothing), starting from a Zipf-like popularity:
  about 20 % of the items take about 70 % of the units.
* **Cycle counts:** ABC-weighted schedule (A items most often) plus exception counts after short
  picks. Counts are **blind** (the counter never sees the system quantity). A difference within
  5 % is booked; a larger one is **recounted** by someone else; a confirmed difference worth more
  than $150 waits for a **supervisor's approval**.
* **Two books:** the system book (what the WMS believes) and the physical shelf. The simulation
  makes small shelf losses and finds, as happen in reality, so short picks, count variances and
  **inventory record accuracy** are measured rather than assumed.
* **Holds and quality:** hold or release an item or one lot (e.g. a supplier recall); damaged
  units go to quarantine; expired lots are blocked and scrapped with reason codes.
* **Returns:** a share of shipped lines come back (RMA), are received on QC hold, inspected,
  restocked or scrapped.
* **Associates** (8) do receiving, putaway, replenishment, counts, quarantine and returns by
  priority (urgent replenishment first), with walking and handling time. Each task type can be
  switched to "by operators" in the Work queue, so the work waits for someone with a scanner.

Every adjustment needs a **reason code** (COUNT_VARIANCE, DAMAGED, FOUND, LOST, EXPIRED,
QUALITY, DATA_ERROR, RETURN_RESTOCK, RETURN_SCRAP) and is booked under the user's name.

## 4. The Inventory screen

| Tab | What |
|---|---|
| Overview | units, value, fill rate, inventory record accuracy, stockouts, inbound, alerts, open work |
| Items | search / scan, ABC and status filters; item panel with barcode, stock by location / lot / plate, allocations, reorder settings, purchase orders, history, label, hold, count |
| Receiving | purchase orders and trucks with their plates (pallet labels); the receiving station: scan plate → receive → scan destination |
| Locations & control | location master, label printing per rack row, contents, move and adjust with reasons |
| Cycle counts | blind counting, supervisor approvals, history |
| Work queue | open tasks by priority, associates, and which work is automatic |
| Ledger | every transaction, filtered by item, location, reference or user |

## 5. Results (one simulated day, large layout)

2,016 orders shipped; **fill rate 99.8 %** (12 of 6,115 units short-picked because the shelf
held fewer than the system said); **inventory record accuracy 93 %** of counted locations; 74
purchase orders and 90 plates received with about 4 simulated minutes from dock to stock; 169
replenishments; 17 returns; 3 count differences sent to a supervisor.

## 6. Data and API

The ledger (`wms_transactions`) and the balances (`wms_stock`) are stored in PostgreSQL for every
recorded run (migration 004). API under `/api/v1/wms`: `kpis`, `alerts`, `items`, `locations`,
`transactions`, `lots`, `scan`, `purchase-orders`, `receive`, `putaway`, `moves`,
`adjustments`, `holds`, `counts` (+ submit / decide), `tasks`, `settings`, `returns`, `labels/…`,
`barcode.svg`. Tests: `tests/unit/test_wms.py`, `apps/backend/tests/test_wms_api.py`,
`apps/backend/tests/test_run_store.py`, `tests/e2e/test_ui.py`.

## 7. Not yet (in the professional backlog)

* An inspection screen for returns: returns are inspected automatically today (PR-11).
  (Packing, labels, carriers and cut-offs are done: [wms_outbound.md](wms_outbound.md). Logins
  and roles are done: [authentication.md](authentication.md).)
* Scan events from simulated handhelds in the 3D view; associates are not drawn walking their
  tasks yet.
* The warehouse documents (RAG knowledge base) still describe the simple stock rules; they will be
  updated with the next knowledge-base revision.
