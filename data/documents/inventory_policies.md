---
doc_id: inventory_policies
title: Inventory Policies
version: 4.0
effective: 2026-10-30
owner: Inventory Control
---

# Inventory Policies

## INV-1 Item master

INV-1.1 The warehouse stocks 1,584 items (SKUs), each with a fixed home pick face. The SKU follows
the home bay: `P-` + zone letter + rack row + bay. Example: P-A-05-12 is picked from bay A-05-12
(Zone A, rack row y = 5, bay x = 12).

INV-1.2 Every item record holds: SKU, name, category, supplier, GTIN-13 of one unit, GTIN-14 of a
case, unit cost, unit weight (kg), packed volume (litres), units per case, cases per pallet,
pick-face minimum and maximum, ABC class, and whether the item is lot, expiry or serial
controlled.

INV-1.3 Categories are assigned per rack row, so all items in one row share a category and a
supplier. The ten categories are Electronics, Home & Kitchen, Apparel, Toys & Games, Books &
Media, Sports & Outdoors, Beauty & Health, Grocery, Office Supplies, and Tools & DIY.

INV-1.4 Expiry control: Grocery and Beauty & Health items carry a best-before date on every lot.
Serial numbers: Electronics items costing $60 or more carry a serial number per unit, tracked from
receipt to the order that shipped it.

INV-1.5 ABC class: items are ranked by recent units picked. A items make up the first 80 % of
units picked, B items the next 15 %, C items the rest. The classes are recalculated once a day.

## INV-2 Locations and stock records

INV-2.1 Every rack bay has four levels. Level 1 is the item's pick face (code ending -1, for
example A-05-12-1): the only place robots pick from. Levels 2-4 are reserve positions, each holding
one pallet or case stack of any item.

INV-2.2 Other locations: six dock doors DOCK-01 to DOCK-06 on the north wall, each with a staging
lane STAGE-01 to STAGE-06; the quarantine area QA-01; the returns area RET-01; the packing
stations PACK_1 to PACK_6; the carrier sort lanes and shipping doors (see the Shipping Policies).

INV-2.3 Stock is recorded per item, location, lot, status and license plate. A license plate (LPN)
is a pallet or case stack identified by an SSCC barcode; reserve positions always hold stock on a
license plate.

INV-2.4 Stock statuses: AVAILABLE, QC_HOLD (quality check, quarantine, returns), DAMAGED, EXPIRED
and HOLD (count investigation, recall or operator hold). Only AVAILABLE stock can be allocated to
orders.

INV-2.5 Available to promise (ATP) = available units in pick faces and reserve positions that are
not blocked, minus units already allocated to orders. A customer order can only be accepted for
items with ATP above zero.

INV-2.6 Every stock change is a transaction in the inventory ledger (RECEIVE, PUTAWAY, MOVE,
REPLENISH, ALLOCATE, PICK, SHORT_PICK, PACK, LOAD, SHIP, ADJUST, COUNT, STATUS, RETURN, SCRAP),
with the user, the reason and the reference document. The ledger is never edited; mistakes are
corrected with a new transaction.

## INV-3 Barcodes and scanning

INV-3.1 Barcodes follow GS1 standards. A unit carries an EAN-13 (GTIN-13). A case carries a GS1-128
label with AI (01) GTIN-14 of the case, (30) quantity, (17) expiry date and (10) lot.

INV-3.2 A pallet or case stack carries a GS1 logistic label: AI (00) SSCC-18 as its license plate
number, plus (02) content GTIN, (37) count, (17) expiry and (10) lot.

INV-3.3 Location labels show the location code as a Code 128 barcode and two large check digits
that a picker reads out to confirm being at the right place.

INV-3.4 The scan box accepts handheld scanners (keyboard wedge, with or without symbology prefixes
such as ]C1), the phone or laptop camera, or typed codes. A wrong check digit is reported and the
scan is not used.

## INV-4 Receiving and putaway

INV-4.1 Purchase orders are sent to the item's supplier. Each supplier sends an advance shipping
notice (ASN) listing every license plate on the truck with its SSCC, item, quantity, lot and
expiry. Supplier lead times are between 3 and 10 hours.

INV-4.2 A truck is given a free dock door when it arrives. Receiving: scan each plate's SSCC,
confirm the quantity, and report damaged units. Good units go to the door's staging lane on the
plate; damaged units go to quarantine QA-01 with status DAMAGED.

