# Phase 4 · Optimisation

Phase 3 made the warehouse **predict** (delivery time, late risk, demand, faults). Phase 4 makes it
**decide better**: smarter routes, smarter choice of robot, and a fleet that is positioned and charged
ahead of the demand. Every improvement is **measured**, not assumed, with controlled experiments in the
simulator.

## 1. What is optimised

| Decision | Baseline (E2, before Phase 4) | Phase 4 options |
|---|---|---|
| Robot for an order | nearest free robot, straight-line distance | `eta`: the robot the ETA model predicts will **finish first** · `global`: the best **combination** for all waiting orders (Hungarian algorithm) · `random`: lower bound |
| Route | BFS: fewest cells, traffic ignored | Dijkstra / **A\*** with **live traffic costs** |
| Re-planning | when blocked, or when a cell closes | also every 20 ticks with the current traffic |
| Idle positioning | balanced parking (distance + fullness) | **demand-aware**: bonus for parking areas next to the zone the demand model expects to be busiest |
| Charging | top up below 70 % when no order waits | **predictive**: 85 % in forecast-quiet hours, 50 % in forecast-busy hours, else 70 % |
| Collision safety | one robot per cell; wait, re-plan, side-step | unchanged: every strategy keeps the same safety rules |

## 2. How each part works

**A\* with traffic costs** (`ai/optimization/astar.py`, `dijkstra.py`, `traffic.py`). Each step costs
1 metre plus: 4 if a robot stands on the cell now, 2 per robot already inside the same one-robot-wide
aisle, and 1 × the congestion of the cell's zone. Dijkstra always expands the cheapest partial route;
A\* adds the Manhattan distance to the goal as a guide (it never overestimates, so the route is still
the cheapest) and explores far fewer cells.

**Route-distance cache** (`simulation/navigation/distance.py`). To compare candidate robots, one search
runs *backwards* from the order's first rack over the reversed one-way graph, giving the legal route
length from every cell. Fields are cached and invalidated when an aisle or hazard closes or opens.

**ETA-based assignment** (`ai/optimization/assignment.py`, `eta_estimator.py`). For each waiting order
(HIGH first, then oldest), the 8 robots with the shortest routes to the first rack are scored by the
Phase 3 ETA model — with the exact features the model was trained on (`ai/classical_ml/features.py`):
route distance, battery, motor temperature, current speed, zone congestion, queue, closures, order
size, priority, time. The robot with the lowest predicted delivery time is chosen.

**Global assignment** (Hungarian algorithm). All waiting orders of one priority (up to 20) and all free
robots form a cost matrix of predicted delivery times; `scipy.optimize.linear_sum_assignment` finds the
pairing with the lowest total time. HIGH orders are matched first.

**Demand-aware positioning and predictive charging** (`ai/optimization/positioning.py`). They read
the Phase 3 demand forecasts produced live by `ai/classical_ml/live_predictor.py`.

**Optimizer** (`ai/optimization/optimizer.py`) switches an engine between strategies. Baseline values
change nothing (tested against the golden-master fingerprint).

## 3. Experimental design

| ID | Experiment | Strategies |
|---|---|---|
| E1 | Random assignment | random robot, BFS |
| E2 | **Baseline** (today) | nearest robot, BFS |
| E3 | A\* traffic-aware routing | nearest robot, A\* + traffic |
| E4 | AI prediction + assignment | ETA-based robot, A\* + traffic |
| E4b | Global assignment | Hungarian on predicted times, A\* + traffic |
| E5 | All ideas | E4 + replanning + demand-aware positioning + predictive charging |
| E3c | Diagnostic | A\* with traffic costs at 25 % strength |
| E4c | Diagnostic | ETA-based robot choice, BFS routes |
| E4d | Diagnostic → **winner** | Hungarian on predicted times, BFS routes |
| E5b | Combination | E4d + demand-aware positioning + predictive charging |

- **Fair comparison (common random numbers):** `independent_streams: true` gives orders, faults and
  hazards their own random generators, so every experiment faces exactly the same day.
- **5 seeds × 24 simulated hours** per experiment, large layout, 40 robots, same load.
- **Paired analysis:** every experiment is compared with E2 on the same seed; we report the mean change
  and on how many seeds it improved.
- **KPIs:** average and 90th-percentile completion time, late %, throughput, wait for a robot, distance
  per order, standoffs, utilisation (`evaluation/simulation/metrics.py`).

## 4. Running it

