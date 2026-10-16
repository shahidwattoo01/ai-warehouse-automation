---
doc_id: safety_rules
title: Warehouse Safety Rules
version: 3.0
effective: 2026-09-07
owner: Health & Safety
---

# Warehouse Safety Rules

## SAF-1 General principles

SAF-1.1 People always have priority over robots. Robots treat every person as an obstacle and
stop or plan around them.

SAF-1.2 Only trained associates may walk on the robot floor. High-visibility vests and safety shoes
are mandatory beyond the control-center door.

SAF-1.3 Any person may ask the control center to pause a robot at any time. A pause takes effect
at the next tick.

## SAF-2 Walking on the robot floor

SAF-2.1 Use the highways and cross aisles to walk through the building. Avoid narrow picking aisles
unless your task requires it: they are one robot wide.

SAF-2.2 Never step in front of a moving robot. Robots give way to people, but leave at least one
cell (1 m) of space.

SAF-2.3 Do not walk through parking bays, charging bays or packing drop bays while robots are
using them.

SAF-2.4 Walk at a normal pace (about 1 m/s). Do not run on the robot floor.

## SAF-3 Restricted zones

SAF-3.1 A restricted zone is an area that robots must not enter and people may enter only for the
work that created it.

SAF-3.2 Closed aisles. An aisle closed for maintenance, a spill or a rack inspection is a
restricted zone for its whole length until it reopens. Barriers stand at both ends. Robots never
plan through it. Only the people doing the maintenance, cleanup or inspection may enter.

SAF-3.3 Floor hazards. A dropped parcel or a fallen pallet on a highway is a restricted cell until
it is removed. Robots plan around it. Only the associate sent to clear it may approach it.

SAF-3.4 Charging areas. The charging bays at the west and east walls (CHG_1 to CHG_4) are
restricted to robots and maintenance staff. Do not touch charging contacts.

SAF-3.5 Columns. The structural columns on the main highway at (38, 12), (41, 12), (38, 34) and
(41, 34) are permanent obstacles; do not store anything against them.

SAF-3.6 An operator may close an aisle on request ("avoid Aisle 7"). Closing an aisle is only
allowed when no robot or person is inside it and no robot is about to pick from it; otherwise
pause the robots concerned first (SOP-05).

## SAF-4 Emergency stop

SAF-4.1 To stop a single robot, send pause_robot from the control center. The robot stops in its
current cell and stays PAUSED until resumed.

SAF-4.2 To stop the whole fleet, pause the simulation (all robots stop at once). Use this when a
person is injured, when there is a fire alarm, or when several robots behave abnormally at the
same time.

SAF-4.3 Never resume a paused robot until the person who requested the pause confirms the area is
clear.

## SAF-5 Robots in trouble

SAF-5.1 A robot in FAULT status stops where it is. Do not push it by hand; follow SOP-03.

SAF-5.2 An overheating robot (motor above 60 C) must not be touched on the drive unit until it has
cooled below 55 C. Follow SOP-04.

SAF-5.3 A robot with a battery below 10 % (critical) must not be left in an aisle: pause it and
arrange recovery (SOP-02).

## SAF-6 Reporting

SAF-6.1 Report every near miss, dropped load and spill to the control center immediately. The
control center logs it, closes the area if needed, and sends an associate.

SAF-6.2 The AI operations copilot may suggest actions, but every action that changes robot or
order state is applied only through validated commands; safety-relevant actions need operator
approval.