INV-4.3 A quantity different from the ASN is recorded on the purchase order and raises an alert to
the buyer. About 2 % of received plates contain damaged units.

INV-4.4 Directed putaway: the system tops up the item's pick face first (up to its maximum), then
sends the rest to the nearest free reserve position, preferring the same bay. Confirm the putaway
by scanning the destination location.

INV-4.5 Dock-to-stock time (truck arrival to putaway) is measured for every plate.

## INV-5 Allocation and picking

INV-5.1 Stock is allocated when an order is created, not when it is picked, so the same unit can
never be promised twice.

INV-5.2 Allocation takes stock from the pick face only, first expiry first out (FEFO) for expiry
controlled items and first in first out (FIFO) for the others.

INV-5.3 An order is released to the robots only when every line is allocated. If a pick face is
short, an urgent replenishment is raised and the order waits for stock (status WAITING_STOCK).

INV-5.4 Short pick: if the shelf holds fewer units than the system says, the robot picks what is
there, the missing units are recorded as SHORT_PICK, and a cycle count of that location is raised
automatically.

## INV-6 Replenishment and purchasing

INV-6.1 Pick-face replenishment: when a pick face's free stock falls below its minimum (about one
case), associates move stock from the item's reserve plates (earliest expiry first) to top the pick
face up to its maximum (about three cases).

INV-6.2 An urgent replenishment is raised when an order is waiting for stock at that pick face; it
is done before any other inventory work.

INV-6.3 Reorder point: each SKU is reordered from its supplier when its inventory position
(available to promise plus open purchase orders) falls to the reorder point = demand during the
supplier lead time + safety stock. Safety stock = 1.65 x sqrt(hourly demand x lead time in hours),
a 95 % cycle service level.

INV-6.4 Order quantity: up to the lead-time demand plus 4 hours of demand, rounded up to whole
pallets. Demand per SKU is learned from the units picked each hour (exponential smoothing).

## INV-7 Cycle counts

INV-7.1 Counts are blind: the counter reports what is on the shelf and never sees the system
quantity.

INV-7.2 Twelve pick faces are counted every hour, chosen by ABC class: A items six times as often
as C items, B items three times as often. Short picks raise an extra count of that location.

INV-7.3 A difference within 5 % of the expected quantity (at least one unit) is adjusted
automatically. A larger difference triggers a recount by another associate.

INV-7.4 If the recount confirms the difference and its value is below $150, it is adjusted
automatically. At $150 or more a supervisor must approve or reject it; a rejected count is counted
again.

INV-7.5 Inventory record accuracy = share of counted locations where the system was right (within
tolerance).

## INV-8 Holds, expiry, quarantine and returns

INV-8.1 Hold: put all free units of an item, or one lot, on HOLD (for example a supplier recall).
Held stock cannot be allocated. Release the hold to make it available again.

INV-8.2 Expiry: a lot past its best-before date is set to EXPIRED and moved to quarantine. Lots
within 7 days of expiry are reported as near expiry.

INV-8.3 Quarantine QA-01 holds damaged and expired stock until it is scrapped (SCRAP transaction
with a reason code).

INV-8.4 Customer returns arrive at RET-01 on QC_HOLD with a return number (RMA). Each return is
inspected: resaleable units are restocked to the pick face, damaged units are scrapped. About
1.5 % of shipped lines are returned.

## INV-9 Adjustments and reason codes

INV-9.1 Every adjustment needs a reason code: COUNT_VARIANCE, DAMAGED, FOUND, LOST, EXPIRED,
QUALITY, DATA_ERROR, RETURN_RESTOCK or RETURN_SCRAP.

INV-9.2 Only users with the adjust permission (inventory clerks and supervisors) may adjust stock;
count differences of $150 or more need a supervisor.

## INV-10 Demand planning

INV-10.1 Demand follows a daily rhythm: quiet at night (about a fifth of the average rate between
01:00 and 04:00) and busiest around 09:00-10:00 and 14:00-15:00 on weekdays. Weekends start later
and peak around midday.

INV-10.2 Saturdays carry about 80 % and Sundays about 66 % of a weekday's volume. Volume grows
through the autumn into the November peak season.

INV-10.3 Promotion days (Singles Day on 11 November, Black Friday, Cyber Monday) bring 12-22 % more
orders than a normal day of the same weekday. Raise stock of top sellers ahead of them.

INV-10.4 The demand forecast (orders per hour, by priority, category and zone) is used to plan
replenishment, charging and robot positioning.
