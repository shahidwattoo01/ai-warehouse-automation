---
doc_id: robot_manual
title: AMR-500 Robot Manual
version: 3.0
effective: 2026-09-07
owner: Fleet Engineering
---

# AMR-500 Robot Manual

## RM-1 The fleet

RM-1.1 The warehouse runs 40 AMR-500 autonomous mobile robots, named R1 to R40. Each robot drives
on the warehouse grid, picks order lines at rack faces and carries them to a packing station.

RM-1.2 Every robot reports, on every tick: its position (x, y), heading, status, battery level,
drive-motor temperature, load (order lines carried), current task and planned route.

RM-1.3 Robots start each shift spread over the eight parking areas (see WM-2.7).

## RM-2 Motion

RM-2.1 Maximum speed is 2 m/s: one grid cell per tick at normal simulation speed (2 ticks per
second).

RM-2.2 Robots move in four directions (north, south, east, west) and turn on the spot. They obey
one-way aisle directions and never enter racks, walls, columns, closed aisles or floor hazards.

RM-2.3 Robots plan the shortest legal route with a breadth-first search over the grid. Ties
between equally short routes are broken at random so robots spread over parallel aisles.

RM-2.4 Speed is reduced to half (one cell every second tick) when the robot has a speed
degradation fault or when its motor is above the throttle temperature of 60 C.

## RM-3 Status values

| Status | Meaning |
|---|---|
| IDLE | No task; parked or waiting in a parking bay |
| MOVING | Driving to a rack, a charger or a parking bay |
| PICKING | Stopped at a rack face, picking an order line |
| DELIVERING | Carrying picked items to a packing station, or unloading there |
| CHARGING | Docked at a charging bay |
| PAUSED | Stopped by an operator command; resumes only on a resume command |
| FAULT | Stopped by a fault (stop event); recovers when the fault clears |

## RM-4 Battery and charging

RM-4.1 Battery use: 0.05 % per metre driven and 0.01 % per order line picked. A full battery
covers about 2 km of driving.

RM-4.2 Thresholds:

| Level | Threshold | What happens |
|---|---|---|
| Low | below 20 % | The robot receives no new orders and drives to the nearest free charging bay |
| Critical | below 10 % | Operator action required (SOP-02) |
| Top-up | below 70 % | When no orders are waiting, idle robots below 70 % top up at a free charger |
| Charged | 95 % | Charging stops and the robot returns to parking |

RM-4.3 Charging adds 2 % per tick, so a robot charges from 20 % to 95 % in about 38 ticks
(about 19 seconds at normal speed).

RM-4.4 Each charger has three bays. If every bay is taken, a robot that only wants a top-up stays
parked and tries again later; a low-battery robot keeps waiting for the nearest free bay.

RM-4.5 Opportunity charging (top-ups during quiet periods) keeps the robots in the parking rows
charged and ready for the next rush.

## RM-5 Drive-motor temperature

RM-5.1 The motor temperature is measured continuously. Ambient temperature is 24 C.

RM-5.2 Normal operating values:

| Activity | Typical temperature |
|---|---|
| Parked | about 24 C |
| Charging | about 32 C |
| Driving empty | about 39 C |
| Driving loaded | about 44 C |

RM-5.3 Above 60 C the robot throttles itself to half speed to protect the motor (thermal
throttling). A robot running above 60 C is overheating: follow SOP-04.

RM-5.4 The temperature reading has a sensor noise of about 0.3 C. Judge trends over several
readings rather than a single value.

## RM-6 Faults

RM-6.1 Five fault types are monitored. Each is logged as a ROBOT_FAULT event and cleared with a
FAULT_CLEARED event.

| Fault | What the robot does | Typical duration | Main signals |
|---|---|---|---|
| battery_spike | Battery level drops suddenly by 12-30 % | short (about 10 ticks) | large negative battery step |
| speed_degradation | Drives at half speed | 40-120 ticks | low movement rate while it has a route |
| stop_event | Stops completely (status FAULT) | 15-60 ticks | no movement, status FAULT |
| route_deviation | Leaves its route and wanders to a nearby cell before resuming | 20-50 ticks | route length grows, detour |
| overheating | Motor heats far above normal, then throttles | 60-160 ticks of heating, plus cool-down | temperature above 60 C, rising |

RM-6.2 An overheating fault stays active until the motor has cooled below 55 C.

RM-6.3 Diagnosis and repair steps are in the Maintenance Guide. Operator procedures are in SOP-03
(stopped robot) and SOP-04 (overheating).

## RM-7 Commands

RM-7.1 Operators and approved AI tools can send these commands; every command is validated and
applied at the start of the next tick:

| Command | Effect |
|---|---|
| pause_robot(robot_id) | Robot stops where it is (status PAUSED) |
| resume_robot(robot_id) | A paused robot continues its task |
| assign_order(robot_id, order_id) | Gives a waiting order to a free robot (rejected with a reason if not allowed) |
| reroute_robot(robot_id, ...) | Plans a new route for the robot |

RM-7.2 An assignment is rejected when the robot is paused, faulty, busy with another order or
charging, when its battery is below 20 %, when the order is no longer waiting, or when the order
needs a rack in a closed aisle. The rejection reason is logged as a COMMAND_REJECTED event.

RM-7.3 AI tools never change robot data directly: they submit the same validated commands as an
operator.
