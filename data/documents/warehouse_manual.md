---
doc_id: warehouse_manual
title: Warehouse Operations Manual
version: 3.0
effective: 2026-09-07
owner: Operations
---

# Warehouse Operations Manual

## WM-1 Purpose and scope

WM-1.1 This manual describes the layout, naming conventions, traffic rules and performance
measures of the automated warehouse operated with 40 autonomous mobile robots (AMRs).

WM-1.2 It applies to operators in the control center, floor associates, maintenance technicians
and the AI operations copilot. Robot details are in the Robot Manual, safety rules in the Safety
Rules, step-by-step procedures in the Standard Operating Procedures (SOPs), repair work in the
Maintenance Guide and stock rules in the Inventory Policies.

## WM-2 Building layout

WM-2.1 The building floor is 80 m wide (east-west, x = 0 to 79) and 50 m deep (north-south,
y = 0 to 49). The floor is managed as a grid of 1 m x 1 m cells; every location is written as
(x, y), with (0, 0) in the north-west corner.

WM-2.2 Storage is split into four zones:

| Zone | Name | Area (x, y) | Position |
|---|---|---|---|
| ZONE_A | Zone A | x 3-37, y 4-21 | north-west |
| ZONE_B | Zone B | x 42-76, y 4-21 | north-east |
| ZONE_C | Zone C | x 3-37, y 24-42 | south-west |
| ZONE_D | Zone D | x 42-76, y 24-42 | south-east |

Each zone is planned for up to 10 robots at a time. Zone congestion is the number of robots in the
zone divided by 10 (1.0 = at capacity).

WM-2.3 Highways (two-way roads):
- North highway and dock apron: y 0-3, along the whole north wall.
- Cross highway: y 22-23, between the north and south storage blocks.
- South highway: y 43-45, in front of the packing lane.
- Main highway: x 38-41, four lanes running north-south through the middle of the building.
- Side lanes: x 0-2 (west wall) and x 77-79 (east wall), where the chargers are.
- Cross aisles: x 19-20 and x 59-60, cutting through each storage block.

WM-2.4 Structural columns stand on the main highway at (38, 12), (41, 12), (38, 34) and (41, 34).
Columns are permanent obstacles; robots plan around them.

WM-2.5 The packing lane is y 47-49. Six packing stations stand on the south wall (y = 49):

| Station | Position (x, y) |
|---|---|
| PACK_1 | (7, 49) |
| PACK_2 | (20, 49) |
| PACK_3 | (33, 49) |
| PACK_4 | (46, 49) |
| PACK_5 | (59, 49) |
| PACK_6 | (72, 49) |

Each packing station has three drop bays along the front of its bench, so up to three robots can
unload at the same time.

WM-2.6 Four charging stations stand on the side walls, each with three charging bays (12 bays):

| Charger | Position (x, y) | Wall |
|---|---|---|
| CHG_1 | (0, 10) | west |
| CHG_2 | (0, 35) | west |
| CHG_3 | (79, 10) | east |
| CHG_4 | (79, 35) | east |

WM-2.7 Eight parking areas (88 bays in total) line the walls, away from through-traffic:

| Area | Name | Cells |
|---|---|---|
| P1 | North-west | x 4-17, y 0 |
| P2 | North-east | x 62-75, y 0 |
| P3 | West | x 0, y 14-20 |
| P4 | East | x 79, y 14-20 |
| P5 | South-west wall | x 0, y 25-31 |
| P6 | South-east wall | x 79, y 25-31 |
| P7 | South-west | x 3-18, y 46 |
| P8 | South-east | x 61-76, y 46 |

## WM-3 Racking and locations

WM-3.1 Storage racks are back-to-back double rows, four levels high. There are 1,584 rack bays.
Each bay holds exactly one product (SKU).

WM-3.2 Location code: `Z-RR-BB`, where Z is the zone letter, RR the rack row (its y coordinate,
two digits) and BB the bay (its x coordinate, two digits). Example: `A-05-12` is in Zone A, rack
row y = 5, bay x = 12. The shelf identifier adds the prefix `SH-` (SH-A-05-12) and the product
stored there has the identifier `P-` plus the location (P-A-05-12).

WM-3.3 Robots never enter a rack. They stop on the pick face: the walkable aisle cell directly
beside the bay (normally the cell to the south, otherwise the cell to the north). Example: bay
A-05-12 is picked from (12, 4), in Aisle 1.

WM-3.4 Each rack row holds one product category, so related goods are stored together. The ten
categories are Electronics, Home & Kitchen, Apparel, Toys & Games, Books & Media, Sports &
Outdoors, Beauty & Health, Grocery, Office Supplies, and Tools & DIY.

