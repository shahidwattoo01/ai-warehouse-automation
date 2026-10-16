---
doc_id: maintenance_guides
title: Fleet Maintenance Guide
version: 3.0
effective: 2026-09-07
owner: Fleet Engineering
---

# Fleet Maintenance Guide

## MG-1 How faults are detected

MG-1.1 Every robot reports its telemetry each tick. The monitoring system looks at short windows
of about 20 ticks per robot and compares them with normal behaviour.

MG-1.2 Signals used for diagnosis:

| Signal | Normal | Suspicious |
|---|---|---|
| Movement rate while it has a route | close to 1 cell per tick | about 0.5 or less |
| Stops while it has a route | rare, short (traffic) | many stops, or long stop with status FAULT |
| Battery change per tick | about -0.05 % while driving | a single drop of 12 % or more |
| Motor temperature | 24-45 C | above 60 C, or rising quickly |
| Route length | shrinking as it drives | growing (wandering off route) |
| Time on current task | about 100-250 ticks | far longer than similar orders |

MG-1.3 Traffic also causes stops and slow progress. Before calling a fault, check whether the robot
is blocked by other robots, a worker, a closed aisle or a floor hazard (blocked-tick counter,
zone congestion).

## MG-2 Battery spike

MG-2.1 Symptom: the battery level drops by 12-30 % in one step, without matching driving.

MG-2.2 Action: if the battery is now below 20 %, the robot goes to charge automatically. Note the
robot ID. Two spikes on the same robot within a shift: take it out of service and inspect the
battery pack and connectors.

## MG-3 Speed degradation

MG-3.1 Symptom: the robot moves at about half speed although its route is free.

MG-3.2 Action: check the motor temperature first. If it is above 60 C, this is thermal throttling:
see MG-6. Otherwise suspect a drive-wheel or encoder problem. If it lasts longer than 120 ticks
or repeats, finish the current order, then pause the robot and send it for inspection.

## MG-4 Stop event

MG-4.1 Symptom: status FAULT, no movement. Stops normally clear within 15-60 ticks.

MG-4.2 Action: follow SOP-03. Do not push the robot. If the stop has not cleared after 60 ticks,
reassign its order and send a technician.

## MG-5 Route deviation

MG-5.1 Symptom: the robot leaves its planned route, wanders to a nearby cell, then resumes. Its
route length grows instead of shrinking.

MG-5.2 Action: usually clears in 20-50 ticks. Repeated deviations point to a localisation
problem: recalibrate the robot's floor-marker camera at the next charging stop.

## MG-6 Overheating

MG-6.1 Symptom: motor temperature far above the normal 24-45 C; above 60 C the robot throttles to
half speed.

MG-6.2 Action: follow SOP-04. The fault is cleared only when the motor is below 55 C. Inspect the
cooling fan and air filter of any robot that overheats twice in one shift.

## MG-7 Preventive maintenance

MG-7.1 Daily: check fault counts per robot from the event log; any robot with five or more faults
in a day is inspected before the next shift.

MG-7.2 Weekly: clean drive wheels, check battery connectors, check cooling fans.

MG-7.3 Monthly: calibrate cameras and floor-marker readers; check charger contacts at CHG_1 to
CHG_4.

MG-7.4 Record every inspection and repair with the robot ID, date, fault type and the work done.
