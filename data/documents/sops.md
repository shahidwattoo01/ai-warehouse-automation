---
doc_id: sops
title: Standard Operating Procedures
version: 4.0
effective: 2026-10-30
owner: Operations
---

# Standard Operating Procedures (SOPs)

Each SOP lists the trigger, the steps in order, and how to confirm the situation is resolved.
"Control center" means the operator on duty; actions may be proposed by the AI copilot but are
applied only through validated commands.

## SOP-01 Low battery (below 20 %)

Trigger: a BATTERY_LOW event, or a robot's battery below 20 %.

1. No action is needed for a robot that is driving to a charger: below 20 % a robot automatically
   receives no new orders and goes to the nearest free charging bay.
2. If the robot is still carrying an order, it finishes nothing new; check that the order is
   delivered or reassigned.
3. If all 12 charging bays are taken, the robot waits for the nearest bay. If more than three
   robots wait at the same time, pause opportunity top-ups by keeping orders flowing, and report
   charger capacity to the shift lead.
4. Resolved when the robot is CHARGING and later returns to parking at 95 %.

## SOP-02 Critical battery (below 10 %)

Trigger: a robot below 10 % that is not at a charger.

1. Pause the robot (pause_robot) if it is in a picking aisle or on a highway lane where it could
   stop and block traffic.
2. Reassign its order, if it has one, to another free robot.
3. Send an associate with the manual tow cart to bring it to the nearest charger: CHG_1 or CHG_2 on
   the west wall, CHG_3 or CHG_4 on the east wall.
4. Resume the robot once it is docked.
5. Record the robot ID: a robot reaching critical battery may have a battery fault (see MG-2).

## SOP-03 Robot stopped (FAULT status)

Trigger: a ROBOT_FAULT event of type stop_event, or a robot in FAULT status.

1. Check the robot's status and position. Do not send a person into a narrow aisle to push it.
2. Wait up to 60 ticks: most stop events clear by themselves.
3. If the robot carries a HIGH-priority order with less than 120 ticks left before its deadline,
   do not wait: pause the robot and reassign the order now.
4. If the stop has not cleared after 60 ticks: pause the robot, reassign its order, check that other
   robots are routing around it, and call a technician (MG-4).
5. Resolved when FAULT_CLEARED is logged and the robot moves again, or the robot is taken out of
   service.

## SOP-04 Overheating robot

Trigger: motor temperature above 60 C, or an overheating fault.

1. Let the robot finish its current order: above 60 C it throttles to half speed automatically.
2. If its temperature keeps rising above 70 C, pause it at the next safe stop (a parking bay or a
   wide highway lane, never a narrow aisle) and reassign its order.
3. Do not assign new orders to the robot until its temperature is below 55 C.
4. Resume it after cooling; if it overheats twice in one shift, send it for inspection (MG-6).

## SOP-05 Closing an aisle (restricted zone)

Trigger: maintenance, a spill, a rack inspection, or an operator request such as "avoid Aisle 7".

1. Identify the aisle (Aisle 1 to Aisle 52; see WM-4.2 for its row and segment).
2. Check that no robot or person is inside the aisle and no robot is about to pick from it. If one
   is, wait until it has left, or pause it and reassign its order first.
3. Close the aisle. Barriers are placed at both ends; robots immediately plan around it and orders
   that need a rack in it wait in the queue.
4. Expect HIGH-priority orders for that aisle to become late if the closure lasts long; consider
   reopening within 10-40 minutes.
5. Reopen the aisle when the work is finished and the floor is dry and clear. Orders waiting for
   it are then assigned again automatically.

## SOP-06 Dropped parcel or fallen pallet

Trigger: a HAZARD_DETECTED event (a PACKAGE or DEBRIS on a highway cell).

1. The cell is closed to robots at once; robots whose route crossed it are rerouted automatically.
2. Send the nearest associate to remove it. A parcel is returned to its packing station; a pallet
   is removed with a pallet jack.
3. While it lies there, check that robots are not queuing beside it.
4. Resolved when HAZARD_CLEARED is logged. A cleanup normally takes 3-12 minutes.

