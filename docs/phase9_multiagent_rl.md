# Phase 9 — Multi-Agent RL

**Status:** done  
**Backlog items:** PR-03 (batch picking), PR-04 (space-time traffic), PR-05 (robot physics), PR-10 (slotting)  
**Experiment configs:** E9a, E9b, E9c, E9d  

---

## What was built

### PR-03 — Batch picking (`simulation/orders/dispatcher.py`, `simulation/robots/controller.py`)

The dispatcher now clusters waiting orders by proximity and assigns up to `tote_capacity=3` orders per robot trip.  Orders within `cluster_radius=8 m` of a seed order and of the same priority are batched.  Stops are sorted by nearest-neighbour to minimise total travel.  A `stop_order_map` parallel array in `Task` tracks which pick belongs to which order so delivery credit is correctly applied.

Config key: `batch_picking: {enabled, tote_capacity, cluster_radius}`.

### PR-04 — Space-time traffic control (`simulation/navigation/space_time.py`)

A `SpaceTimeTable` holds `(cell, tick)` reservations.  `SpaceTimePlanner` runs A* in space-time, refusing moves into already-reserved slots.  Deadlock detection uses a waiting-for graph: if a cycle is found, the lowest-priority robot in the cycle backs off one cell.  The engine sweeps old reservations and checks for deadlocks every `deadlock_check_every` ticks.

Config key: `space_time: {enabled, horizon_ticks, deadlock_check_every}`.

### PR-05 — Robot physics (`simulation/robots/physics.py`)

Based on the MiR 100 datasheet (1.5 m/s max speed, 0.5 m/s² acceleration, 0.5 m/s turn speed) at the simulator's 600-tick/hour rate:

- `accel_ticks = 1` — one tick to reach cruising speed from rest
- `turn_ticks = 1` — one tick per direction change

`pace_ticks(path)` returns a list of per-cell tick costs so each move drains the right amount of simulated time. Physics ETA replaces the flat cell-count estimate in the robot controller.

Config key: `physics: {enabled, max_speed_ms, accel_ms2, turn_speed_ms, cell_m}`.

### PR-10 — Slotting optimisation (`simulation/warehouse/slotting.py`)

`SlottingOptimiser` maintains a rolling pick-velocity window (default 7 days).  Every `reoptimise_every_hours` simulated hours it ranks SKUs by velocity and rack faces by distance to the nearest packing station, then swaps fast movers toward the front.  The engine subscribes to `ITEM_PICKED` events to record each pick.

Config key: `slotting: {enabled, reoptimise_every_hours, velocity_window_hours}`.

### MARL navigator (`ai/reinforcement_learning/`)

- **`env.py`** — `WarehouseEnv` wraps the engine as a Gymnasium environment. 58-dim observation per robot (7×7 local occupancy grid, route direction, battery, load, urgency). 5 discrete actions (stay, N, S, E, W). Single-agent and multi-agent interfaces.
- **`dqn_agent.py`** — `DQNNavigator`: 58→128→64→5 MLP, ε-greedy exploration, 50 k replay buffer, SmoothL1 loss, soft target update.
- **`marl.py`** — `SharedPolicyMARL`: all robots share one `DQNNavigator`. Each tick every robot contributes a transition to the shared replay buffer.

---

## Experiment configs

| ID  | Description |
|-----|-------------|
| E9a | Batch picking + space-time traffic, physics on |
| E9b | E9a + explicit physics config (turn\_speed\_ms 0.4) |
| E9c | E9b + slotting optimisation |
| E9d | E9c + MARL navigator (planner: marl, weights from training) |

All configs: 5 seeds (101–105), 24 h, `independent_streams: true`, large layout.  Comparison baseline: E4d.

---

## Frontend additions

- **`/rl`** — RL Training panel: reward curve, per-checkpoint table (episode, mean reward, deliveries, epsilon), Train button (triggers async training run), live status polling.
- **`/slotting`** — Slotting heatmap: rack-cell grid coloured by pick velocity (blue = slow, red = fast), stat tiles (enabled, products tracked, total swaps), Re-slot Now button.

---

## Backend API routes

- `GET /rl/status` — MARL config and training history
- `POST /rl/train` — trigger async training run
- `GET /rl/history` — per-checkpoint training history
- `GET /slotting/heatmap` — per-cell pick velocity matrix
- `POST /slotting/reslot` — trigger manual re-slot
