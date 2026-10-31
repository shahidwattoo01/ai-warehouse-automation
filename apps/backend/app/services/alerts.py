"""Alert centre (backlog PR-32): rules, incidents, acknowledgement, escalation, notifications.

Every 30 ticks (3 simulated minutes) each enabled rule (configs/alert_rules.yaml) looks at the
simulator, the AI predictions and the WMS and returns the subjects for which its condition holds
(a robot, the order queue, a truck). One incident is kept per rule and subject:

    OPEN ─► ACKNOWLEDGED (who, when, note) ─► RESOLVED
      │                                          ▲  automatically when the condition clears, or
      └─ not acknowledged within escalate_after ─┘  by a person (then the rule stays quiet for
         minutes: ESCALATED, notified again          that subject until the condition clears)

Against flapping: an incident opens after its condition held in `confirm_checks` checks in a row
(2 for the AI anomaly flag) and resolves after it was absent in `clear_checks` checks (2).

Notifications go to the screen always, and by email (SMTP) or webhook (Slack / Teams / any URL)
when configured; every attempt is logged with its outcome. Sending runs on a worker thread, so
a slow mail server never holds up the simulation.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import smtplib
import threading
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass, field
from email.message import EmailMessage
from pathlib import Path

import yaml

from app.core.config import get_settings

log = logging.getLogger(__name__)
RULES_FILE = Path(__file__).resolve().parents[4] / "configs" / "alert_rules.yaml"
EVERY_TICKS = 30
SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass
class Incident:
    alert_id: str
    rule: str
    subject: str
    severity: str
    title: str
    detail: str
    opened_tick: int
    opened_at: str
    status: str = "OPEN"  # OPEN | ACKNOWLEDGED | RESOLVED
    escalated: bool = False
    escalated_tick: int | None = None
    acknowledged_by: str | None = None
    acknowledged_at: str | None = None
    resolved_by: str | None = None
    resolved_tick: int | None = None
    resolved_at: str | None = None
    history: list[dict] = field(default_factory=list)

    def log(self, tick: int, event: str, user: str = "system", note: str | None = None) -> None:
        self.history.append(
            {"at": now().isoformat(timespec="seconds"), "tick": tick, "event": event,
             "user": user, "note": note}
        )  # fmt: skip

    def to_dict(self) -> dict:
        return asdict(self)


class AlertCentre:
    def __init__(self, rules_file: Path = RULES_FILE) -> None:
        raw = yaml.safe_load(rules_file.read_text(encoding="utf-8"))["rules"]
        self.rules: dict[str, dict] = {
            rid: {"enabled": True, "unit": None, "confirm_checks": 1, "clear_checks": 2, **spec}
            for rid, spec in raw.items()
        }
        self.reset()

    def reset(self) -> None:
        """A new simulation run starts with no incidents (rules and their settings stay)."""
        self.incidents: dict[str, Incident] = {}
        self.active: dict[tuple[str, str], str] = {}  # (rule, subject) -> open incident id
        self.quiet: set[tuple[str, str]] = set()  # resolved by hand: wait until the cause clears
        self.notifications: deque = deque(maxlen=300)
        self._changed: set[str] = set()
        self._seq = 0
        self._seen: dict[tuple[str, str], int] = {}  # checks in a row a condition has held
        self._gone: dict[tuple[str, str], int] = {}  # checks in a row an open one has been absent

    # ----- conditions ------------------------------------------------------------------------
    def _conditions(self, engine, predictions: dict | None) -> dict[str, dict[str, tuple]]:
        """rule -> {subject: (title, detail)} for every condition that holds now."""
        r = self.rules
        out: dict[str, dict[str, tuple]] = {k: {} for k in r}
        robots = engine.robots.values()
        for robot in robots:
            if robot.status.value == "FAULT":
                out["robot_fault"][robot.robot_id] = (
                    f"{robot.robot_id} is in fault",
                    f"at {robot.position}, battery {robot.battery:.0f} %",
                )
            limit = r["battery_critical"]["threshold"]
            if robot.battery < limit:
                out["battery_critical"][robot.robot_id] = (
                    f"{robot.robot_id} battery {robot.battery:.0f} %",
                    f"below {limit} %; it needs a charger now (SOP-02)",
                )
        for rid, h in ((predictions or {}).get("robots") or {}).items():
            if h.get("abnormal"):
                out["robot_abnormal"][rid] = (
                    f"{rid} flagged by the anomaly model",
                    h.get("reason") or "",
                )
        safety = engine.safety
        if safety.state == "ESTOP" and safety.stop:
            where = safety.stop["zone"] or "fleet"
            out["emergency_stop"][where] = (
                f"Emergency stop: {where}",
                f"{safety.stop['reason']} (by {safety.stop['by']}), {len(safety.held)} robots held",
            )
        pending = sum(o.status.value == "PENDING" for o in engine.orders.values())
        if pending >= r["order_backlog"]["threshold"]:
            out["order_backlog"]["queue"] = (
                f"{pending} orders waiting for a robot",
                "check SOP-07",
            )
        k = engine.kpis.snapshot()
        if (
            k.get("orders_completed", 0) >= 20
            and k.get("late_percent", 0) > r["late_rate"]["threshold"]
        ):
            out["late_rate"]["fleet"] = (
                f"{k['late_percent']}% of orders late",
                f"target below {r['late_rate']['threshold']} %",
            )
        hour = engine.config.get("ticks_per_hour", 600)
        recent = sum(
            1 for e in safety.log if e["kind"] == "NEAR_MISS" and engine.time - e["tick"] <= hour
        )
        if recent >= r["near_misses"]["threshold"]:
            out["near_misses"]["fleet"] = (f"{recent} near misses in the last hour", "Safety page")
        wms = getattr(engine.inventory, "wms", None)
        if wms is not None:
            waiting = len(wms.waiting)
            if waiting >= r["waiting_stock"]["threshold"]:
                out["waiting_stock"]["stock"] = (f"{waiting} orders waiting for stock", "Inventory")
            pending_counts = sum(1 for c in wms.counts.values() if c.status == "PENDING_APPROVAL")
            if pending_counts >= r["counts_to_approve"]["threshold"]:
                out["counts_to_approve"]["counts"] = (
                    f"{pending_counts} count differences to approve",
                    "Inventory, Cycle counts",
                )
            out_ = wms.out
            for trip in out_.trips.values():
                if trip.status != "SCHEDULED":
                    continue
                minutes = (trip.departs - engine.time) * 60 / hour
                row = out_.trip_row(trip) if minutes <= r["truck_at_risk"]["threshold"] else None
                if row and row["orders_waiting"] > 0:
                    out["truck_at_risk"][trip.trip_id] = (
                        f"{row['carrier_name']} leaves in {round(minutes)} min",
                        f"{row['orders_waiting']} planned orders not on board (SOP-12)",
                    )
        return out

    # ----- the cycle -------------------------------------------------------------------------
    def evaluate(self, engine, predictions: dict | None = None) -> None:
        if engine.time % EVERY_TICKS:
            return
        tick = engine.time
        holding = self._conditions(engine, predictions)
        hour = engine.config.get("ticks_per_hour", 600)
        for rule_id, subjects in holding.items():
            rule = self.rules[rule_id]
            for subject, (title, detail) in subjects.items():
                key = (rule_id, subject)
                if not rule["enabled"] or key in self.quiet:
                    continue
                if key in self.active:
                    self._gone.pop(key, None)
                    inc = self.incidents[self.active[key]]
                    inc.title, inc.detail = title, detail
                    due = rule["escalate_after_min"] * hour / 60
                    if inc.status == "OPEN" and not inc.escalated and tick - inc.opened_tick >= due:
                        inc.escalated, inc.escalated_tick = True, tick
                        inc.log(
                            tick,
                            "ESCALATED",
                            note=f"not acknowledged in {rule['escalate_after_min']} min",
                        )
                        self._changed.add(inc.alert_id)
                        self._notify(inc, rule["escalate_to"], "escalated")
                    continue
                self._seen[key] = self._seen.get(key, 0) + 1
                if self._seen[key] < rule["confirm_checks"]:
                    continue  # noisy rules (the AI flags) must hold in consecutive checks first
                self._seen.pop(key)
                self._seq += 1
                inc = Incident(
                    f"AL-{self._seq:05d}", rule_id, subject, rule["severity"], title, detail, tick,
                    now().isoformat(timespec="seconds"),
                )  # fmt: skip
                inc.log(tick, "OPENED", note=detail)
                self.incidents[inc.alert_id] = inc
                self.active[key] = inc.alert_id
                self._changed.add(inc.alert_id)
                self._notify(inc, rule["notify"], "opened")
        for key in list(self._seen):  # a pending condition that did not hold again
            if key[1] not in holding.get(key[0], {}):
                del self._seen[key]
        for key in list(self.active):  # conditions that cleared (for clear_checks): resolve
            if key[1] not in holding.get(key[0], {}):
                self._gone[key] = self._gone.get(key, 0) + 1
                if self._gone[key] < self.rules[key[0]]["clear_checks"]:
                    continue
                del self._gone[key]
                inc = self.incidents[self.active.pop(key)]
                inc.status, inc.resolved_by, inc.resolved_tick = "RESOLVED", "system", tick
                inc.resolved_at = now().isoformat(timespec="seconds")
                inc.log(tick, "RESOLVED", note="condition cleared")
                self._changed.add(inc.alert_id)
        for key in list(self.quiet):
            if key[1] not in holding.get(key[0], {}):
                self.quiet.discard(key)
        if len(self.incidents) > 2000:  # keep the newest; the database keeps everything
            for alert_id in sorted(self.incidents)[: len(self.incidents) - 2000]:
                if self.incidents[alert_id].status == "RESOLVED":
                    del self.incidents[alert_id]

    # ----- people ----------------------------------------------------------------------------
    def acknowledge(self, alert_id: str, user: str, note: str | None, tick: int) -> Incident:
        inc = self._get(alert_id)
        if inc.status != "OPEN":
            raise ValueError(f"{alert_id} is {inc.status.lower()}")
        inc.status, inc.acknowledged_by = "ACKNOWLEDGED", user
        inc.acknowledged_at = now().isoformat(timespec="seconds")
        inc.log(tick, "ACKNOWLEDGED", user, note)
        self._changed.add(alert_id)
        return inc

    def resolve(self, alert_id: str, user: str, note: str | None, tick: int) -> Incident:
        inc = self._get(alert_id)
        if inc.status == "RESOLVED":
            raise ValueError(f"{alert_id} is already resolved")
        key = (inc.rule, inc.subject)
        if self.active.get(key) == alert_id:
            del self.active[key]
            self.quiet.add(key)  # no new incident until the cause has really cleared
        inc.status, inc.resolved_by, inc.resolved_tick = "RESOLVED", user, tick
        inc.resolved_at = now().isoformat(timespec="seconds")
        inc.log(tick, "RESOLVED", user, note)
        self._changed.add(alert_id)
        return inc

    def _get(self, alert_id: str) -> Incident:
        if alert_id not in self.incidents:
            raise KeyError(alert_id)
        return self.incidents[alert_id]

    def summary(self) -> dict:
        live = [i for i in self.incidents.values() if i.status != "RESOLVED"]
        return {
            "open": sum(i.status == "OPEN" for i in live),
            "acknowledged": sum(i.status == "ACKNOWLEDGED" for i in live),
            "critical": sum(i.severity == "critical" for i in live),
            "escalated": sum(i.escalated and i.status == "OPEN" for i in live),
        }

    def take_changed(self) -> list[Incident]:
        out = [self.incidents[a] for a in sorted(self._changed) if a in self.incidents]
        self._changed = set()
        return out

    # ----- notifications ---------------------------------------------------------------------
    def _notify(self, inc: Incident, channels: list[str], why: str) -> None:
        for channel in channels:
            entry = {
                "at": now().isoformat(timespec="seconds"),
                "alert_id": inc.alert_id,
                "channel": channel,
                "why": why,
                "status": "PENDING",
                "detail": None,
            }
            self.notifications.appendleft(entry)
            if channel == "screen":
                entry["status"] = "SHOWN"
                continue
            threading.Thread(
                target=self._send, args=(channel, inc, why, entry), daemon=True
            ).start()

    @staticmethod
    def _send(channel: str, inc: Incident, why: str, entry: dict) -> None:
        s = get_settings()
        subject = f"[{inc.severity.upper()}] {inc.title} ({why})"
        body = f"{inc.title}\n{inc.detail}\n\nAlert {inc.alert_id}, rule {inc.rule}, {why}."
        try:
            if channel == "email":
                if not (s.smtp_host and s.alert_email_to):
                    entry["status"], entry["detail"] = (
                        "NOT_CONFIGURED",
                        "set SMTP_HOST and ALERT_EMAIL_TO",
                    )
                    return
                msg = EmailMessage()
                msg["Subject"], msg["From"], msg["To"] = subject, s.smtp_from, s.alert_email_to
                msg.set_content(body)
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                    if s.smtp_user:
                        smtp.starttls()
                        smtp.login(s.smtp_user, s.smtp_password)
                    smtp.send_message(msg)
            elif channel == "webhook":
                if not s.alert_webhook_url:
                    entry["status"], entry["detail"] = "NOT_CONFIGURED", "set ALERT_WEBHOOK_URL"
                    return
                data = json.dumps({"text": f"{subject}\n{inc.detail}", "alert": inc.to_dict()})
                req = urllib.request.Request(
                    s.alert_webhook_url, data.encode(), {"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=10):  # noqa: S310 (configured URL)
                    pass
            else:
                entry["status"], entry["detail"] = "FAILED", f"unknown channel {channel}"
                return
            entry["status"] = "SENT"
        except Exception as err:  # noqa: BLE001 - every failure is reported in the log
            entry["status"], entry["detail"] = "FAILED", str(err)[:200]
            log.warning("Alert %s via %s failed: %s", inc.alert_id, channel, err)


centre = AlertCentre()
