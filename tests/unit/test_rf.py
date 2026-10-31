"""Handheld (RF) task-directed work: claim the next task, follow the instructions, confirm with a
scan; wrong scans are refused; unconfirmed claims go back to the queue."""

import pytest

from simulation.environment.engine import SimulationEngine
from wms import rf
from wms.model import TxnType
from wms.operations import POLine


@pytest.fixture()
def wh():
    e = SimulationEngine(seed=5, overrides={"layout": "default", "inventory_model": "wms"})
    w = e.inventory.wms
    for t in w.cfg["auto_tasks"]:
        w.cfg["auto_tasks"][t] = False  # people do the work here
    w.tasks.clear()
    return w


def test_receive_then_put_away_by_scanning(wh):
    sku = next(iter(wh.inv.items))
    item = wh.inv.items[sku]
    po = wh.create_po(item.supplier_id, [POLine(sku, item.case_qty * item.pallet_cases)])
    po.eta = wh.inv.tick
    wh._trucks()  # the truck arrives at a dock: one RECEIVE task per plate
    task = rf.claim(wh, ["RECEIVE"], "sara")
    info = rf.instructions(wh, task)
    assert info["go_to"] == po.dock and info["scan"]["kind"] == "plate"
    with pytest.raises(rf.RFError, match="Wrong scan"):
        rf.confirm(wh, task.task_id, "sara", "LPN000000000000000000")
    plate = info["scan"]["value"]
    result = rf.confirm(wh, task.task_id, "sara", "LPN" + plate, {"qty": None, "damaged": 1})
    assert "1 damaged" in result and task.status == "DONE"
    put = rf.claim(wh, ["PUTAWAY"], "sara")
    target = rf.instructions(wh, put)["go_to"]
    with pytest.raises(rf.RFError):
        rf.confirm(wh, put.task_id, "sara", "A-99-99-9")
    rf.confirm(wh, put.task_id, "sara", target.lower())  # case-insensitive location scan
    moves = [t for t in wh.inv.ledger if t.type == TxnType.PUTAWAY and t.user == "sara"]
    assert moves and moves[0].to_loc == target


def test_blind_count_on_a_handheld(wh):
    item = next(iter(wh.inv.items.values()))
    count = wh.create_count(item.home, item.sku, "MANUAL")
    task = rf.claim(wh, ["COUNT"], "omar")
    info = rf.instructions(wh, task)
    assert info["go_to"] == item.home and "expected" not in str(info)  # nothing gives it away
    with pytest.raises(rf.RFError, match="units"):
        rf.confirm(wh, task.task_id, "omar", item.home)
    shelf = sum(q for k, q in wh.inv.rows(sku=item.sku, location=item.home, physical=True))
    assert (
        rf.confirm(wh, task.task_id, "omar", item.home, {"counted": shelf}) == "matches the system"
    )
    assert count.counter == "omar" and count.status == "MATCHED"


def test_a_claim_is_kept_for_its_person_and_expires(wh):
    item = next(iter(wh.inv.items.values()))
    wh.create_count(item.home, item.sku, "MANUAL")
    task = rf.claim(wh, ["COUNT"], "sara")
    assert rf.claim(wh, ["COUNT"], "omar") is None  # the only count is taken
    assert rf.claim(wh, ["COUNT"], "sara") is task  # sara gets hers back
    with pytest.raises(rf.RFError, match="not yours"):
        rf.confirm(wh, task.task_id, "omar", item.home, {"counted": 1})
    wh.inv.tick += rf.CLAIM_MINUTES * wh.tph // 60 + 1
    rf.expire_claims(wh)
    assert task.status == "OPEN" and rf.claim(wh, ["COUNT"], "omar") is task
    rf.release(wh, task.task_id, "omar")
    assert task.status == "OPEN" and task.assignee is None
