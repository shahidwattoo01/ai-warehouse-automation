"""Fleet safety: the emergency stop freezes every robot, release never restarts motion, reset is
deliberate and refused next to a person; zone stops; slow zones; the safety log."""

import pytest

from simulation.environment.engine import SimulationEngine
from simulation.environment.safety import SafetyError
from tests.unit.golden_master import fingerprint

SMALL = {"layout": "default"}


def engine(**safety) -> SimulationEngine:
    e = SimulationEngine(seed=3, overrides={**SMALL, "safety": safety})
    e.start()
    for _ in range(200):
        e.tick()
    return e


def positions(e):
    return {rid: r.position for rid, r in e.robots.items()}


def run(e, ticks):
    for _ in range(ticks):
        e.tick()


def test_estop_freezes_the_fleet_and_release_does_not_restart_it():
    e = engine()
    s = e.safety
    s.engage("sara", "person in the aisle")
    held = positions(e)
    batteries = {rid: r.battery for rid, r in e.robots.items()}
    run(e, 40)
    assert positions(e) == held  # nobody drives, picks or drops
    assert all(e.robots[rid].battery <= batteries[rid] for rid in e.robots)
    assert all(not e.controller.available(r) for r in e.robots.values())  # no new orders
    s.release("sara")
    run(e, 40)
    assert positions(e) == held and s.state == "RELEASED"
    with pytest.raises(SafetyError):
        s.release("sara")
    for _ in range(200):  # workers walk away; then the reset is accepted
        try:
            s.reset("sara")
            break
        except SafetyError as err:
            assert "person" in str(err)
            e.tick()
    assert s.state == "NORMAL"
    run(e, 40)
    assert positions(e) != held
    kinds = [x["kind"] for x in s.log]
    assert {"ESTOP", "ESTOP_RELEASED", "ESTOP_RESET"} <= set(kinds)
    assert next(x for x in s.log if x["kind"] == "ESTOP")["user"] == "sara"


def test_reset_needs_a_release_first():
    e = engine()
    with pytest.raises(SafetyError):
        e.safety.reset("sara")
    e.safety.engage("sara", "test")
    with pytest.raises(SafetyError):
        e.safety.reset("sara")  # still engaged
    with pytest.raises(SafetyError):
        e.safety.engage("sara", "again")  # the fleet is already stopped


def test_zone_stop_holds_only_that_zone_and_keeps_others_out():
    e = engine()
    zone = e.layout.zones[0]
    inside = {rid for rid, r in e.robots.items() if zone.contains(*r.position)}
    e.safety.engage("sara", "maintenance in zone", zone=zone.zone_id)
    held = positions(e)
    run(e, 60)
    now = positions(e)
    assert all(now[rid] == held[rid] for rid in inside)
    outside_moved = [rid for rid in e.robots if rid not in inside and now[rid] != held[rid]]
    assert outside_moved  # the rest of the fleet keeps working
    assert not any(zone.contains(*now[rid]) for rid in e.robots if rid not in inside)
    with pytest.raises(SafetyError):
        e.safety.engage("sara", "x", zone="ZONE_NOPE")


def test_slow_zones_halve_speed_near_people_and_near_misses_are_logged():
    fast, slow = engine(slow_zones=False), engine(slow_zones=True)
    run(fast, 600)
    run(slow, 600)
    assert slow.safety.metrics["slow_robot_ticks"] > 0
    assert fast.safety.metrics["slow_robot_ticks"] == 0
    near = [x for x in slow.safety.log if x["kind"] == "NEAR_MISS"]
    assert all(x["detail"]["distance_m"] <= 1 and x["robot_id"] for x in near)
    assert "safety" in slow.state()  # the live state carries the safety status


def test_with_slow_zones_off_the_safety_layer_changes_no_behaviour(monkeypatch):
    """configs/simulation.yaml has slow zones off, so recorded datasets, the golden master and
    the trained models stay valid: watching (near misses, the log) must not change a run."""
    assert SimulationEngine(seed=42).safety.slow_zones is False
    watched = fingerprint(ticks=400)
    from simulation.environment import safety

    monkeypatch.setattr(safety.Safety, "step", lambda self: None)
    monkeypatch.setattr(safety.Safety, "observe", lambda self, events: None)
    assert fingerprint(ticks=400) == watched


def test_reset_next_to_a_person_needs_an_explicit_area_check():
    e = engine()
    s = e.safety
    s.engage("sara", "test")
    s.release("sara")
    robot = next(iter(e.robots.values()))
    e.workers.positions[0] = (robot.position[0] + 1, robot.position[1])  # someone stands there
    with pytest.raises(SafetyError, match="person"):
        s.reset("sara")
    s.reset("sara", area_checked=True)
    assert s.state == "NORMAL"
    confirmed = next(x for x in s.log if x["kind"] == "RESET_CONFIRMED")
    assert confirmed["user"] == "sara" and robot.robot_id in confirmed["text"]
