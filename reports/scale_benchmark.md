# Scale benchmark 2026-11-01

3000 measured ticks per run (5 simulated hours) after one hour of warm-up, seed 5, simple inventory, steady demand (no daily curve). Fixed: 0.14 orders per tick (84 per simulated hour). Scaled: in proportion to the fleet. Utilisation is averaged over every tick.

| Layout | Robots | Demand | Orders/h | Avg completion (ticks) | Late % | Utilisation % | Waiting at end | Collisions | ms/tick | Max real-time speed |
|---|---|---|---|---|---|---|---|---|---|---|
| default | 6 | fixed | 36.0 | 1166.0 | 63.3 | 99.0 | 149 | 0 | 1.25 | 400.6x |
| default | 6 | scaled | 34.0 | 319.1 | 7.1 | 97.7 | 39 | 0 | 1.18 | 425.1x |
| default | 12 | fixed | 64.2 | 266.7 | 8.4 | 99.1 | 150 | 0 | 2.19 | 228.3x |
| default | 18 | fixed | 80.4 | 108.7 | 1.5 | 82.6 | 0 | 0 | 2.3 | 217.8x |
| default | 18 | scaled | 92.4 | 890.7 | 13.9 | 99.1 | 148 | 0 | 2.82 | 177.5x |
| default | 24 | fixed | 86.2 | 93.1 | 0.7 | 65.9 | 0 | 0 | 2.53 | 197.4x |
| default | 24 | scaled | 123.6 | 738.8 | 14.9 | 99.1 | 145 | 0 | 4.16 | 120.3x |
| large | 20 | fixed | 65.8 | 483.2 | 13.1 | 99.4 | 128 | 0 | 5.1 | 98.0x |
| large | 20 | scaled | 47.0 | 142.6 | 2.6 | 61.5 | 0 | 0 | 3.6 | 139.0x |
| large | 40 | fixed | 81.4 | 139.4 | 1.7 | 53.8 | 0 | 0 | 5.74 | 87.1x |
| large | 60 | fixed | 80.2 | 125.9 | 1.2 | 32.0 | 0 | 0 | 5.8 | 86.2x |
| large | 60 | scaled | 129.2 | 161.7 | 2.2 | 60.9 | 0 | 0 | 11.55 | 43.3x |
| large | 88 | fixed | 80.6 | 131.9 | 0.7 | 22.3 | 0 | 0 | 7.54 | 66.3x |
| large | 88 | scaled | 181.8 | 156.0 | 2.9 | 63.7 | 0 | 0 | 15.75 | 31.7x |
