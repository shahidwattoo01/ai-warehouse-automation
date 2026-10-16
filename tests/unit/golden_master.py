"""Behavioural fingerprint of the simulator: a hash over every tick's robots, orders and events.

Refactors that must not change behaviour compare `fingerprint()` before and after.
Run directly to print the current value:  python -m tests.unit.golden_master

History (change only when behaviour changes on purpose):
    a1d34a7d...  large layout, traffic fixes, engine refactor
    0fd20127...  dataset v2: order rate from measured capacity (0.14/tick), queue cap 150
    5d14949d...  8 parking areas around the building, balanced idle positioning
    0b4aa665...  dataset v3: aisle closures and floor hazards, motor temperature, overheating
                 faults (also thermal throttling), dispatcher skips orders in closed aisles
    c3e99469...  live clock 600 ticks per simulated hour, the same as dataset v3 (Phase 3 models)
"""

from __future__ import annotations

import hashlib
import json

from simulation.environment.engine import SimulationEngine


def fingerprint(ticks: int = 3000, seed: int = 42, layout: str = "large") -> str:
    engine = SimulationEngine(
        seed=seed, overrides={"layout": layout, "faults": {"probability_per_hour": 3.0}}
    )
    engine.start()
    h = hashlib.sha256()
    for _ in range(ticks):
        events = engine.tick()
        snapshot = {
            "robots": [
                (
                    r.robot_id,
                    r.position,
                    r.status.value,
                    round(r.battery, 6),
                    r.load,
                    r.current_task,
                )
                for r in engine.robots.values()
            ],
            "orders": sorted(
                (o.order_id, o.status.value, o.assigned_robot) for o in engine.orders.values()
            ),
            "events": [(e.type.value, e.entity_id) for e in events],
        }
        h.update(json.dumps(snapshot, default=str).encode())
    return h.hexdigest()


if __name__ == "__main__":
    print(fingerprint())