```bash
python scripts/run_experiments.py                    # all Phase 4 experiments (~30-40 min, 3 cores)
python scripts/run_experiments.py --experiments E2 E4 --seeds 2 --hours 6   # quick check
```

Outputs in `evaluation/reports/phase4/`: `runs.csv`, `summary.csv`, `vs_baseline.csv`, `report.md`,
`figures/*.png`, `manifest.json`. `notebooks/06_optimization_experiments.ipynb` explains the results;
the app shows them under **Analytics**, and the **Strategy** selector in the header switches the live
warehouse between E1–E5.

## 5. Results

**All results** (mean of 5 simulated days, ticks unless noted, lower is better):

| ID | Strategy | Avg completion | 90th pct | Late % | Wait for robot | Distance/order (m) | Standoffs |
|---|---|---|---|---|---|---|---|
| E1 | Random robot | 464 | 1567 | 23.1 | 272 | 168.7 | 250 |
| E2 | **Baseline**: nearest robot, BFS | 418 | 1390 | 20.6 | 236 | 160.7 | 246 |
| E3 | + A\* traffic-aware | 564 | 2064 | 26.1 | 368 | 168.4 | 208 |
| E3c | + A\* gentle traffic (diag.) | 531 | 1867 | 25.0 | 338 | 164.8 | 220 |
| E4 | + A\* + ETA robot choice | 566 | 2094 | 25.6 | 371 | 168.3 | 209 |
| E4b | + A\* + Hungarian | 502 | 1599 | 23.7 | 310 | 165.1 | 213 |
| E4c | ETA robot choice, BFS (diag.) | 400 | 1307 | 19.7 | 219 | 160.2 | 246 |
| E4d | **Hungarian on predicted times, BFS** | 328 | 793 | 12.4 | 152 | 157.9 | 236 |
| E5 | Everything incl. A\* | 513 | 1830 | 24.4 | 323 | 164.2 | 221 |
| E5b | E4d + demand parking + forecast charging | 349 | 862 | 13.1 | 171 | 158.4 | 256 |

**1. The winner: E4d — assign all waiting orders together (Hungarian algorithm) using the ETA model's
predicted delivery times, with the normal shortest routes.** Compared with today's rules on the same
five days:

- average delivery time **-21.4 % (5/5 days)**
- slowest 10 % of orders **-42.9 % (5/5 days)**
- late orders **-40.1 % (5/5 days)**
- time an order waits for a robot **-35.6 % (5/5 days)**

It wins on **every** simulated day. Throughput is unchanged (the fleet delivers the same orders per
hour; capacity is set by the robots) — the gain is that each order is matched with the robot that will
really finish it soonest, and urgent orders are matched first, so the queue clears faster.

**2. Traffic-aware A\* made things worse** (E3 +35.0 % (0/5 days), even the gentle
version E3c +27.1 % (0/5 days)). It reduced standoffs, but made every trip about 5 %
longer. At peak hours the warehouse is **overloaded** — more than half of an order's time is spent
waiting for a free robot — so robot time is the scarcest resource, and extra metres grow the queue.
Because E4, E4b and E5 also used A\*, it hid the value of the AI assignment until the diagnostic runs
(E4c, E4d) tested assignment with normal routes.

**3. Choosing one robot at a time by predicted finish time** (E4c) helps a little
(-4.3 % (4/5 days)); planning **all waiting orders together** (E4d) helps far more,
because a greedy one-by-one choice can leave later orders with a distant robot.

**4. Demand-aware parking and forecast-driven charging add nothing on top** (E5b
-16.5 % (5/5 days) vs E4d -21.4 % (5/5 days)): when robots are
almost never idle at peaks, where they wait matters little.

**Recommendation:** use **E4d** as the optimised strategy (select it in the app's **Strategy** menu).
Keep E2 as the reference.

**Honest limits:** 5 simulated days per experiment (consistent wins across all 5 days make the main
result reliable, but small differences such as E4c's are within day-to-day variation); one layout and
fleet size; the ETA model was trained on baseline behaviour. The run times in `runs.csv` for a few runs
include a period when the computer was asleep and are not meaningful.

Full tables: `evaluation/reports/phase4/report.md`; explained in `notebooks/06_optimization_experiments.ipynb`.

## 6. Tests

`tests/unit/test_optimization.py`: planners as short as BFS, one-way aisles and closures respected,
distance fields equal to planned routes, traffic-aware routes avoid occupied cells, the baseline
Optimizer leaves behaviour unchanged, every strategy sees identical orders, and every strategy
delivers orders without two robots sharing a cell.
