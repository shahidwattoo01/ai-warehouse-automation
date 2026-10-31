"""Task-directed work on handhelds (RF guns, phones) for floor staff (backlog PR-29).

    next task ─► the most urgent open task of a type the person may do is claimed for them
             ─► instructions: where to go, what to take, what to scan
             ─► confirm with a scan (the location, the plate or carton) ─► done, next task

A wrong scan is refused before anything moves. A claimed task is the person's: the simulated
associates leave it alone; one not confirmed within 30 simulated minutes goes back to the queue.
"""

from __future__ import annotations

from wms import barcodes as bc
from wms.inventory import InventoryError
from wms.operations import Task

# Task types a person can do on a handheld, and the permission each needs.
RF_TYPES = {
    "RECEIVE": "wms:receive",
    "PUTAWAY": "wms:receive",
    "REPLENISH_URGENT": "wms:move",
    "REPLENISH": "wms:move",
    "COUNT": "wms:count",
    "LOAD": "wms:ship",
}
CLAIM_MINUTES = 30


class RFError(ValueError):
    """The scan or the task state does not allow this step."""


def _is_person(wh, name: str | None) -> bool:
    return bool(name) and name not in wh.associates


def claim(wh, types: list[str], user: str) -> Task | None:
    """Give the user their claimed task back, else claim the most urgent open one."""
    mine = [
        t
        for t in wh.tasks.values()
        if t.status == "IN_PROGRESS" and t.assignee == user and t.type in types
    ]
    if mine:
        return mine[0]
    open_tasks = sorted(
        (t for t in wh.tasks.values() if t.status == "OPEN" and t.type in types),
        key=lambda t: (t.priority, t.created, t.task_id),
    )
    if not open_tasks:
        return None
    task = open_tasks[0]
    task.status, task.assignee, task.started = "IN_PROGRESS", user, wh.inv.tick
    return task


def release(wh, task_id: str, user: str) -> None:
    task = _mine(wh, task_id, user)
    task.status, task.assignee, task.started = "OPEN", None, None


def expire_claims(wh) -> None:
    """Claims left unconfirmed for CLAIM_MINUTES go back to the queue."""
    limit = CLAIM_MINUTES * wh.tph // 60
    for t in wh.tasks.values():
        if (
            t.status == "IN_PROGRESS"
            and _is_person(wh, t.assignee)
            and wh.inv.tick - (t.started or 0) > limit
        ):
            t.status, t.assignee, t.started = "OPEN", None, None


def _mine(wh, task_id: str, user: str) -> Task:
    task = wh.tasks.get(task_id)
    if task is None:
        raise RFError(f"unknown task {task_id}")
    if task.status != "IN_PROGRESS" or task.assignee != user:
        raise RFError(f"{task_id} is not yours (it is {task.status.lower()})")
    return task


