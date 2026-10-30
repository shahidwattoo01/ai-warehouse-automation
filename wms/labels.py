"""Printable labels (PDF, sized for 4-inch thermal label printers) and screen barcodes (SVG).

* Item label (100 x 50 mm): EAN-13 of the unit and GS1-128 of the case (GTIN-14 + quantity).
* Location label (100 x 40 mm): Code 128 of the location code, with large check digits that a
  picker reads out to confirm being at the right place.
* Pallet label (100 x 150 mm, GS1 logistic label layout): SSCC barcode (00), then content
  (02 GTIN, 37 count, 17 expiry, 10 lot) for one-item pallets.
* Shipping label (100 x 150 mm): ship-from / ship-to, carrier and service, the carrier's
  tracking barcode (Code 128), ship-to postal code (420) for sortation, and the carton's SSCC
  (00) with its gross weight (3301).
"""

from __future__ import annotations

import io

from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from wms import barcodes as bc
from wms.model import Item, Location

FONT, BOLD = "Helvetica", "Helvetica-Bold"


def gs1_128_value(fields: dict[str, str]) -> str:
    """Data for a GS1-128 symbol: FNC1 first, FNC1 also ending variable-length fields."""
    return bc.FNC1 + bc.element_string(fields).replace(bc.GS, bc.FNC1)


def drawing(kind: str, value: str, width_mm: float, height_mm: float, human: bool = False):
    """A barcode drawing scaled to a box. kind: ean13 | code128 | gs1-128 | datamatrix."""
    if kind == "ean13":
        d = createBarcodeDrawing(
            "EAN13", value=value[:12], barHeight=height_mm * mm, humanReadable=human
        )
    elif kind == "datamatrix":
        d = createBarcodeDrawing("ECC200DataMatrix", value=value)
    else:
        d = createBarcodeDrawing(
            "Code128",
            value=value,
            barHeight=height_mm * mm,
            humanReadable=human,
            quiet=False,
            barWidth=0.33 * mm,
        )
    scale = min(width_mm * mm / d.width, 1.6) if d.width else 1
    d.scale(scale, 1 if kind != "datamatrix" else scale)
    d.width *= scale
    if kind == "datamatrix":
        d.height *= scale
    return d


def barcode_svg(kind: str, value: str) -> str:
    """An SVG barcode for the screen (the browser shows it; scanners read it from the screen)."""
    if kind == "gs1-128":
        fields = _fields_from_text(value)
        if not fields:
            raise ValueError("not a GS1 element string")
        value = gs1_128_value(fields)
    d = drawing(kind, value, 80, 15, human=False)
    return renderSVG.drawToString(d)


def _fields_from_text(text: str) -> dict[str, str]:
    scan = bc.parse_scan(text)
    fields = {}
    if scan.sscc:
        fields["00"] = scan.sscc
    if scan.gtin:
        fields["01"] = scan.gtin
    if scan.expiry:
        fields["17"] = bc.yymmdd(scan.expiry)
    if scan.lot:
        fields["10"] = scan.lot
    if scan.serial:
        fields["21"] = scan.serial
    if scan.quantity:
        fields["30"] = str(scan.quantity)
    return fields


def _page(c: canvas.Canvas, w: float, h: float) -> None:
    c.setPageSize((w * mm, h * mm))


def _text(c, x, y, text, size=9, font=FONT):
    c.setFont(font, size)
    c.drawString(x * mm, y * mm, str(text))


