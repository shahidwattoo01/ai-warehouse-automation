# Scale benchmark 2026-11-01

3000 measured ticks per run (5 simulated hours) after one hour of warm-up, seed 5, simple inventory, steady demand (no daily curve). Fixed: 0.14 orders per tick (84 per simulated hour). Scaled: in proportion to the fleet. Utilisation is averaged over every tick.

| Layout | Robots | Demand | Orders/h | Avg completion (ticks) | Late % | Utilisation % | Waiting at end | Collisions | ms/tick | Max real-time speed |
|---|---|---|---|---|---|---|---|---|---|---|
| large | 40 | fixed | 80.8 | 199.8 | 7.7 | 76.3 | 0 | 0 | 8.37 | 59.8x |
| large | 88 | fixed | 81.6 | 157.8 | 2.5 | 33.4 | 0 | 0 | 7.32 | 68.3x |
