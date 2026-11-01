# Simulator against real warehouses

Backlog PR-20. Every result in this project (the models, the optimisation experiments, the
dashboards) comes from the simulator. This page compares the simulator's settings and outputs
with published figures from real AMR warehouses. It records where they match, where they don't,
and how much the gaps matter.

## First: two clocks

The simulator runs two clocks:

* **Motion and handling run in real time.** One tick is 0.5 s (`sim_tick_hz: 2`, 1 m cells), so
  a robot drives 2 m/s and a pick takes 4 ticks = 2 s.
* **The calendar runs 12× faster.** 600 ticks make one "hour" of demand, KPIs and model features
  (`ticks_per_hour: 600`), which is 5 real minutes.

This keeps a day of warehouse life short enough to simulate and record. It also means
per-hour figures on the dashboard are per calendar hour. A robot's work per real hour is 12×
the per-calendar-hour figure.

## Comparison

| Quantity | Simulator | Real warehouses (published) | Verdict |
|---|---|---|---|
| Robot speed | 2.0 m/s, constant | 1.1–2 m/s: Locus 1.1, Zimmer 1.5, Addverb Dynamo up to 2 [1] | Top of the range; no acceleration or turning time (PR-05) |
| Pick at the rack | 2 s per item | Goods-to-person and AMR-assisted: about 300–600 lines/h per station, i.e. 6–12 s per line; Geek+ 400–500 picks/h; manual 60–120 lines/h [2] | **3–6× too fast**: like a robot arm, not a person |
| Hand-over at packing | 1.5 s per tote | Seconds per tote at a bench; packing itself is the associates' work (modelled separately in the WMS) | Plausible for the hand-over |
| Battery runtime | about 2,000 moves ≈ 17 min of driving (≈ 3 calendar hours) | 8–10 h per charge: inVia about 10 h, ForwardX about 8 h, Zimmer 8 h [1] | **About 30× too short** in real time |
| Recharge | about 100 s from empty | 2–2.5 h to 95–100 % (ForwardX, Zimmer); fast chargers about 10 min for 2.7 h (MiR, 1:16) [1] | Too fast, but the runtime-to-charge ratio (about 10:1) is inside the published 1:6–1:16 |
| On-time orders | 98–99 % (1–2 % late) | DC median on-time shipments 98.2 % [3] | Matches |
| Lines received and put away per person-hour | Inbound associates: 15 ticks per receipt + walking | Median 22, best-in-class ≥ 60 lines/h [3] | Same order of magnitude |
| Order cycle time | About 140 ticks ≈ 70 s from order to packing station | Internal order cycle time median 8 h, best-in-class < 2 h [3] | Not comparable: ours covers pick to pack only, theirs includes waves, packing and shipping |

Sources:

1. AMR specifications: [inVia Picker](https://inviarobotics.com/our-system/invia-picker-robots/),
   [ForwardX Flex white paper](https://www.forwardx.com/wp-content/uploads/docs/whitepapers/Whitepaper%20Meet%20ForwardX%20Flex.pdf),
   [Zimmer Miles 3500](https://www.zimmer-group.com/en-us/products/system-solutions/mobile-robotics-and-transport-systems/autonomous-mobile-robot-miles/base-vehicle-with-stroke/products/miles-3500-mit-hub),
   [MiR250 specifications](https://mobile-industrial-robots.com/it/prodotti/robot/mir250/specifiche),
   [Addverb Dynamo 100](https://addverb.com/?p=3365),
   [Locus (Material Handling 247)](https://www.materialhandling247.com/product/locusbot_autonomous_robotic_system/robotics),
   [arXiv 2406.08333 (AMR review)](https://arxiv.org/pdf/2406.08333).
2. Picking rates: [Savoye pick stations](https://www.savoye.com/en/ressource/goods-to-person-pick-stations-3/),
   [Hoj (Geek+ figures)](https://hoj.net/pages/goods-to-person-robotics),
   [Mecalux pick station](https://mecalux.com/warehouse-automation/pick-station),
   [TGW robotic picker (SC247)](https://www.supplychain247.com/article/new_robotic_picker_integrates_with_tgws_goods_to_person_workstations).
   These are mostly vendor claims; Locus Robotics itself warns that such figures
   [cannot be independently checked](https://www.warehouseautomation.ca/news/dhl-receives-first-locus-array-robot).
3. WERC DC Measures medians (2018 report, quoted by
   [Honeywell](https://www.honeywell.com/us/en/news/featured-stories/2020/02/which-metrics-matter-most-to-dc-operations));
   the current [2026 report](https://www.mmh.com/article/wercs_2026_dc_measures_report_delivers_benchmarks)
   is sold by WERC.

## How much do the gaps matter? The realistic timing profile

`configs/profiles/realistic_timing.yaml` sets the handling and battery times to the published
ranges:

* 8 s per pick (`pick_ticks: 16`);
* 5 s hand-over (`drop_ticks: 10`);
* batteries lasting hours and recharging in about 45 min.

It is **not** the default, because the trained models and the optimisation experiments used the
default timing. The same large layout, demand and seed, with and without it
(`python scripts/scale_benchmark.py --runs large:40,large:88 --profile realistic_timing`):

| Robots | Timing | Orders/h | Late % | Utilisation % |
|---|---|---|---|---|
| 40 | default | 81 | 1.7 | 54 |
| 40 | realistic | 81 | **7.7** | **76** |
| 88 | default | 81 | 0.7 | 22 |
| 88 | realistic | 82 | 2.5 | 33 |

With real pick times, the same 40 robots are close to their limit: lateness more than quadruples.
About twice the fleet is needed for the default's service level. So the default timing **flatters
fleet size**. Experiment results about how many robots a site needs should be read with that in
mind, or re-run with the profile.

## What this means for the project

* **Kept:**
  * on-time rates, robot speed and the order of magnitude of associate work are realistic;
  * lateness and congestion behave like a real site under load.
* **Known optimism:** fast picks and short batteries. The profile measures the effect. Retraining
  the models on profile data is the step towards using them on a real site; the MLOps retraining
  (docs/mlops.md) would also adapt them from live outcomes.
* **Not modelled yet:**
  * acceleration and turning (PR-05);
  * pick errors, damaged items and human fatigue (partly in PR-31).
* **Real data:** a site's own WMS and robot logs, through the ERP and VDA 5050 connections, are
  the real calibration source. The published figures above are the stand-in until then.

## Tests

`tests/unit/test_scale.py`: the profile is applied on top of the configuration (the rest
unchanged), and the batteries last hours, not minutes.
