# Layouts

ASCII maps, one character per cell (1 cell = 1 meter by default).

| Char | Meaning |
| --- | --- |
| `#` | Wall |
| `.` | Floor / aisle |
| `S` | Rack bay (robots pick from the adjacent aisle cell) |
| `C` | Charger |
| `P` | Packing / pick station service cell |
| `K` | Parking cell |
| `D` | Dock door |

Layout version 2 (racks with levels, conveyors, diverters, worker paths, cameras) is described in
`standard_30x20.v2.yaml` once Phase 2 of the simulator is built.
