"""Labels in ZPL II, the language of Zebra and most industrial thermal printers (backlog PR-30).

Same layouts as the PDF labels (wms/labels.py), at 203 dpi (8 dots per mm): item 100 x 50 mm,
location 100 x 40 mm, pallet and shipping 100 x 150 mm. GS1-128 barcodes use Code 128 with FNC1
(`>8` in ZPL) at the start and after every variable-length field, exactly as on the PDFs.

Text from the system (item names, customer addresses, notes) is cleaned before it goes into a
label: `^` and `~` start ZPL commands, so a name containing them could otherwise change or break
the printer's job (command injection). Only printable ASCII is kept.
"""

from __future__ import annotations

import datetime as dt

from wms import barcodes as bc
from wms.model import Item, Location

DOTS_PER_MM = 8


def mm(v: float) -> int:
    return round(v * DOTS_PER_MM)


def clean(text: object, limit: int = 60) -> str:
    """Printable ASCII only, without the ZPL command characters ^ and ~."""
    s = "".join(ch if 32 <= ord(ch) < 127 and ch not in "^~" else " " for ch in str(text))
    return " ".join(s.split())[:limit]


class Label:
    def __init__(self, width_mm: float, height_mm: float) -> None:
        self.parts = ["^XA", "^CI0", f"^PW{mm(width_mm)}", f"^LL{mm(height_mm)}", "^LH0,0"]

    def text(self, x: float, y: float, value: object, size: float = 3.0, bold=False) -> Label:
        h = mm(size)
        w = mm(size * (0.9 if bold else 0.75))
        self.parts.append(f"^FO{mm(x)},{mm(y)}^A0N,{h},{w}^FD{clean(value)}^FS")
        return self

    def line(self, x: float, y: float, length: float) -> Label:
        self.parts.append(f"^FO{mm(x)},{mm(y)}^GB{mm(length)},2,2^FS")
        return self

    def code128(self, x: float, y: float, data: str, height: float = 12, text=False) -> Label:
        self.parts.append(
            f"^FO{mm(x)},{mm(y)}^BY2^BCN,{mm(height)},{'Y' if text else 'N'},N,N^FD{data}^FS"
        )
        return self

    def gs1_128(self, x: float, y: float, fields: dict[str, str], height: float = 14) -> Label:
        return self.code128(x, y, gs1_data(fields), height)

    def ean13(self, x: float, y: float, gtin13: str, height: float = 12) -> Label:
        self.parts.append(f"^FO{mm(x)},{mm(y)}^BY2^BEN,{mm(height)},Y,N^FD{gtin13[:12]}^FS")
        return self

    def zpl(self) -> str:
        return "\n".join([*self.parts, "^XZ"]) + "\n"


def gs1_data(fields: dict[str, str]) -> str:
    """ZPL Code 128 data for a GS1-128 symbol: >; starts subset C, >8 is FNC1."""
    raw = bc.element_string(fields)  # fixed-length AIs first, variable ones end with GS
    return ">;>8" + raw.replace(bc.GS, ">8")


def item_labels(items: list[Item]) -> str:
    out = []
    for item in items:
        lab = Label(100, 50)
        lab.text(4, 3, item.name, 3.5, bold=True)
        lab.text(4, 8.5, f"SKU {item.sku}  home {item.home}  {item.category}", 2.4)
        lab.ean13(4, 14, item.gtin, 14)
        fields = {"01": item.case_gtin, "30": str(item.case_qty)}
        lab.gs1_128(48, 14, fields, 12)
        lab.text(48, 28, bc.element_string(fields, human=True), 2.2)
        lab.text(48, 32, f"Case of {item.case_qty}", 2.4)
        if item.shelf_life_days:
            lab.text(4, 43, f"Expiry-controlled ({item.shelf_life_days} days), pick FEFO", 2.4)
        out.append(lab.zpl())
    return "".join(out)