## SOP-07 Prioritising urgent orders

Trigger: many HIGH-priority orders waiting, or an instruction such as "prioritise all urgent
orders".

1. The dispatcher already serves HIGH-priority orders first. Check why they are still waiting: no
   free robot, low batteries, or racks in a closed aisle.
2. If racks are in a closed aisle, consider reopening it (SOP-05).
3. If no robot is free, use manual assignment to give the most urgent orders to the robots that
   finish soonest, or pause opportunity charging by keeping robots in service.
4. Report expected late orders to the shift lead.

## SOP-08 Manual assignment

Trigger: an operator wants to choose robots by hand (testing, special orders).

1. Switch assignment mode to manual. From now on the dispatcher assigns nothing.
2. Assign each waiting order to a robot with assign_order(robot_id, order_id). Choose a free robot
   with at least 20 % battery, close to the order's first rack.
3. If the command is rejected, read the reason (robot busy, paused, faulty, battery too low, order
   already taken, or order needs a closed aisle) and choose another robot.
4. Switch back to automatic mode when finished; waiting orders are then assigned automatically.

## SOP-09 Blocked or stuck robot

Trigger: a robot that has not moved for a long time although it has a route, repeated
ROBOT_BLOCKED or ROUTE_CHANGED events, or an instruction like "Robot 7 is blocking the main
aisle".

1. Get the robot's status: is it PAUSED, in FAULT, waiting behind a working robot, or blocked by a
   person or a hazard?
2. Look at nearby robots: a standoff between two robots is normally broken automatically within
   4-7 ticks.
3. If it is paused, resume it when safe. If it is faulty, follow SOP-03.
4. If it blocks a busy lane, reroute it or send it to the nearest parking area, and reassign its
   order if needed.
5. Verify that traffic is flowing again (no robot blocked for more than 20 ticks).

## SOP-10 Peak days (promotions)

Trigger: a promotion day (for example Singles Day, Black Friday or Cyber Monday) or orders
arriving faster than the fleet can deliver.

1. Before the peak: make sure all robots are charged above 70 % and no aisle is closed for routine
   work.
2. Postpone routine maintenance closures until after the peak.
3. Watch the queue length and the late percentage every hour.
4. Expect late LOW-priority orders during the busiest hours; HIGH-priority orders are served first.
5. After the peak, run opportunity charging and restart postponed maintenance.

## SOP-11 Emergency stop and restart

Trigger: a person injured or in danger, a fire alarm, several robots behaving abnormally at once,
or anyone asking to stop the fleet.

1. Press the red E-STOP button at the top of any screen (one press, no confirmation). For work in
   one zone only, stop that zone on the Safety page instead.
2. Check the red banner: it shows how many robots are held, the reason and who stopped them.
3. Deal with the cause: send help, clear the person or hazard, call maintenance.
4. When the cause is dealt with, press Release. The robots keep holding (amber banner).
5. Get confirmation that the area is clear from the person who asked for the stop, then press
   Reset. If the reset is refused because a person stands next to a robot, make sure they are
   clear and aware before choosing "area checked, reset anyway" (logged under your name).
6. Confirm robots are moving again and check the safety log for the stop, release and reset.

## SOP-12 Order at risk of missing its truck

Trigger: an order close to its carrier's cut-off that is not packed, a long pack queue, or orders
reported as having missed a truck.

1. Open the order under Orders, Customer orders: check its status, its truck and the minutes to
   cut-off.
2. ON_HOLD: if the hold reason is resolved, release the hold. READY in wave mode: release it now.
3. WAITING_STOCK: if the customer accepts partial shipments, ship what is in stock (the rest goes
   on backorder); otherwise check the urgent replenishment or the purchase order for the item.
4. AT_PACK with a long pack queue: switch packing to manual for that station and pack from the
   Packing tab, or move help to the station.
5. If the truck is missed anyway, the order moves to the carrier's next truck automatically; tell
   the customer service team.
6. Confirm on Shipping and trucks that the order is on board before departure.
