"""Labour management for the associates (backlog PR-31; docs/labour.md).

Engineered labour standards, as a real labour management system (LMS) uses them:

    standard time of a task = walking at the standard pace + the handling standard of its type
                              (+ per unit for packing)

People are not all the same: every associate has a personal pace (about 75-130 % of standard,
seeded, so runs repeat) and each task varies a little around it. The actual time is what the
work takes them; the standard is what it should take a trained person at a normal pace.

    performance  = earned standard time / time actually spent on tasks   (100 % = on standard)
    utilisation  = time on tasks / time in the shift so far
    productivity = performance x utilisation  (the share of the shift that earned standard time)

Everything is kept per associate and per shift (8 simulated hours), so a supervisor sees the
current shift and hands over with the previous shift's report and the open work.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict

SHIFT_HOURS = 8
PACE_SPREAD = 0.12  # standard deviation of the personal pace around 1.0
PACE_LIMITS = (0.75, 1.3)
TASK_SPREAD = 0.10  # task-to-task variation around a person's pace


def _empty_row() -> dict:
    return {"earned": 0.0, "worked": 0, "tasks": 0, "types": Counter()}


class Labour:
    def __init__(self, wms, seed: str) -> None:
        self.wms = wms
        self.rng = random.Random(f"{seed}:labour")  # its own stream: other randomness unchanged
        lo, hi = PACE_LIMITS
        self.pace = {
            name: round(min(max(self.rng.gauss(1.0, PACE_SPREAD), lo), hi), 3)
            for name in sorted(wms.associates)
        }
        # (shift, associate) -> earned / worked ticks, tasks, by type
        # A named factory, not a lambda: the WMS is saved in warehouse snapshots (pickle).
        self.book: dict[tuple[int, str], dict] = defaultdict(_empty_row)

    # ----- standards --------------------------------------------------------------------------
    def standard_ticks(self, task_type: str, walk_ticks: float, units: int = 1) -> float:
        cfg = self.wms.cfg
        handling = cfg["handling_ticks"][task_type]
        if task_type == "PACK":
            handling += cfg["pack_ticks_per_unit"] * units
        return walk_ticks + handling

    def actual_ticks(self, name: str, standard: float) -> int:
        """What the task takes this person: their pace, with some variation per task."""
        speed = self.pace.get(name, 1.0) * self.rng.gauss(1.0, TASK_SPREAD)
        return max(1, round(standard / max(speed, 0.5)))

    def standards(self) -> list[dict]:
        """The standards table: minutes per task type, handling only (walking comes on top)."""
        sec = 3600 / self.wms.tph
        rows = []
        for task_type, ticks in sorted(self.wms.cfg["handling_ticks"].items()):
            extra = " + per unit" if task_type == "PACK" else ""
            walk = self.wms.cfg["walk_m_per_tick"] / sec
            note = f"handling{extra}; walking at {walk:.1f} m/s on top"
            rows.append(
                {"task": task_type, "standard_minutes": round(ticks * sec / 60, 2), "note": note}
            )
        return rows

    # ----- booking ---------------------------------------------------------------------------
    def shift_of(self, tick: int) -> int:
        return tick // (SHIFT_HOURS * self.wms.tph)

    def done(self, name: str, task_type: str, standard: float, started: int, finished: int):
        row = self.book[(self.shift_of(started), name)]
        row["earned"] += standard
        row["worked"] += max(1, finished - started)
        row["tasks"] += 1
        row["types"][task_type] += 1

    # ----- reports ---------------------------------------------------------------------------
    def report(self, shift: int | None = None) -> dict:
        tick = self.wms.inv.tick
        current = self.shift_of(tick)
        shift = current if shift is None else shift
        length = SHIFT_HOURS * self.wms.tph
        elapsed = min(length, tick - shift * length) if shift == current else length
        hours = 3600 / self.wms.tph / 3600  # simulated hours per tick
        people, crews = [], defaultdict(lambda: {"earned": 0.0, "worked": 0, "tasks": 0, "n": 0})
        for name in sorted(self.wms.associates):
            a = self.wms.associates[name]
            row = self.book.get((shift, name), {"earned": 0.0, "worked": 0, "tasks": 0,
                                                "types": Counter()})  # fmt: skip
            perf = row["earned"] / row["worked"] if row["worked"] else None
            util = row["worked"] / elapsed if elapsed else None
            people.append({
                "associate": name, "crew": a["crew"], "pace": self.pace.get(name),
                "tasks": row["tasks"], "earned_hours": round(row["earned"] * hours, 2),
                "worked_hours": round(row["worked"] * hours, 2),
                "performance_percent": None if perf is None else round(100 * perf, 1),
                "utilisation_percent": None if util is None else round(100 * min(util, 1), 1),
                "productivity_percent": None if perf is None or util is None
                else round(100 * perf * min(util, 1), 1),
                "top_tasks": dict(row["types"].most_common(3)),
                "busy_now": a["task"] is not None and shift == current,
            })  # fmt: skip
            c = crews[a["crew"]]
            c["earned"] += row["earned"]
            c["worked"] += row["worked"]
            c["tasks"] += row["tasks"]
            c["n"] += 1
        crew_rows = []
        for crew, c in sorted(crews.items()):
            perf = round(100 * c["earned"] / c["worked"], 1) if c["worked"] else None
            util = round(100 * c["worked"] / (elapsed * c["n"]), 1) if elapsed and c["n"] else None
            row = {"crew": crew, "people": c["n"], "tasks": c["tasks"]}
            crew_rows.append({**row, "performance_percent": perf, "utilisation_percent": util})
        open_work = Counter(t.type for t in self.wms.tasks.values() if t.status == "OPEN")
        below = [p["associate"] for p in people
                 if p["performance_percent"] is not None and p["performance_percent"] < 85
                 and p["tasks"] >= 5]  # fmt: skip
        return {
            "shift": shift, "current_shift": current, "shift_hours": SHIFT_HOURS,
            "hours_elapsed": round(elapsed * hours, 2),
            "people": people, "crews": crew_rows,
            "handover": {"open_tasks": dict(open_work), "below_85_percent": below,
                         "in_progress": sum(p["busy_now"] for p in people)},
            "standards": self.standards(),
        }  # fmt: skip
