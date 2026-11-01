"""Labour management: standards, personal pace, performance and utilisation per shift."""

from simulation.environment.engine import SimulationEngine
from wms.labour import SHIFT_HOURS


def run(ticks: int, seed: int = 7):
    e = SimulationEngine(seed=seed, overrides={"layout": "default", "inventory_model": "wms"})
    e.start()
    for _ in range(ticks):
        e.tick()
    return e.inventory.wms


def test_performance_follows_each_persons_pace():
    wms = run(SHIFT_HOURS * 600 + 1200)  # a full shift and part of the next
    first = wms.labour.report(0)
    busy = [p for p in first["people"] if p["tasks"] >= 20]
    assert busy, "some associates should have done real work"
    for p in busy:  # earned / worked converges on the personal pace (task variation averages out)
        assert abs(p["performance_percent"] / 100 - p["pace"]) < 0.12, p
        assert 0 < p["utilisation_percent"] <= 100
        assert p["productivity_percent"] <= p["performance_percent"]
    assert first["hours_elapsed"] == SHIFT_HOURS  # a past shift is complete
    now = wms.labour.report()
    assert now["shift"] == 1 and 0 < now["hours_elapsed"] < SHIFT_HOURS
    assert {c["crew"] for c in first["crews"]} == {"inbound", "pack", "dock"}
    assert {"open_tasks", "below_85_percent", "in_progress"} <= set(first["handover"])
    std = {s["task"]: s["standard_minutes"] for s in first["standards"]}
    assert std["RECEIVE"] == 1.5  # 15 ticks of 6 s


def test_same_seed_same_people():
    a, b = run(300), run(300)
    assert a.labour.pace == b.labour.pace
    assert 0.75 <= min(a.labour.pace.values()) and max(a.labour.pace.values()) <= 1.3


def test_labour_survives_a_warehouse_snapshot():
    """The WMS is pickled into the recovery snapshot (PR-17); a lambda here broke it."""
    import pickle

    wms = run(400)
    copy = pickle.loads(pickle.dumps(wms.labour))
    assert copy.pace == wms.labour.pace and copy.report()["people"]