def instructions(wh, task: Task) -> dict:
    """What the handheld shows: a title, the steps, and what has to be scanned to confirm."""
    d = task.data
    inv = wh.inv
    base = {"task_id": task.task_id, "type": task.type, "inputs": []}
    if task.type == "RECEIVE":
        po = wh.pos[d["po"]]
        plate = next(p for p in po.asn if p["sscc"] == d["sscc"])
        item = inv.items[plate["sku"]]
        return {
            **base,
            "title": f"Receive at {po.dock}",
            "steps": [
                f"Truck {po.po_id} from {wh.suppliers[po.supplier_id].name} at {po.dock}",
                f"Plate of {plate['qty']} x {item.name} ({item.sku}), lot {plate['lot']}",
                "Count the units and note any damaged ones",
            ],
            "go_to": po.dock,
            "scan": {"kind": "plate", "label": "Scan the plate's SSCC label", "value": d["sscc"]},
            "inputs": [
                {"name": "qty", "label": "Units received", "default": plate["qty"]},
                {"name": "damaged", "label": "Damaged", "default": 0},
            ],
        }
    if task.type == "PUTAWAY":
        rows = list(inv.rows(lpn=d["sscc"]))
        if not rows:
            return {**base, "title": "Put away", "steps": ["The plate is empty"], "scan": None}
        key, qty = rows[0]
        targets = wh.putaway_target(key.sku, qty)
        target = targets[0][0] if targets else None
        return {
            **base,
            "title": "Put away",
            "steps": [
                f"Take plate {d['sscc']} from {key.location}: {qty} x {inv.items[key.sku].name}",
                *(f"{q} units to {loc}" for loc, q in targets),
            ],
            "go_to": target,
            "scan": {"kind": "location", "label": f"Scan location {target}", "value": target},
        }
    if task.type in ("REPLENISH", "REPLENISH_URGENT"):
        item = inv.items[d["sku"]]
        plates = wh._reserve_plates(d["sku"])
        room = item.pick_max - inv.qty(d["sku"], location=item.home)
        source = (
            f"from {plates[0][0].location} (plate {plates[0][0].lpn})"
            if plates
            else "no reserve stock"
        )
        return {
            **base,
            "title": "Replenish" + (" (urgent)" if task.type == "REPLENISH_URGENT" else ""),
            "steps": [
                f"{item.name} ({item.sku})",
                f"Take whole cases {source}",
                f"Fill pick face {item.home} (room for about {max(room, 0)} units)",
            ],
            "go_to": item.home,
            "scan": {
                "kind": "location",
                "label": f"Scan pick face {item.home}",
                "value": item.home,
            },
        }
    if task.type == "COUNT":
        count = wh.counts[d["count_id"]]
        return {
            **base,
            "title": "Count" + (" (recount)" if count.recount_of else ""),
            "steps": [
                f"Count every unit of {inv.items[count.sku].name} ({count.sku})",
                "Blind count: write what is on the shelf",
            ],
            "go_to": count.location,
            "scan": {
                "kind": "location",
                "label": f"Scan {count.location}",
                "value": count.location,
            },
            "inputs": [{"name": "counted", "label": "Units on the shelf", "default": None}],
        }
    if task.type == "LOAD":
        carton = wh.out.cartons.get(d["sscc"])
        door = wh.out.carriers[carton.carrier].door if carton else "?"
        return {
            **base,
            "title": f"Load onto {door}",
            "steps": [
                f"Carton {d['sscc']} in {d.get('location')}",
                f"Order {carton.order_id if carton else '?'}: load it on the trailer at {door}",
            ],
            "go_to": d.get("location"),
            "scan": {"kind": "plate", "label": "Scan the carton's SSCC", "value": d["sscc"]},
        }
    return {**base, "title": task.type, "steps": [], "scan": None}


def _matches(kind: str, expected: str, raw: str) -> bool:
    if kind == "plate":
        s = bc.parse_scan(raw)
        got = s.sscc or raw.strip().removeprefix("LPN")
        return got == expected
    return raw.strip().upper() == (expected or "").upper()


def confirm(wh, task_id: str, user: str, scan: str, values: dict | None = None) -> str:
    """Check the scan, then do the work under the user's name."""
    task = _mine(wh, task_id, user)
    info = instructions(wh, task)
    expected = info.get("scan")
    if expected and not _matches(expected["kind"], expected["value"], scan):
        raise RFError(f"Wrong scan: expected {expected['value']}, got {scan.strip()}")
    values = values or {}
    try:
        if task.type == "RECEIVE":
            result = wh.receive_plate(
                task.data["po"],
                task.data["sscc"],
                None if values.get("qty") is None else int(values["qty"]),  # None: as on the ASN
                int(values.get("damaged") or 0),
                user=user,
                task=task,
            )
        elif task.type == "PUTAWAY":
            result = wh._do_putaway(task, user)
        elif task.type in ("REPLENISH", "REPLENISH_URGENT"):
            result = wh._do_replenish(task, user)
        elif task.type == "COUNT":
            if values.get("counted") is None:
                raise RFError("enter the number of units on the shelf")
            count = wh.submit_count(task.data["count_id"], int(values["counted"]), user)
            result = {
                "MATCHED": "matches the system",
                "ADJUSTED": "small difference adjusted",
                "COUNTED": "difference: a recount was created",
                "PENDING_APPROVAL": "difference sent to a supervisor",
            }.get(count.status, count.status.lower())
        elif task.type == "LOAD":
            result = f"on {wh.out.load(task.data['sscc'], user).trip}"
        else:
            raise RFError(f"{task.type} is not done on a handheld")
    except InventoryError as err:
        raise RFError(str(err)) from err
    task.status, task.done_at, task.result = "DONE", wh.inv.tick, result
    wh.metrics[f"tasks_{task.type.lower()}"] += 1
    wh.metrics["tasks_by_people"] += 1
    return result
