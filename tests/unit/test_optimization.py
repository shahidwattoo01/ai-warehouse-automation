"""Phase 4 optimisation: planners, route distances, assignment strategies and fair experiments."""

import random

import pytest

from ai.optimization.astar import AStarPlanner
from ai.optimization.dijkstra import DijkstraPlanner
from ai.optimization.optimizer import BASELINE, Optimizer, experiment_presets
from ai.optimization.traffic import TrafficCosts
from simulation.environment.engine import SimulationEngine
from simulation.navigation.planner import BFSPlanner
from tests.unit.golden_master import fingerprint


def _engine(seed: int = 3, **overrides) -> SimulationEngine:
    engine = SimulationEngine(seed=seed, overrides={"layout": "large", **overrides})
    engine.start()
    return engine


def _walkable_pairs(engine, n: int, seed: int = 1):
    rng = random.Random(seed)
    grid = engine.layout.grid
    cells = [
        (x, y)
        for y in range(grid.height)
        for x in range(grid.width)
        if grid.is_walkable(x, y) and (x, y) not in grid.destination_only
    ]
    return [(rng.choice(cells), rng.choice(cells)) for _ in range(n)]


def test_dijkstra_and_astar_find_routes_as_short_as_bfs():
    engine = _engine()
    grid = engine.layout.grid
    bfs, dijkstra, astar = BFSPlanner(), DijkstraPlanner(), AStarPlanner()
    for a, b in _walkable_pairs(engine, 40):
        expected = len(bfs.plan(grid, a, b))
        assert len(dijkstra.plan(grid, a, b)) == expected
        assert len(astar.plan(grid, a, b)) == expected


def test_routes_respect_one_way_aisles_and_closed_cells():
    engine = _engine()
    grid = engine.layout.grid
    closure = engine.hazards.close_random_aisle()
    closed = set(closure.cells)
    for planner in (DijkstraPlanner(TrafficCosts(engine)), AStarPlanner(TrafficCosts(engine))):
        for a, b in _walkable_pairs(engine, 30, seed=2):
            if b in closed or a in closed:
                continue
            path = planner.plan(grid, a, b)
            assert not closed & set(path)
            for p, q in zip([a, *path], path, strict=False):
                assert grid.can_move(p, q), (p, q)  # every step legal (one-way aisles)


def test_distance_fields_match_planned_route_lengths():
    engine = _engine()
    grid = engine.layout.grid
    bfs = BFSPlanner()
    for a, b in _walkable_pairs(engine, 40, seed=3):
        path = bfs.plan(grid, a, b)
        expected = len(path) if path or a == b else -1
        assert engine.distances.distance(a, b) == expected


def test_traffic_aware_route_avoids_a_robot_standing_in_the_way():
    engine = _engine()
    grid = engine.layout.grid
    # Main highway (4 lanes wide at x 38-41): park a robot on the straight line and plan past it.
    blocker = next(iter(engine.robots.values()))
    blocker.position = (39, 30)
    start, goal = (39, 26), (39, 40)
    plain = AStarPlanner().plan(grid, start, goal)
    aware = AStarPlanner(TrafficCosts(engine)).plan(grid, start, goal)
    assert (39, 30) in plain or len(plain) == len(aware)
    assert (39, 30) not in aware


def test_baseline_optimizer_changes_nothing():
    plain = fingerprint(ticks=400)
    engine = SimulationEngine(
        seed=42, overrides={"layout": "large", "faults": {"probability_per_hour": 3.0}}
    )
    Optimizer(engine, None, BASELINE)
    engine.start()
    import hashlib
    import json

    h = hashlib.sha256()
    for _ in range(400):
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
            ],  # fmt: skip
            "orders": sorted(
                (o.order_id, o.status.value, o.assigned_robot) for o in engine.orders.values()
            ),
            "events": [(e.type.value, e.entity_id) for e in events],
        }
        h.update(json.dumps(snapshot, default=str).encode())
    assert h.hexdigest() == plain


def test_independent_streams_give_every_strategy_the_same_orders():
    def created(strategies):
        engine = _engine(seed=9, independent_streams=True)
        Optimizer(engine, None, strategies)
        orders = []
        for _ in range(900):
            orders += [e.entity_id for e in engine.tick() if e.type.value == "ORDER_CREATED"]
        return orders

    assert created(BASELINE) == created(
        {"assignment": "random", "planner": "astar", "traffic_aware": True}
    )


@pytest.mark.parametrize("assignment", ["random", "eta", "global"])
def test_assignment_strategies_deliver_orders_without_overlap(assignment):
    from ai.optimization.eta_estimator import MODEL

    if assignment != "random" and not MODEL.exists():
        pytest.skip("train notebooks/01_eta first")
    engine = _engine(seed=5, independent_streams=True)
    optimizer = Optimizer(
        engine, None, {"assignment": assignment, "planner": "astar", "traffic_aware": True}
    )
    delivered = 0
    for _ in range(1200):
        delivered += sum(e.type.value == "ORDER_DELIVERED" for e in engine.tick())
        optimizer.after_tick()
        positions = [r.position for r in engine.robots.values()]
        assert len(positions) == len(set(positions))
    assert delivered > 10
    busy = [t.order_id for t in engine.controller.tasks.values() if t.kind == "order"]
    assert len(busy) == len(set(busy))  # no order given to two robots


def test_presets_are_the_phase4_experiments():
    presets = experiment_presets()
    assert {"E1", "E2", "E3", "E4", "E5"} <= set(presets)
    assert presets["E2"]["strategies"] == BASELINE
