"""Unit tests for the simulator core (Phase 1 skeleton)."""

from simulation.environment.engine import Command, SimulationEngine
from simulation.navigation.planner import BFSPlanner
from simulation.warehouse.entities import RobotStatus
from simulation.warehouse.grid import CellType, Grid
from simulation.warehouse.layout import load_layout


def test_layout_loads_shelves_and_stations():
    layout = load_layout("default")
    assert layout.grid.width == 40 and layout.grid.height == 28
    assert len(layout.shelves) == 150
    assert any(s.type == "CHARGING" for s in layout.stations)
    shelf = layout.shelves[0]
    assert layout.grid.get(shelf.x, shelf.y) == CellType.SHELF


def test_planner_finds_path_and_avoids_walls():
    grid = Grid(5, 5)
    for y in range(4):
        grid.set(2, y, CellType.BLOCKED)
    path = BFSPlanner().plan(grid, (0, 0), (4, 0))
    assert path[-1] == (4, 0)
    assert all(grid.is_walkable(x, y) for x, y in path)


def test_engine_state_and_pause_command():
    engine = SimulationEngine(seed=1, overrides={"layout": "default"})
    state = engine.state()
    assert len(state["robots"]) == 12 and state["time"] == 0
    engine.submit(Command("pause_robot", {"robot_id": "R1"}))
    events = engine.tick()
    assert engine.robots["R1"].status == RobotStatus.PAUSED
    assert events[0].type.value == "ROBOT_PAUSED"
    assert engine.time == 1


def _reachable(grid, src):
    from collections import deque

    seen, queue = {src}, deque([src])
    while queue:
        for nxt in grid.neighbors(*queue.popleft()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def test_layouts_have_no_dead_ends_or_one_way_traps():
    for name in ("default", "large"):
        grid = load_layout(name).grid
        cells = [
            (x, y) for y in range(grid.height) for x in range(grid.width) if grid.is_walkable(x, y)
        ]
        hub = cells[len(cells) // 2]
        from_hub = _reachable(grid, hub)
        assert set(cells) <= from_hub, name
        assert all(hub in _reachable(grid, c) for c in cells[:: max(1, len(cells) // 60)]), name


def test_one_way_aisle_is_directed():
    grid = load_layout("large").grid
    # y=4 runs east: from (10, 4) the robot may go to (11, 4) but not back to (9, 4).
    assert (11, 4) in grid.neighbors(10, 4)
    assert (9, 4) not in grid.neighbors(10, 4)


def test_large_layout_spawns_full_fleet_without_overlap():
    engine = SimulationEngine(seed=2)
    assert engine.layout.name == "large" and len(engine.robots) == 40
    positions = [r.position for r in engine.robots.values()]
    assert len(set(positions)) == 40


def test_large_layout_has_parking_areas_and_spreads_robots():
    layout = load_layout("large")
    assert len(layout.parking_areas) == 8 and len(layout.parking) == 88
    engine = SimulationEngine(seed=2)
    area_of = {c: a.area_id for a in layout.parking_areas for c in a.cells}
    start_areas = {area_of[r.position] for r in engine.robots.values()}
    assert len(start_areas) == 8  # every area gets robots at the start


def test_routes_never_cut_through_parking_bays_but_every_bay_is_reachable():
    layout = load_layout("large")
    grid, planner = layout.grid, BFSPlanner()
    # A route along the north wall stays in the lane instead of crossing bays P1.
    route = planner.plan(grid, (3, 1), (18, 1))
    assert route and not any(c in grid.destination_only for c in route)
    hub = (39, 22)
    for bay in layout.parking:
        to_bay = planner.plan(grid, hub, bay)
        assert to_bay and to_bay[-1] == bay, bay
        assert not any(c in grid.destination_only for c in to_bay[:-1]), bay  # only the last cell
        assert planner.plan(grid, bay, hub), bay  # and it can leave again


def test_idle_robots_park_in_bays():
    engine = SimulationEngine(seed=4)
    engine.start()
    for _ in range(3000):
        engine.tick()
    bays = set(engine.layout.parking)
    idle = [r for r in engine.robots.values() if r.robot_id not in engine.controller.tasks]
    assert idle and all(r.position in bays for r in idle)
