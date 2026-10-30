"""Fleet safety in software: emergency stop, zone stop, slow zones near people, safety event log.

    E-STOP (fleet or one zone) ─► robots hold where they are: no driving, no picking, no new orders
            ─► RELEASE (the cause is cleared; robots still hold, nothing restarts by itself)
            ─► RESET (deliberate restart, refused while a person stands next to a held robot)

Releasing an emergency stop must never restart motion on its own (ISO 3691-4 / ISO 13850); the
separate reset is that rule. Slow zones: a robot within `slow_radius` cells of a person drives at
half speed. Near misses (a moving robot within `near_miss_radius` cells of a person), hazards,
aisle closures and safety-relevant faults are written to the same log.

This is the supervisory layer only. Certified safety (safety-rated stop circuits, personnel
detection scanners, speed and separation monitoring) lives in each robot and is not replaced by
anything here (docs/safety.md).
"""

from __future__ import annotations

from collections import Counter, deque
from typing import TYPE_CHECKING

from simulation.environment.congestion import zone_of
from simulation.events.events import Event, EventType

if TYPE_CHECKING:
    from simulation.environment.engine import SimulationEngine
    from simulation.warehouse.entities import Robot

Cell = tuple[int, int]
NEAR_MISS_REPEAT = 60  # ticks before the same robot / person pair is logged again

# Simulator events that belong in the safety log: (kind, severity)
LOGGED = {
    EventType.HAZARD_DETECTED: ("FLOOR_HAZARD", "warning"),
    EventType.AISLE_CLOSED: ("AISLE_CLOSED", "info"),
    EventType.AISLE_OPENED: ("AISLE_OPENED", "info"),
    EventType.COLLISION: ("COLLISION", "critical"),
}
SAFETY_FAULTS = {"stop_event", "overheating"}


class SafetyError(ValueError):
    """A safety command the current state does not allow."""