## WM-4 Picking aisles

WM-4.1 Picking aisles run east-west between rack rows. They are one robot wide and one-way.
Directions alternate, so two robots never meet head-on in an aisle.

WM-4.2 There are 52 numbered aisles (Aisle 1 to Aisle 52, identifiers AISLE_01 to AISLE_52),
numbered in reading order: north to south, then west to east. Each aisle row has four segments:
x 3-18 and x 21-37 (Zone A or C) and x 42-58 and x 61-76 (Zone B or D).

| Aisle numbers | Row (y) | Direction | Zones |
|---|---|---|---|
| 1-4 | 4 | east | A, A, B, B |
| 5-8 | 7 | west | A, A, B, B |
| 9-12 | 10 | east | A, A, B, B |
| 13-16 | 13 | west | A, A, B, B |
| 17-20 | 16 | east | A, A, B, B |
| 21-24 | 19 | west | A, A, B, B |
| 25-28 | 24 | east | C, C, D, D |
| 29-32 | 27 | west | C, C, D, D |
| 33-36 | 30 | east | C, C, D, D |
| 37-40 | 33 | west | C, C, D, D |
| 41-44 | 36 | east | C, C, D, D |
| 45-48 | 39 | west | C, C, D, D |
| 49-52 | 42 | east | C, C, D, D |

Example: Aisle 7 is the third segment of row y = 7 (x 42-58, Zone B) and is driven westwards.

WM-4.3 An aisle may be closed temporarily (see SOP-05). A closed aisle is marked with barriers at
both ends; no robot plans a route through it.

## WM-5 Order flow

WM-5.1 Customer orders arrive continuously. Each order has one or two order lines (different
products) of one to three units each, a priority and a deadline.

WM-5.2 Priority mix and deadlines (ticks of the simulation clock; at normal speed a tick is half a
second):

| Priority | Share of orders | Deadline after creation |
|---|---|---|
| HIGH | about 20 % | 240 ticks (2 minutes) |
| MEDIUM | about 50 % | 480 ticks (4 minutes) |
| LOW | about 30 % | 900 ticks (7.5 minutes) |

An order delivered after its deadline is recorded as LATE.

WM-5.3 Order life cycle: PENDING (waiting) -> ASSIGNED (a robot accepted it) -> IN_PROGRESS
(picking started) -> DELIVERED or LATE (dropped at a packing station).

WM-5.4 Automatic assignment (dispatcher): waiting orders are taken highest priority first, then
oldest first. Each goes to the nearest free robot that has at least 20 % battery, measured to the
order's first rack. Orders that need a rack in a closed aisle wait until it reopens.

WM-5.5 A robot visits the racks in order, spends 4 ticks per order line at the rack face, then
drives to the packing station nearest its last rack, chooses the least busy of its three drop
bays and unloads in 3 ticks.

WM-5.6 Manual assignment: an operator can switch the warehouse to manual mode. The dispatcher then
assigns nothing and operators assign each order to a robot themselves (see SOP-08).

## WM-6 Traffic rules

WM-6.1 Only one robot may occupy a cell. Before every step a robot checks that the next cell is free
of robots, people and obstacles.

WM-6.2 When the cell ahead is taken, a robot:
1. queues for up to 20 ticks if the robot ahead is working (picking, dropping or charging);
2. otherwise replans around nearby robots after 2 blocked ticks;
3. steps aside into a free neighbouring cell after 4-7 blocked ticks, to break a standoff.

WM-6.3 Parking bays may only be entered by a robot parking there; routes never cut through them.

WM-6.4 Floor associates (8 per shift) walk at about 1 m/s. Robots treat them as obstacles and wait
or replan; associates give way to moving robots.

## WM-7 Idle robots, parking and charging

WM-7.1 A robot with no task parks in a parking bay. It chooses a bay that is close but also in an
area that is not already full (cost = distance in metres + 150 x share of that area's bays taken),
so idle robots stay spread around the building.

WM-7.2 Charging rules are in the Robot Manual (RM-4) and SOP-01.

## WM-8 Performance indicators (KPIs)

| KPI | Definition |
|---|---|
| Average completion time | Ticks from order creation to delivery, averaged over the latest 100 deliveries |
| Throughput | Orders delivered in the last simulated hour |
| Late percentage | Share of delivered orders that missed their deadline |
| Utilisation | Share of robots that are busy (on an order or charging) |
| Fleet battery | Average battery level of all robots |
| Queue length | Number of orders waiting (PENDING) |

WM-8.1 Targets: late orders below 5 % on ordinary days; no order waiting longer than its deadline
without an operator being alerted.
