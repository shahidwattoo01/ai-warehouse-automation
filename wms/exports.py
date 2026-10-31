"""Exports for people and other systems (backlog PR-30): CSV files and printable PDFs.

CSV cells that start with = + - @ (or a tab / carriage return) are prefixed with an apostrophe:
spreadsheet programs would otherwise run them as formulas (CSV / formula injection), and item
names, notes and customer names come from outside the warehouse.
"""

from __future__ import annotations

import csv
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> object:
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def to_csv(rows: list[dict], columns: list[str]) -> str:
    """Rows as CSV with the given columns (missing values empty), Excel-friendly UTF-8 BOM."""
    buf = io.StringIO()
    buf.write("﻿")
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([safe_cell("" if row.get(c) is None else row.get(c)) for c in columns])
    return buf.getvalue()


def _table(header: list[str], rows: list[list], widths: list[float]) -> Table:
    t = Table([header, *rows], colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t


def _doc(title: str, lines: list[str], table: Table, sign: list[str]) -> bytes:
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm,
        bottomMargin=15 * mm, title=title,
    )  # fmt: skip
    story = [Paragraph(title, styles["Title"])]
    story += [Paragraph(line, styles["Normal"]) for line in lines]
    story += [Spacer(1, 5 * mm), table, Spacer(1, 12 * mm)]
    story += [Paragraph(s, styles["Normal"]) for s in sign]
    doc.build(story)
    return buf.getvalue()


def manifest_pdf(trip: dict, rows: list[dict]) -> bytes:
    """Driver's manifest of a truck: every carton with tracking number, order and consignee."""
    table = _table(
        ["#", "Tracking", "SSCC", "Order", "Consignee", "City", "Units", "kg"],
        [
            [
                i,
                r["tracking"],
                r["sscc"],
                r["order_id"],
                (r.get("customer") or "")[:26],
                r.get("city") or "",
                r["units"],
                f"{r['weight_kg']:.2f}",
            ]
            for i, r in enumerate(rows, start=1)
        ],  # fmt: skip
        [8, 28, 36, 16, 40, 22, 11, 14],
    )
    total = sum(r["weight_kg"] for r in rows)
    return _doc(
        f"Manifest {trip['trip_id']}",
        [
            f"<b>{trip['carrier_name']}</b> · {trip['service']} · door {trip['door']}",
            f"Departure {trip['departs_at']} · {len(rows)} cartons · {total:.1f} kg",
        ],
        table,
        [
            "Loaded by (dock): ______________________",
            "Received by (driver): ______________________",
        ],
    )


def count_sheet_pdf(counts: list[dict], printed_at: str) -> bytes:
    """Blind count sheet: locations and items to count, with no system quantities on it."""
    table = _table(
        ["Count", "Location", "Check", "SKU", "Item", "Counted"],
        [
            [
                c["count_id"],
                c["location"],
                c.get("check", ""),
                c["sku"],
                (c.get("item") or "")[:34],
                "",
            ]
            for c in counts
        ],  # fmt: skip
        [26, 26, 12, 26, 60, 24],
    )
    return _doc(
        "Cycle count sheet",
        [
            f"Printed {printed_at} · {len(counts)} locations · "
            "blind count: write what is on the shelf"
        ],
        table,
        ["Counted by: ______________________   Date / time: ______________"],
    )
