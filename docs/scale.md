# Scale: layouts and fleet sizes

Backlog PR-06. `python scripts/scale_benchmark.py` runs both layouts at several fleet sizes,
which `fleet_size` sets per run. Results: `reports/scale_benchmark.md` / `.json`.

## Method

* **Warm-up:** each run has one simulated hour of warm-up, which is not counted.
* **Measured window:** then 3,000 ticks (5 simulated hours) of steady demand, with no daily curve,
  so night hours don't dilute the load.
* **Two demand series:**
  * Fixed: the normal 0.14 orders per tick, which is 84 per simulated hour.
  * Scaled: the same number of orders per robot as the layout's normal fleet (12 small, 40
    large).
* **Measures:**
  * Throughput: orders completed in the measured window.
  * Utilisation: the share of robots busy, averaged over every tick.
  * Late %.
  * Orders still waiting at the end.
  * The compute cost of one tick.

## Results

| Layout | Robots | Demand | Orders/h | Late % | Utilisation % | Waiting at end | ms per tick |
|---|---|---|---|---|---|---|---|
| small (40×28 m) | 6 | fixed | 36 | 63.3 | 99 | 149 | 1.2 |
| small | 12 | fixed | 64 | 8.4 | 99 | 150 | 2.2 |
| small | 18 | fixed | 80 | 1.5 | 83 | 0 | 2.3 |
| small | 24 | fixed | 86 | 0.7 | 66 | 0 | 2.5 |
| small | 24 | scaled (168/h) | 124 | 14.9 | 99 | 145 | 4.2 |
| large (80×50 m) | 20 | fixed | 66 | 13.1 | 99 | 128 | 5.1 |
| large | 40 | fixed | 81 | 1.7 | 54 | 0 | 5.7 |
| large | 60 | fixed | 80 | 1.2 | 32 | 0 | 5.8 |
| large | 88 | fixed | 81 | 0.7 | 22 | 0 | 7.5 |
| large | 60 | scaled (126/h) | 129 | 2.2 | 61 | 0 | 11.6 |
| large | 88 | scaled (185/h) | **182** | **2.9** | 64 | 0 | **15.8** |

What it shows:

* **Fleet size for a given demand.** On the large layout, 40 robots keep up with 84 orders an
  hour (1.7 % late). Going to 60 or 88 robots barely lowers lateness and leaves most robots idle
  (22 % busy). The small layout needs about 18 robots for the same demand.
* **Scaling.** On the large layout, throughput grows almost in proportion to the fleet up to 88
  robots: 182 of 185 orders an hour, with 64 % busy. Congestion is not the limit yet.
* **The small layout's ceiling** is about 120 orders an hour. Above that, robots are 99 % busy,
  the backlog fills and 15 % of orders are late. Six packing stations and narrow aisles are the
  bottleneck, not the robot count.
* **Compute.** 88 robots cost 15.8 ms per tick, so the simulator still runs at about 30× real
  time. The live loop needs 500 ms per tick at 1×.

## Limits

* **88 robots on the large layout.** It has 88 parking places, and every robot needs one to
  wait and charge from. Asking for more is refused with a clear message.
  * A bug found here: start positions were shared out evenly per parking area, so the small
    areas ran out first and only 86 of 88 places were used. The spare places are now filled too.
    Fleets that already fit are placed exactly as before (the simulator fingerprint is
    unchanged).
* **100+ robots** need a bigger building (a third layout with more racking and parking). That is
  left for when the fleet work of phase 9 changes how robots share the floor (PR-04, time-based
  traffic control).
* **One process.** The live platform runs one simulation per backend (docs/recovery.md); the load
  limits are in docs/load_testing.md.

## Tests

`tests/unit/test_scale.py`:

* 88 robots fill every parking place exactly once.
* 100 robots are refused.
* The layout's own fleet is unchanged.
