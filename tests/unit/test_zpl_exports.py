"""ZPL labels for thermal printers and the CSV / PDF exports."""

import datetime as dt

from wms import barcodes as bc
from wms import exports, zpl
from wms.model import Item, Location, LocationType

ITEM = Item(
    "P-A-05-12", bc.gtin13(7), bc.gtin14(bc.gtin13(7)), "Tea ^XZ~JR caddy", "Grocery", "SUP-01",
    2.0, 0.5, case_qty=6, pallet_cases=4, home="A-05-12-1", pick_min=6, pick_max=18,
    shelf_life_days=120,
)  # fmt: skip


def test_text_cannot_inject_printer_commands():
    assert "^" not in zpl.clean("Tea ^XZ^PQ99 ~JR") and "~" not in zpl.clean("~JA")
    label = zpl.item_labels([ITEM])
    assert label.count("^XA") == 1 and label.count("^XZ") == 1  # the name did not end the job
    assert "Tea  XZ JR caddy"[:3] in label and "^PQ" not in label


def test_gs1_128_uses_fnc1_at_the_start_and_after_variable_fields():
    data = zpl.gs1_data({"01": ITEM.case_gtin, "10": "L1", "17": "270131"})
    assert data.startswith(">;>8")
    assert data == ">;>8" + f"01{ITEM.case_gtin}17270131" + "10L1"  # fixed fields first
    assert zpl.gs1_data({"10": "L1", "21": "SN9"}) == ">;>810L1>821SN9"  # FNC1 between variable


def test_every_label_kind_is_a_complete_zpl_job_at_203_dpi():
    loc = Location("A-05-12-1", LocationType.PICK, "A", 12, 4, 1, sku=ITEM.sku, check="37")
    plate = {"sscc": bc.sscc(5), "qty": 24, "lot": "L1", "expiry": dt.date(2027, 1, 31)}
    carton = {"sscc": bc.sscc(6), "tracking": "SWX0000000001", "order_id": "000001", "seq": 1,
              "of": 2, "scale_kg": 2.35, "size": "M", "trip": "EXP-0907-1200"}  # fmt: skip
    customer = {"name": "Cedar Mart 01", "address": "Plot 1, Block A", "city": "Lahore",
                "postal_code": "54000"}  # fmt: skip
    carrier = {"name": "Swiftline Couriers", "service": "Express"}
    jobs = {
        "item": zpl.item_labels([ITEM]),
        "location": zpl.location_labels([loc, loc]),
        "pallet": zpl.pallet_label(plate, ITEM, "Harvest Foods"),
        "shipping": zpl.shipping_label(carton, customer, carrier),
    }
    assert jobs["location"].count("^XA") == 2  # one job per label
    assert "^PW800" in jobs["item"] and "^LL400" in jobs["item"]  # 100 x 50 mm at 8 dots/mm
    assert "^LL1200" in jobs["shipping"]
    assert "^BEN" in jobs["item"]  # EAN-13 of the unit
    assert f">;>800{plate['sscc']}" in jobs["pallet"]  # SSCC as GS1-128
    assert ">8420" in jobs["shipping"] and f"00{carton['sscc']}3301000024" in jobs["shipping"]


def test_csv_neutralises_formulas_and_keeps_columns():
    rows = [{"sku": "P-1", "note": '=HYPERLINK("http://x")'}, {"sku": "+1", "note": None}]
    text = exports.to_csv(rows, ["sku", "note"])
    assert text.startswith("﻿sku,note")
    assert "'=HYPERLINK" in text and "'+1" in text  # spreadsheets show them as text
    assert text.splitlines()[2].endswith(",")  # missing value -> empty cell


def test_manifest_and_count_sheet_pdfs():
    trip = {"trip_id": "EXP-0907-1200", "carrier_name": "Swiftline Couriers", "service": "Express",
            "door": "SHIP-01", "departs_at": "Mon 07 Sep 12:00"}  # fmt: skip
    rows = [{"tracking": "SWX1", "sscc": bc.sscc(1), "order_id": "000001", "customer": "Cedar",
             "city": "Lahore", "units": 2, "weight_kg": 1.2}]  # fmt: skip
    assert exports.manifest_pdf(trip, rows).startswith(b"%PDF")
    sheet = exports.count_sheet_pdf(
        [
            {
                "count_id": "CNT-1",
                "location": "A-05-12-1",
                "check": "37",
                "sku": "P-1",
                "item": "Tea",
            }
        ],
        "Mon 07 Sep 10:00",
    )
    assert sheet.startswith(b"%PDF")
