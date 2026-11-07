"""AMR physics: acceleration, braking, turning costs (PR-05).

Calibrated to the MiR 100 datasheet:
  max speed  1.5 m/s straight
  accel/decel  0.5 m/s²
  cornering  speed drops to 0.5 m/s through a 90° turn

Grid cell = 1 m.  Time unit = 1 simulation tick (1/600 of a simulated hour = 6 s real).

Public API
----------
count_turns(path)                  → int     direction changes along a path
travel_ticks(cells, turns, cfg)    → int     ticks the physics model adds on top of path length
pace_ticks(path, cfg)              → list[int]  per-cell extra-wait schedule (index 0 = first step)
PhysicsConfig                      → dataclass  AMR parameters (read from config["physics"])
"""

from __future__ import annotations

from dataclasses import dataclass

Cell = tuple[int, int]

# MiR 100 defaults (can be overridden per experiment in config["physics"])
_MAX_SPEED_MS: float = 1.5
_ACCEL_MS2: float = 0.5
_TURN_SPEED_MS: float = 0.5
_CELL_M: float = 1.0
_TICKS_PER_HOUR: int = 600


@dataclass
class PhysicsConfig:
    enabled: bool = True
    max_speed_ms: float = _MAX_SPEED_MS
    accel_ms2: float = _ACCEL_MS2
    turn_speed_ms: float = _TURN_SPEED_MS
    cell_m: float = _CELL_M
    # Pre-computed tick penalties (derived on first use)
    _accel_ticks: int | None = None
    _turn_ticks: int | None = None

    @classmethod
    def from_config(cls, cfg: dict) -> "PhysicsConfig":
        p = cfg.get("physics", {})
        return cls(
            enabled=p.get("enabled", True),
            max_speed_ms=p.get("max_speed_ms", _MAX_SPEED_MS),
            accel_ms2=p.get("accel_ms2", _ACCEL_MS2),
            turn_speed_ms=p.get("turn_speed_ms", _TURN_SPEED_MS),
            cell_m=p.get("cell_m", _CELL_M),
        )

    def _seconds_per_tick(self, ticks_per_hour: int) -> float:
        return 3600.0 / ticks_per_hour

    def accel_ticks(self, ticks_per_hour: int = _TICKS_PER_HOUR) -> int:
        """Extra ticks to accelerate from rest to max speed (once per route start)."""
        if self._accel_ticks is None:
            # time = v / a, convert to ticks
            t_s = self.max_speed_ms / self.accel_ms2
            self._accel_ticks = max(1, round(t_s / self._seconds_per_tick(ticks_per_hour)))
        return self._accel_ticks

    def turn_ticks(self, ticks_per_hour: int = _TICKS_PER_HOUR) -> int:
        """Extra ticks lost at each 90° direction change."""
        if self._turn_ticks is None:
            # time to slow to turn speed + re-accelerate; rough model: 2*(v_diff / a)
            v_diff = self.max_speed_ms - self.turn_speed_ms
            t_s = 2.0 * v_diff / self.accel_ms2
            self._turn_ticks = max(1, round(t_s / self._seconds_per_tick(ticks_per_hour)))
        return self._turn_ticks


def count_turns(path: list[Cell]) -> int:
    """Count 90° direction changes along a path (start → … → end)."""
    if len(path) < 3:
        return 0
    turns = 0
    dx0 = path[1][0] - path[0][0]
    dy0 = path[1][1] - path[0][1]
    for i in range(2, len(path)):
        dx1 = path[i][0] - path[i - 1][0]
        dy1 = path[i][1] - path[i - 1][1]
        if (dx1, dy1) != (dx0, dy0):
            turns += 1
        dx0, dy0 = dx1, dy1
    return turns


def travel_ticks(
    cells: int,
    turns: int,
    cfg: PhysicsConfig,
    ticks_per_hour: int = _TICKS_PER_HOUR,
) -> int:
    """Total simulation ticks to traverse `cells` cells with `turns` direction changes.

    Returns the Manhattan ticks (cells) plus physics overhead; never less than cells.
    When cfg.enabled is False, returns cells unchanged.
    """
    if not cfg.enabled or cells == 0:
        return cells
    overhead = cfg.accel_ticks(ticks_per_hour) + turns * cfg.turn_ticks(ticks_per_hour)
    return cells + overhead


def pace_ticks(
    path: list[Cell],
    cfg: PhysicsConfig,
    ticks_per_hour: int = _TICKS_PER_HOUR,
) -> list[int]:
    """Per-cell extra-wait schedule for the controller.

    Returns a list parallel to `path` where each value is how many additional ticks the robot
    must wait *before* stepping onto that cell (0 = step as normal).

    - Cell 0 (first step) gets accel_ticks — the robot starts from rest.
    - Every cell where a direction change occurs gets turn_ticks.
    - The last cell gets decel_ticks (braking to a stop) counted as an extra dwell, handled by
      the caller, so it is NOT included here (avoid double-counting with the stage dwell timer).
    """
    if not cfg.enabled or not path:
        return [0] * len(path)

    at = cfg.accel_ticks(ticks_per_hour)
    tt = cfg.turn_ticks(ticks_per_hour)

    waits: list[int] = [0] * len(path)
    waits[0] = at  # start from rest

    if len(path) >= 2:
        dx0 = path[1][0] - path[0][0]
        dy0 = path[1][1] - path[0][1]
        for i in range(2, len(path)):
            dx1 = path[i][0] - path[i - 1][0]
            dy1 = path[i][1] - path[i - 1][1]
            if (dx1, dy1) != (dx0, dy0):
                waits[i - 1] = tt  # penalty on the cell where the turn begins
            dx0, dy0 = dx1, dy1

    return waits