class Safety:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        cfg = engine.config.get("safety", {})
        self.slow_zones: bool = bool(cfg.get("slow_zones", False))
        self.slow_radius: int = int(cfg.get("slow_radius", 3))
        self.near_radius: int = int(cfg.get("near_miss_radius", 1))
        self.state = "NORMAL"  # NORMAL | ESTOP | RELEASED (waiting for a reset)
        self.stop: dict | None = None  # scope, zone, by, reason, tick
        self.held: set[str] = set()  # robots held by the stop
        self.zone_cells: set[Cell] = set()  # zone stop: other robots do not drive in
        self.slowed: set[str] = set()
        self.log: deque = deque(maxlen=2000)
        self._new: list[dict] = []
        self._near_seen: dict[tuple[str, int], int] = {}
        self.metrics: Counter = Counter()

    # ----- the log -----------------------------------------------------------------------------
    def record(
        self,
        kind: str,
        severity: str,
        text: str,
        robot: str | None = None,
        cell: Cell | None = None,
        user: str = "system",
        **detail,
    ) -> dict:
        eng = self.engine
        entry = {
            "tick": eng.time,
            "kind": kind,
            "severity": severity,
            "text": text,
            "robot_id": robot,
            "zone": zone_of(eng.layout.zones, cell) if cell else (self.stop or {}).get("zone"),
            "x": cell[0] if cell else None,
            "y": cell[1] if cell else None,
            "user": user,
            "detail": detail,
        }
        self.log.appendleft(entry)
        self._new.append(entry)
        self.metrics[kind] += 1
        return entry

    def take_new(self) -> list[dict]:
        out, self._new = self._new, []
        return out

    # ----- emergency stop ----------------------------------------------------------------------
    def engage(self, user: str, reason: str, zone: str | None = None) -> dict:
        """Stop the whole fleet (zone=None) or the robots in one zone. Takes effect before the
        next robot step; a fleet stop overrides a zone stop."""
        eng = self.engine
        if zone is not None and zone not in {z.zone_id for z in eng.layout.zones}:
            raise SafetyError(f"unknown zone {zone}")
        if self.state == "ESTOP" and self.stop and self.stop["scope"] == "fleet":
            raise SafetyError("the whole fleet is already stopped")
        if zone is None:
            robots = set(eng.robots)
            self.zone_cells = set()
        else:
            z = next(z for z in eng.layout.zones if z.zone_id == zone)
            robots = {rid for rid, r in eng.robots.items() if z.contains(*r.position)}
            robots |= self.held if self.state != "NORMAL" else set()
            self.zone_cells = {
                (x, y)
                for y in range(eng.layout.grid.height)
                for x in range(eng.layout.grid.width)
                if z.contains(x, y)
            }
        self.state = "ESTOP"
        self.held = robots
        self.stop = {
            "scope": "fleet" if zone is None else "zone",
            "zone": zone,
            "by": user,
            "reason": reason,
            "tick": eng.time,
        }
        self.metrics["estops"] += 1
        self.record(
            "ESTOP",
            "critical",
            f"Emergency stop ({'fleet' if zone is None else zone}): {reason}",
            user=user,
            robots=len(robots),
            scope=self.stop["scope"],
        )
        return self.snapshot()

    def release(self, user: str, note: str | None = None) -> dict:
        """The cause is cleared. Robots keep holding until a reset."""
        if self.state != "ESTOP":
            raise SafetyError("no emergency stop is active")
        self.state = "RELEASED"
        self.record("ESTOP_RELEASED", "warning", note or "Emergency stop released", user=user)
        return self.snapshot()

    def blockers(self) -> list[str]:
        """Held robots with a person within the near-miss radius (reset is refused)."""
        people = self.people()
        return sorted(
            rid
            for rid in self.held
            if any(_dist(self.engine.robots[rid].position, p) <= self.near_radius for p in people)
        )

    def reset(self, user: str, area_checked: bool = False) -> dict:
        """Deliberate restart after a release, refused while a person is next to a held robot,
        unless the person resetting confirms they checked the area (e.g. the person is standing
        clear and aware; robots near people then restart in a slow zone). Logged either way."""
        if self.state == "ESTOP":
            raise SafetyError("release the emergency stop first")
        if self.state != "RELEASED":
            raise SafetyError("nothing to reset")
        near = self.blockers()
        if near and not area_checked:
            raise SafetyError(f"a person is next to {', '.join(near)}; clear the area first")
        if near:
            self.record(
                "RESET_CONFIRMED",
                "warning",
                f"Reset with a person next to {', '.join(near)}: area checked by {user}",
                user=user,
                robots=near,
            )
        stopped_for = self.engine.time - (self.stop or {}).get("tick", self.engine.time)
        self.record(
            "ESTOP_RESET",
            "info",
            f"Fleet reset: {len(self.held)} robots resume",
            user=user,
            stopped_ticks=stopped_for,
        )
        self.metrics["stopped_ticks"] += stopped_for
        self.state, self.stop = "NORMAL", None
        self.held, self.zone_cells = set(), set()
        return self.snapshot()

    def holds(self, robot: Robot) -> bool:
        return self.state != "NORMAL" and robot.robot_id in self.held

    def blocks_cell(self, cell: Cell) -> bool:
        """During a zone stop no other robot drives into the zone."""
        return self.state != "NORMAL" and cell in self.zone_cells

    # ----- people and speed --------------------------------------------------------------------
    def people(self) -> list[Cell]:
        return list(self.engine.workers.positions)

    def slow(self, robot: Robot) -> bool:
        """Half speed near people: the robot skips every other step while slowed."""
        return robot.robot_id in self.slowed and self.engine.time % 2 == 1

    def step(self) -> None:
        """Before the robots move: who is near a person (slow zones, near misses)."""
        eng = self.engine
        people = self.people()
        self.slowed = set()
        if not people:
            return
        for rid, robot in eng.robots.items():
            d, who = min((_dist(robot.position, p), i) for i, p in enumerate(people))
            if self.slow_zones and d <= self.slow_radius:
                self.slowed.add(rid)
                self.metrics["slow_robot_ticks"] += 1
            if d <= self.near_radius and robot.route and not self.holds(robot):
                last = self._near_seen.get((rid, who))
                if last is None or eng.time - last >= NEAR_MISS_REPEAT:
                    self._near_seen[(rid, who)] = eng.time
                    self.metrics["near_misses"] += 1
                    self.record(
                        "NEAR_MISS",
                        "warning",
                        f"{rid} passed within {d} m of a person",
                        robot=rid,
                        cell=robot.position,
                        distance_m=d,
                        slowed=rid in self.slowed,
                    )

    def observe(self, events: list[Event]) -> None:
        """Copy the safety-relevant simulator events into the log."""
        for e in events:
            if e.type in LOGGED:
                kind, severity = LOGGED[e.type]
                cell = e.payload.get("position") or e.payload.get("cell")
                self.record(
                    kind,
                    severity,
                    e.payload.get("reason") or kind.replace("_", " ").lower(),
                    robot=e.entity_id if e.entity_id and e.entity_id.startswith("R") else None,
                    cell=tuple(cell) if cell else None,
                    ref=e.entity_id,
                )
            elif e.type == EventType.ROBOT_FAULT and e.payload.get("fault") in SAFETY_FAULTS:
                robot = self.engine.robots.get(e.entity_id or "")
                self.record(
                    "ROBOT_FAULT",
                    "warning",
                    f"{e.entity_id}: {e.payload.get('fault')}",
                    robot=e.entity_id,
                    cell=robot.position if robot else None,
                )

    # ----- reporting ---------------------------------------------------------------------------
    def snapshot(self) -> dict:
        return {
            "tick": self.engine.time,  # screens keep the newest of the stream and API answers
            "state": self.state,
            "stop": self.stop,
            "robots_held": sorted(self.held) if self.state != "NORMAL" else [],
            "slow_zones": self.slow_zones,
            "slow_radius": self.slow_radius,
            "robots_slowed": sorted(self.slowed),
            "near_misses": self.metrics["near_misses"],
            "estops": self.metrics["estops"],
        }


def _dist(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
