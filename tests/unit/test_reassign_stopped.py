"""SOP-03 step 3: an operator may move an order off a stopped robot to another robot, but only
before any of its items is in that robot's tote. And SOP-04 in the dispatcher."""

from simulation.environment.engine import Command, SimulationEngine
from simulation.events.events import EventType
from simulation.warehouse.entities import OrderStatus, RobotStatus


def setup():
    e = SimulationEngine(
        seed=4, overrides={"layout": "default", "orders": {"arrival_prob_per_tick": 0.0}}
    )
    e.start()
    e.tick()
    rejected = []
    e.events.subscribe(lambda ev: ev.type == EventType.COMMAND_REJECTED and rejected.append(ev))
    return e, rejected


def new_order(e):
    oid = e.next_order_id()
    pid = next(iter(e.inventory.face))
    e.submit(
        Command(
            "create_order",
            {
                "order_id": oid,
                "priority": "HIGH",
                "items": [{"product_id": pid, "quantity": 1}],
                "robot_id": None,
            },
        )
    )
    e.tick()
    return e.orders[oid]


def test_order_moves_off_a_faulted_robot_before_any_pick():
    e, rejected = setup()
    order = new_order(e)
    holder = e.robots[order.assigned_robot]
    holder.status = RobotStatus.FAULT  # a stop event, nothing picked yet
    other = next(r for r in e.robots.values() if e.controller.can_take_order(r))
    e.submit(Command("assign_order", {"order_id": order.order_id, "robot_id": other.robot_id}))
    e.tick()
    assert order.assigned_robot == other.robot_id and order.status == OrderStatus.ASSIGNED
    assert holder.robot_id not in e.controller.tasks and not rejected


def test_refused_once_items_are_in_the_tote_or_while_running():
    e, rejected = setup()
    order = new_order(e)
    holder = e.robots[order.assigned_robot]
    other = next(r for r in e.robots.values() if e.controller.can_take_order(r))
    e.submit(Command("assign_order", {"order_id": order.order_id, "robot_id": other.robot_id}))
    e.tick()
    assert order.assigned_robot == holder.robot_id  # it is moving: not taken away
    assert "being carried" in rejected[-1].payload["reason"]
    e.controller.tasks[holder.robot_id].stops.clear()  # as if everything was picked
    holder.status = RobotStatus.PAUSED
    e.submit(Command("assign_order", {"order_id": order.order_id, "robot_id": other.robot_id}))
    e.tick()
    assert order.assigned_robot == holder.robot_id
    assert "already picked" in rejected[-1].payload["reason"]


def test_sop04_hot_robot_gets_no_order_until_cool():
    e, _ = setup()
    e.config["thermal"]["no_new_orders_above"] = 60.0
    r = next(r for r in e.robots.values() if e.controller.available(r))
    r.temperature = 62.0
    assert not e.controller.can_take_order(r) and "cooling down" in e.controller.unavailable_reason(
        r
    )
    r.temperature = 57.0  # between the two limits: still cooling (hysteresis)
    assert not e.controller.can_take_order(r)
    r.temperature = 54.0
    assert e.controller.can_take_order(r)
