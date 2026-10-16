---
doc_id: inventory_policies
title: Inventory Policies
version: 3.0
effective: 2026-09-07
owner: Inventory Control
---

# Inventory Policies

## INV-1 Products and locations

INV-1.1 The warehouse stores 1,584 products (SKUs), one per rack bay.

INV-1.2 Product identifiers follow the bay location: `P-` + zone letter + rack row + bay. Example:
P-A-05-12 is stored in bay A-05-12 (Zone A, rack row y = 5, bay x = 12) on shelf SH-A-05-12.

INV-1.3 Every product record holds: product ID, name, category, unit weight (kg), shelf location,
zone and current stock.

INV-1.4 Categories are assigned per rack row, so all products in one row share a category. The ten
categories are Electronics, Home & Kitchen, Apparel, Toys & Games, Books & Media, Sports &
Outdoors, Beauty & Health, Grocery, Office Supplies, and Tools & DIY.

INV-1.5 Unit weights range by category, for example 0.1-2.0 kg for Beauty & Health and up to 15 kg
for Sports & Outdoors. Heavy orders take longer to pick.

## INV-2 Stock levels

INV-2.1 Opening stock per bay is between 20 and 120 units.

INV-2.2 Picking removes the ordered units from the bay at the moment the robot finishes the pick.

INV-2.3 Only products with stock above zero can be ordered. A product with zero stock is out of
stock until replenished.

## INV-3 Replenishment

INV-3.1 Reorder point: when a bay's stock falls below 10 units, a replenishment order is raised
automatically (one open replenishment per bay at a time).

INV-3.2 Replenishment lead time is 300-900 ticks. The delivery adds 60-120 units to the bay and is
logged as an INVENTORY_RESTOCKED event.

INV-3.3 Replenishment is done by associates from the dock apron on the north side (y 0-3), outside
robot picking hours for that aisle where possible.

## INV-4 Stock queries

INV-4.1 To check a product, query by product ID (for example "stock of P-A-05-12"). The answer
gives the units on hand, the location and whether a replenishment is on its way.

INV-4.2 The inventory screen lists all products with rack, category, weight, stock and restocking
status.

## INV-5 Accuracy and counts

INV-5.1 Cycle counts: every rack row is counted once a week; high-velocity rows (top 10 % by units
picked) twice a week.

INV-5.2 A count difference above 5 % of a bay's stock is investigated before the next pick from
that bay.

## INV-6 Demand planning

INV-6.1 Demand follows a daily rhythm: quiet at night (about a fifth of the average rate between
01:00 and 04:00) and busiest around 09:00-10:00 and 14:00-15:00 on weekdays. Weekends start
later and peak around midday.

INV-6.2 Saturdays carry about 80 % and Sundays about 66 % of a weekday's volume. Volume grows
through the autumn into the November peak season.

INV-6.3 Promotion days (Singles Day on 11 November, Black Friday, Cyber Monday) bring 12-22 % more
orders than a normal day of the same weekday. Raise stock of top sellers ahead of them.

INV-6.4 The demand forecast (orders per hour, by priority, category and zone) is used to plan
replenishment, charging and robot positioning.