def item_labels(items: list[Item]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for item in items:
        _page(c, 100, 50)
        _text(c, 4, 44, item.name[:42], 10, BOLD)
        _text(c, 4, 39.5, f"SKU {item.sku}   ·   home {item.home}   ·   {item.category}", 7)
        renderPDF.draw(drawing("ean13", item.gtin, 40, 14, human=True), c, 4 * mm, 18 * mm)
        _text(c, 4, 14, f"Unit  GTIN {item.gtin}", 7)
        fields = {"01": item.case_gtin, "30": str(item.case_qty)}
        renderPDF.draw(drawing("gs1-128", gs1_128_value(fields), 50, 12), c, 47 * mm, 20 * mm)
        _text(c, 47, 15.5, bc.element_string(fields, human=True), 7)
        _text(c, 47, 12, f"Case of {item.case_qty}", 7)
        if item.shelf_life_days:
            _text(c, 4, 5, f"Expiry-controlled ({item.shelf_life_days} days) · pick FEFO", 7)
        if item.serial_controlled:
            _text(c, 60, 5, "Serial numbers tracked", 7)
        c.showPage()
    c.save()
    return buf.getvalue()


def location_labels(locations: list[Location]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for loc in locations:
        _page(c, 100, 40)
        _text(c, 4, 31, loc.code, 22, BOLD)
        _text(
            c,
            4,
            25.5,
            f"{loc.type.value}"
            + (f" · level {loc.level}" if loc.level else "")
            + (f" · item {loc.sku}" if loc.sku else ""),
            7,
        )
        renderPDF.draw(drawing("code128", loc.code, 62, 13), c, 4 * mm, 6 * mm)
        _text(c, 78, 22, "check", 7)
        _text(c, 76, 9, loc.check, 26, BOLD)
        c.showPage()
    c.save()
    return buf.getvalue()


def pallet_label(
    plate: dict, item: Item, supplier: str, ship_to: str = "Warehouse AI DC-1"
) -> bytes:
    """GS1 logistic label for a license plate: plate = {sscc, sku, qty, lot, expiry}."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    _page(c, 100, 150)
    _text(c, 4, 143, f"FROM  {supplier}", 8, BOLD)
    _text(c, 4, 138, f"TO    {ship_to}", 8, BOLD)
    c.line(4 * mm, 135 * mm, 96 * mm, 135 * mm)
    _text(c, 4, 129, item.name[:40], 10, BOLD)
    _text(c, 4, 124, f"SKU {item.sku}", 8)
    _text(c, 4, 118, "CONTENT", 7)
    _text(c, 4, 113, item.case_gtin, 9, BOLD)
    _text(c, 50, 118, "COUNT (units)", 7)
    _text(c, 50, 113, plate["qty"], 9, BOLD)
    _text(c, 4, 107, "BEST BEFORE", 7)
    expiry = plate.get("expiry")
    _text(c, 4, 102, expiry.strftime("%d.%m.%Y") if expiry else "-", 9, BOLD)
    _text(c, 50, 107, "BATCH / LOT", 7)
    _text(c, 50, 102, plate.get("lot") or "-", 9, BOLD)
    c.line(4 * mm, 98 * mm, 96 * mm, 98 * mm)
    content = {"02": item.case_gtin, "37": str(plate["qty"])}
    if expiry:
        content["17"] = bc.yymmdd(expiry)
    if plate.get("lot"):
        content["10"] = plate["lot"]
    renderPDF.draw(drawing("gs1-128", gs1_128_value(content), 88, 20), c, 6 * mm, 66 * mm)
    _text(c, 6, 61, bc.element_string(content, human=True), 8)
    renderPDF.draw(
        drawing("gs1-128", gs1_128_value({"00": plate["sscc"]}), 88, 25), c, 6 * mm, 25 * mm
    )
    _text(c, 6, 19, f"(00) {plate['sscc']}", 11, BOLD)
    _text(c, 6, 8, "SSCC", 8)
    c.showPage()
    c.save()
    return buf.getvalue()


def shipping_label(
    carton: dict, customer: dict, carrier: dict, ship_from: str = "Warehouse AI DC-1, Lahore"
) -> bytes:
    """carton: sscc, tracking, order_id, seq, of, scale_kg, size, trip."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    _page(c, 100, 150)
    _text(c, 4, 144, "FROM", 7)
    _text(c, 14, 144, ship_from, 8)
    c.line(4 * mm, 141 * mm, 96 * mm, 141 * mm)
    _text(c, 4, 136, "SHIP TO", 7)
    _text(c, 4, 130, customer["name"][:34], 12, BOLD)
    _text(c, 4, 124, customer["address"][:40], 10)
    _text(c, 4, 118, f"{customer['city']}  {customer['postal_code']}", 12, BOLD)
    c.line(4 * mm, 114 * mm, 96 * mm, 114 * mm)
    _text(c, 4, 108, carrier["name"], 10, BOLD)
    _text(c, 4, 103, f"{carrier['service'].upper()}   trip {carton.get('trip') or '-'}", 9)
    _text(c, 66, 108, f"CARTON {carton['seq']} / {carton['of']}", 9, BOLD)
    _text(c, 66, 103, f"{carton['scale_kg']:.2f} kg   size {carton['size']}", 9)
    renderPDF.draw(drawing("code128", carton["tracking"], 88, 16), c, 6 * mm, 82 * mm)
    _text(c, 6, 77, f"TRACKING  {carton['tracking']}", 9, BOLD)
    _text(c, 66, 77, f"ORDER {carton['order_id']}", 8)
    c.line(4 * mm, 74 * mm, 96 * mm, 74 * mm)
    route = {"420": customer["postal_code"]}
    renderPDF.draw(drawing("gs1-128", gs1_128_value(route), 60, 14), c, 6 * mm, 56 * mm)
    _text(c, 6, 51, f"(420) {customer['postal_code']}   SHIP TO POSTAL CODE", 8)
    weight = {"00": carton["sscc"], "3301": f"{round(carton['scale_kg'] * 10):06d}"}
    renderPDF.draw(drawing("gs1-128", gs1_128_value(weight), 88, 24), c, 6 * mm, 20 * mm)
    _text(c, 6, 14, f"(00) {carton['sscc']}  (3301) {weight['3301']}", 10, BOLD)
    _text(c, 6, 6, "SSCC / GROSS WEIGHT", 8)
    c.showPage()
    c.save()
    return buf.getvalue()
