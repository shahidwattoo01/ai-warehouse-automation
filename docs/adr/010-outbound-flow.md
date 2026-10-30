# ADR 010: Outbound flow: totes, cartons, scheduled trucks; robot deadlines unchanged

**Status:** accepted · 30 Oct 2026 · backlog PR-08 and PR-28

## Context

Orders ended when the robot reached a packing station: the stock left the books right there, and
nothing knew about customers, cartons, carriers or trucks. In a real warehouse that is about half
of the work: packing, labelling, sorting, loading, and the truck departure that decides whether an
order is on time. Customers also expect holds, cancellations and partial shipments.

## Decision

1. **Separate module, same ledger.** `wms/outbound.py` owns customer orders, cartons, trips,
   waves and backorders; every unit still moves through the inventory ledger (`MOVE` into the
   order's tote at the station, `PACK` into a carton, `MOVE` to the carrier's lane, `LOAD` onto
   the trailer, `SHIP` when the truck leaves). Stock only leaves the books at departure.
2. **One tote per order at the station.** The robot drops the order into a license plate
   `TOTE-<order>`, so orders waiting at the same station never mix (a real AMR carries a tote).
3. **Trucks leave on a fixed schedule; the cut-off is 30 min before.** Three fictitious carriers,
   chosen by priority (HIGH = express, MEDIUM = standard, LOW = economy). An order is promised
   the first truck whose cut-off is after its pick-by deadline plus 15 min of packing. A carton
   goes on the carrier's next truck, so early orders leave early; an order still open when its
   truck leaves has *missed* it and is re-planned (counted in `missed_trucks`, on-time rate).
4. **The robot deadline is not changed.** Cut-offs could have tightened the robot deadlines, but
   the prediction models (ETA, late risk, demand) were trained on the generator's deadlines;
   changing them in the live WMS mode would put their inputs out of distribution. The shipping
   promise is derived *from* the robot deadline instead, and measured separately.
5. **Continuous release is the default; waves are an option.** Robot fleets usually work
   waveless (an order goes as soon as its stock is allocated). Wave release (every 10-60 min,
   earliest truck first, hot orders at once) is available for experiments and in the UI.
6. **Separate crews.** One packer per packing station and two dock loaders, so outbound work never
   delays receiving, putaway or replenishment (each crew only takes its own task types).
7. **Weight check by simulation.** The scale reads the expected weight ±0.8 %; 0.4 % of cartons
   get a wrong unit and fail the ±3 % (min 50 g) tolerance, and go to an audit.
8. **Backorders through the simulator.** When stock arrives for an open backorder, the WMS asks
   the engine for a follow-up order (`take_new_orders`), so it is picked by robots like any other
   order. The simple inventory model returns none, so the golden-master run is unchanged.

## Consequences

* The order to truck time (minutes) is now the business KPI next to the robot delivery KPIs; it
  is dominated by the truck schedule, not by the robots.
* The live order list on the robot side still drops finished orders after 50; the customer order
  keeps a day of history in the WMS, and the ledger keeps everything.
* Not covered: carrier rating and choice by cost, parcel dimensions from a cubiscan, multi-stop
  routes, dock appointment scheduling, ZPL printing (PR-30) and a handheld packing screen (PR-29).
