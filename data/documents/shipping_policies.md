---
doc_id: shipping_policies
title: Shipping and Outbound Policies
version: 1.0
effective: 2026-10-30
owner: Outbound Operations
---

# Shipping and Outbound Policies

## SHP-1 Customers and carriers

SHP-1.1 Every customer order belongs to a customer with a ship-to address, city and postal code.
Customers are retail stores (B2B) or online sellers (B2C). A customer record also says whether the
customer accepts partial shipments (about 70 % do).

SHP-1.2 Three carriers collect from the shipping doors on the south wall. The carrier is chosen by
order priority:

| Priority | Carrier | Service | Shipping door | Trucks leave at |
|---|---|---|---|---|
| HIGH | Swiftline Couriers | Express | SHIP-01 | 07:00, 12:00, 17:00, 22:00 |
| MEDIUM | RoadLink Parcel | Standard | SHIP-02 | 09:00, 15:00, 21:00 |
| LOW | Freightway Cargo | Economy | SHIP-03 | 06:00, 18:00 |

SHP-1.3 Cut-off: cartons must be ready 30 minutes before their truck leaves. Each order is promised
the first truck whose cut-off is at least 15 minutes after the order's robot deadline (time to
pack).

## SHP-2 Order life cycle

SHP-2.1 Customer order statuses: WAITING_STOCK (not all lines allocated yet), ON_HOLD, READY
(allocated, waiting for release), RELEASED (robots may pick it), PICKING, AT_PACK (the robot
dropped its tote at a packing station), PACKED, LOADED (all cartons on the trailer), SHIPPED (the
truck left), CANCELLED.

SHP-2.2 Every change is written to the order's history with the time and the user.

SHP-2.3 The robot deadline of an order (HIGH 240, MEDIUM 480, LOW 900 ticks) is unchanged; the
truck it is promised comes after it. On-time shipping is measured against the promised truck.

## SHP-3 Release to the robots

SHP-3.1 Continuous release (the default): an order is released as soon as all its lines are
allocated. This keeps the robot deadlines and suits a robot fleet.

SHP-3.2 Wave release (optional): every 10-60 minutes the ready orders are released together,
earliest truck first, at most 80 per wave. Hot orders, whose robot deadline comes before the next
wave, are released at once. Waves make robot deliveries later, so use them only when packing or
loading must be grouped by truck.

SHP-3.3 A supervisor or operator may release a ready order early by hand ("Release now").

## SHP-4 Packing

SHP-4.1 Robots drop each order in its own tote (TOTE-order number) at a packing station, so orders
never mix. One packer works at each packing station.

SHP-4.2 Cartons: S (6 litres, up to 5 kg), M (18 litres, up to 12 kg) and L (40 litres, up to
20 kg), filled to at most 80 % of their volume. The packer fills the largest carton first with the
biggest units, then each carton gets the smallest size its contents fit. Light bulky items such as
apparel and toys often need an L carton.

SHP-4.3 Each carton gets an SSCC (its license plate) and the carrier's tracking number, and is
weighed. If the weight differs from the expected weight by more than 3 % (at least 50 g), the
carton fails the weight check: re-open it, correct the contents and weigh again (audit) before it
may leave the station.

SHP-4.4 Shipping label (100 x 150 mm): ship-from and ship-to address, carrier and service, carton n
of N, the tracking number as a Code 128 barcode, the ship-to postal code as GS1-128 AI (420), and
the carton's SSCC with its gross weight as AI (00) and (3301).

## SHP-5 Sorting, loading and departure

SHP-5.1 After packing, cartons go to their carrier's sort lane (LANE-EXP, LANE-STD, LANE-ECO). Two
dock loaders load them onto the carrier's trailer at its shipping door; loading is confirmed by
scanning the carton.

SHP-5.2 A carton goes on its carrier's next truck, so an order ready early leaves early.

SHP-5.3 When the truck leaves, its cartons leave the stock (SHIP transaction), a manifest lists
every carton with its tracking number, customer and weight, and a ship confirmation per order
(tracking numbers, units shipped) is kept for the business system.

SHP-5.4 Missed truck: an order still in the building when its promised truck leaves has missed it.
It moves to the carrier's next truck and counts as late. Each departure reports how many orders
missed it.

## SHP-6 Holds, cancellations, partial shipments and backorders

SHP-6.1 About 1 % of new orders are held for a credit check and released automatically after
20-90 minutes. Operators and supervisors may hold an order that is not on a robot yet, with a
reason. Held orders are never released to the robots.

SHP-6.2 Cancel: possible until the order is loaded. Allocated stock is freed. If the order was
already picked or packed, a dock loader puts the units back on their pick faces. An order on a
robot cannot be cancelled until the robot reaches packing.

SHP-6.3 Partial shipment: an order waiting for stock longer than 60 minutes ships what is allocated
if the customer accepts partial shipments; the missing units become a backorder. Operators can also
choose "Ship what is in stock" earlier. Customers who do not accept partial shipments keep waiting
and an alert is raised.

SHP-6.4 Short-picked units become a backorder for customers who accept partial shipments, and are
recorded as shipped short for the others.

SHP-6.5 Backorder: when the stock is available again, a follow-up order for the same customer is
created automatically and picked like any other order.

## SHP-7 Shipping KPIs

SHP-7.1 On-time shipping: share of shipped orders that left on or before their promised truck.
Read it together with missed trucks: orders that missed a truck count only when they ship.

SHP-7.2 Order to truck: minutes from order creation to the truck leaving; mostly set by the truck
schedule. Other indicators: pack queue (totes waiting), cartons in the lanes, cartons per order,
weight-check failures, units backordered.
