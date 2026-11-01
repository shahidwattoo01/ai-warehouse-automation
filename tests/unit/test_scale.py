"""Fleet size per run (scale runs, docs/scale.md) and the realistic timing profile (PR-20)."""

import pytest
import yaml

from simulation.environment.engine import SimulationEngine
from simulation.warehouse.layout import load_layout


def test_fleet_size_override_and_parking_limit():
    e = SimulationEngine(seed=1, overrides={"layout": "large", "fleet_size": 88})
    assert len(e.robots) == 88  # every parking place used, none twice
    spots = [tuple(r.position) for r in e.robots.values()]
    assert len(set(spots)) == 88
    with pytest.raises(ValueError, match="88 parking places"):
        load_layout("large", robots=100)
    assert len(load_layout("large").spawn) == 40  # the layout's own fleet is unchanged


def test_realistic_timing_profile_slows_handling():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    profile = yaml.safe_load((root / "configs/profiles/realistic_timing.yaml").read_text())
    faults_off = {"faults": {"probability_per_hour": 0.0}}  # a battery fault drops it at once
    e = SimulationEngine(seed=1, overrides={"layout": "default", **profile, **faults_off})
    assert e.config["orders"]["pick_ticks"] == 16 and e.config["orders"]["drop_ticks"] == 10
    assert e.config["orders"]["arrival_prob_per_tick"] == 0.14  # the rest stays as configured
    start = {rid: r.battery for rid, r in e.robots.items()}
    e.start()
    for _ in range(200):
        e.tick()
    used = max(start[rid] - r.battery for rid, r in e.robots.items())
    assert used < 3  # hours-long batteries barely move in 200 ticks (default: up to ~10 %)