def location_labels(locations: list[Location]) -> str:
    out = []
    for loc in locations:
        lab = Label(100, 40)
        lab.text(4, 3, loc.code, 8, bold=True)
        detail = loc.type.value + (f" level {loc.level}" if loc.level else "")
        lab.text(4, 13, detail + (f" item {loc.sku}" if loc.sku else ""), 2.4)
        lab.code128(4, 19, clean(loc.code), 14)
        lab.text(78, 8, "check", 2.4)
        lab.text(76, 14, loc.check, 10, bold=True)
        out.append(lab.zpl())
    return "".join(out)


def pallet_label(plate: dict, item: Item, supplier: str, ship_to: str = "Warehouse AI DC-1") -> str:
    lab = Label(100, 150)
    lab.text(4, 4, f"FROM {supplier}", 3, bold=True)
    lab.text(4, 9, f"TO   {ship_to}", 3, bold=True)
    lab.line(4, 14, 92)
    lab.text(4, 17, item.name, 3.6, bold=True)
    lab.text(4, 23, f"SKU {item.sku}", 2.6)
    lab.text(4, 29, "CONTENT", 2.2)
    lab.text(4, 32, item.case_gtin, 3.2, bold=True)
    lab.text(52, 29, "COUNT (units)", 2.2)
    lab.text(52, 32, plate["qty"], 3.2, bold=True)
    expiry = plate.get("expiry")
    if isinstance(expiry, str):
        expiry = dt.date.fromisoformat(expiry)
    lab.text(4, 38, "BEST BEFORE", 2.2)
    lab.text(4, 41, expiry.strftime("%d.%m.%Y") if expiry else "-", 3.2, bold=True)
    lab.text(52, 38, "BATCH / LOT", 2.2)
    lab.text(52, 41, plate.get("lot") or "-", 3.2, bold=True)
    lab.line(4, 47, 92)
    content = {"02": item.case_gtin, "37": str(plate["qty"])}
    if expiry:
        content["17"] = bc.yymmdd(expiry)
    if plate.get("lot"):
        content["10"] = clean(plate["lot"], 20)
    lab.gs1_128(6, 52, content, 20)
    lab.text(6, 75, bc.element_string(content, human=True), 2.6)
    lab.gs1_128(6, 100, {"00": plate["sscc"]}, 25)
    lab.text(6, 128, f"(00) {plate['sscc']}", 3.8, bold=True)
    lab.text(6, 136, "SSCC", 2.6)
    return lab.zpl()


def shipping_label(
    carton: dict, customer: dict, carrier: dict, ship_from: str = "Warehouse AI DC-1, Lahore"
) -> str:
    lab = Label(100, 150)
    lab.text(4, 3, f"FROM {ship_from}", 2.6)
    lab.line(4, 8, 92)
    lab.text(4, 10, "SHIP TO", 2.2)
    lab.text(4, 14, customer["name"], 4, bold=True)
    lab.text(4, 20, customer["address"], 3.2)
    lab.text(4, 26, f"{customer['city']}  {customer['postal_code']}", 4, bold=True)
    lab.line(4, 33, 92)
    lab.text(4, 36, carrier["name"], 3.4, bold=True)
    lab.text(4, 41, f"{carrier['service'].upper()}  trip {carton.get('trip') or '-'}", 2.8)
    lab.text(64, 36, f"CARTON {carton['seq']} / {carton['of']}", 3, bold=True)
    lab.text(64, 41, f"{carton['scale_kg']:.2f} kg  size {carton['size']}", 2.8)
    lab.code128(6, 47, clean(carton["tracking"]), 16)
    lab.text(6, 65, f"TRACKING {carton['tracking']}", 3, bold=True)
    lab.text(64, 65, f"ORDER {carton['order_id']}", 2.6)
    lab.line(4, 71, 92)
    lab.gs1_128(6, 75, {"420": clean(customer["postal_code"], 20)}, 14)
    lab.text(6, 91, f"(420) {customer['postal_code']}  SHIP TO POSTAL CODE", 2.6)
    weight = {"00": carton["sscc"], "3301": f"{round(carton['scale_kg'] * 10):06d}"}
    lab.gs1_128(6, 100, weight, 24)
    lab.text(6, 127, f"(00) {carton['sscc']}  (3301) {weight['3301']}", 3.2, bold=True)
    lab.text(6, 136, "SSCC / GROSS WEIGHT", 2.6)
    return lab.zpl()
