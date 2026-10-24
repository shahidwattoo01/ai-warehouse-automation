"""Phase 6 operator commands in the engine: an operator closure lasts until reopened, and a
reroute plans the robot's route around the aisles it should avoid."""

from simulation.environment.engine import Command, SimulationEngine
from simulation.events.events import EventType


def test_operator_closure_stays_until_reopened():
    engine = SimulationEngine(seed=3, overrides={"orders": {"arrival_prob_per_tick": 0.0}})
    aisle = next(a for a in engine.layout.aisles if not engine.hazards.blockers(a.aisle_id))
    engine.submit(Command("close_aisle", {"aisle_id": aisle.aisle_id, "reason": "maintenance"}))
    engine.start()
    for _ in range(200):
        engine.tick()
    assert aisle.aisle_id in engine.hazards.closures
    assert set(aisle.cells) <= engine.layout.grid.closed

    engine.submit(Command("open_aisle", {"aisle_id": aisle.aisle_id}))
    engine.tick()
    assert aisle.aisle_id not in engine.hazards.closures
    assert not set(aisle.cells) & engine.layout.grid.closed


def _robot_driving_through_an_aisle(engine: SimulationEngine):
    """A robot whose route passes through an aisle it neither stands in nor ends in."""
    for _ in range(400):
        engine.tick()
        for robot in engine.robots.values():
            goal = engine.controller.goal.get(robot.robot_id)
            for aisle in engine.layout.aisles:
                cells = set(aisle.cells)
                if (
                    len(robot.route) > 5
                    and cells & set(robot.route[1:-3])
                    and robot.position not in cells
                    and goal not in cells
                ):
                    return robot, aisle
    raise AssertionError("no robot drove through an aisle")


def test_reroute_avoids_the_named_aisle():
    engine = SimulationEngine(seed=3)
    engine.start()
    robot, aisle = _robot_driving_through_an_aisle(engine)
    goal = engine.controller.goal[robot.robot_id]

    engine.submit(Command("reroute_robot", {"robot_id": robot.robot_id, "avoid": [aisle.aisle_id]}))
    events = engine.tick()
    assert not set(aisle.cells) & set(robot.route)
    assert engine.controller.goal[robot.robot_id] == goal  # same destination, different way
    assert any(e.type == EventType.ROUTE_CHANGED and e.payload.get("operator") for e in events)
