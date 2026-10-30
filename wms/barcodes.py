"""GS1 identifiers and barcodes: the numbering and symbols used on real warehouse labels.

* GTIN-13 (EAN-13 barcode): identifies a trade item (one unit). GTIN-14: a case of units.
* SSCC-18: identifies one logistic unit (a pallet or case on the move), our license plate (LPN).
* GS1-128: a Code 128 barcode with Application Identifiers (AIs), e.g.
  (01) GTIN · (10) lot · (17) expiry YYMMDD · (21) serial · (30) quantity · (00) SSCC.

Every GS1 key ends with a mod-10 check digit, so a mistyped or misread number is rejected.
`parse_scan` accepts what a handheld scanner sends: GS1 element strings (with FNC1 / group
separators or in bracketed human-readable form), plain GTINs, SSCCs, location and LPN labels.

Company prefix 0614141 is the fictitious prefix GS1 uses in its own examples.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

COMPANY_PREFIX = "0614141"  # GS1's example prefix (7 digits): never a real company
GS = "\x1d"  # group separator: ends a variable-length field in a raw GS1 scan
FNC1 = "\xf1"  # FNC1 as reportlab's Code 128 encoder expects it

# Application Identifiers used here: (fixed length or None for variable, max length, name)
AIS: dict[str, tuple[int | None, int, str]] = {
    "00": (18, 18, "sscc"),
    "01": (14, 14, "gtin"),
    "02": (14, 14, "content_gtin"),
    "10": (None, 20, "lot"),
    "11": (6, 6, "production_date"),
    "17": (6, 6, "expiry"),
    "21": (None, 20, "serial"),
    "30": (None, 8, "quantity"),
    "37": (None, 8, "count"),
}


def check_digit(digits: str) -> str:
    """GS1 mod-10: weights 3,1,3,1... from the right, check = (10 - sum mod 10) mod 10."""
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digits)))
    return str((10 - total % 10) % 10)


def valid(key: str) -> bool:
    """True for a GS1 key (GTIN-8/12/13/14, SSCC-18 ...) with a correct check digit."""
    return key.isdigit() and len(key) >= 8 and check_digit(key[:-1]) == key[-1]


def gtin13(item_reference: int) -> str:
    """GTIN-13 of a unit: company prefix (7) + item reference (5) + check digit."""
    body = f"{COMPANY_PREFIX}{item_reference:05d}"
    return body + check_digit(body)


def gtin14(gtin_13: str, indicator: int = 1) -> str:
    """GTIN-14 of a case of that unit: packaging indicator + first 12 digits + new check digit."""
    body = f"{indicator}{gtin_13[:12]}"
    return body + check_digit(body)


def as_gtin14(gtin: str) -> str:
    return gtin.zfill(14)


def sscc(serial_reference: int, extension: int = 0) -> str:
    """SSCC-18: extension digit + company prefix (7) + serial reference (9) + check digit."""
    body = f"{extension}{COMPANY_PREFIX}{serial_reference:09d}"
    return body + check_digit(body)


def yymmdd(date: dt.date) -> str:
    return date.strftime("%y%m%d")


def from_yymmdd(text: str) -> dt.date:
    """GS1 dates: YY 51-99 -> 19xx, else 20xx; day 00 means the last day of the month."""
    yy, mm, dd = int(text[:2]), int(text[2:4]), int(text[4:6])
    year = 1900 + yy if yy >= 51 else 2000 + yy
    if dd == 0:
        nxt = dt.date(year + mm // 12, mm % 12 + 1, 1)
        return nxt - dt.timedelta(days=1)
    return dt.date(year, mm, dd)


def element_string(fields: dict[str, str], human: bool = False) -> str:
    """GS1-128 data: fixed-length AIs first, variable ones separated by GS (or "(AI)" text)."""
    fixed = [(ai, v) for ai, v in fields.items() if AIS[ai][0] is not None]
    variable = [(ai, v) for ai, v in fields.items() if AIS[ai][0] is None]
    parts = fixed + variable
    if human:
        return "".join(f"({ai}){v}" for ai, v in parts)
    out = ""
    for i, (ai, v) in enumerate(parts):
        out += ai + v
        if AIS[ai][0] is None and i < len(parts) - 1:
            out += GS
    return out


def gs1_item_label(
    gtin: str,
    lot: str | None = None,
    expiry: dt.date | None = None,
    serial: str | None = None,
    quantity: int | None = None,
) -> dict[str, str]:
    fields = {"01": as_gtin14(gtin)}
    if expiry:
        fields["17"] = yymmdd(expiry)
    if lot:
        fields["10"] = lot
    if serial:
        fields["21"] = serial
    if quantity:
        fields["30"] = str(quantity)
    return fields


@dataclass
class Scan:
    """What a scanned barcode means. kind: gs1 | gtin | sscc | location | lpn | unknown."""

    raw: str
    kind: str
    gtin: str | None = None
    sscc: str | None = None
    lot: str | None = None
    expiry: dt.date | None = None
    serial: str | None = None
    quantity: int | None = None
    code: str | None = None  # location or LPN code
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v not in (None, [])}
        if self.expiry:
            d["expiry"] = self.expiry.isoformat()
        return d


LOCATION_CODE = re.compile(
    r"^(?:[A-D]-\d{2}-\d{2}-\d|DOCK-\d{2}|STAGE-\d{2}|PACK_\d|QA-\d{2}|RET-\d{2})$"
)
LPN_CODE = re.compile(r"^LPN\d{18}$")


def _parse_element_string(data: str) -> tuple[dict[str, str], list[str]]:
    fields: dict[str, str] = {}
    errors: list[str] = []
    i = 0
    while i < len(data):
        if data[i] in (GS, FNC1):
            i += 1
            continue
        ai = data[i : i + 2]
        if ai not in AIS:
            errors.append(f"unknown application identifier at '{data[i : i + 6]}'")
            break
        fixed, max_len, _ = AIS[ai]
        i += 2
        if fixed:
            fields[ai] = data[i : i + fixed]
            i += fixed
        else:
            end = data.find(GS, i)
            end = len(data) if end == -1 else end
            fields[ai] = data[i : min(end, i + max_len)]
            i = end
    return fields, errors


def parse_scan(raw: str) -> Scan:
    """Decode what a scanner sends (keyboard-wedge text, possibly with ]C1 / ]d2 prefixes)."""
    text = raw.strip().replace("␝", GS)
    for prefix in ("]C1", "]d2", "]Q3", "]e0"):  # symbology identifiers some scanners add
        text = text.removeprefix(prefix)
    if text.startswith("("):  # bracketed human-readable GS1: (01)...(17)...(10)...
        pairs = re.findall(r"\((\d{2})\)([^(]*)", text)
        if pairs:  # variable-length values end with a group separator, as in a raw scan
            text = "".join(
                ai + v + (GS if AIS.get(ai, (1,))[0] is None else "") for ai, v in pairs
            ).rstrip(GS)
    if LOCATION_CODE.match(text):
        return Scan(raw, "location", code=text)
    if LPN_CODE.match(text):
        s = text[3:]
        return Scan(
            raw, "lpn", sscc=s, code=text, errors=[] if valid(s) else ["bad SSCC check digit"]
        )
    if text.isdigit() and len(text) in (8, 12, 13, 14):
        return Scan(
            raw, "gtin", gtin=as_gtin14(text), errors=[] if valid(text) else ["bad check digit"]
        )
    if text.isdigit() and len(text) == 18:
        return Scan(raw, "sscc", sscc=text, errors=[] if valid(text) else ["bad check digit"])
    if text[:2] in AIS:
        fields, errors = _parse_element_string(text)
        scan = Scan(raw, "gs1", errors=errors)
        scan.gtin = fields.get("01") or fields.get("02")
        scan.sscc = fields.get("00")
        scan.lot = fields.get("10")
        scan.serial = fields.get("21")
        if "17" in fields:
            try:
                scan.expiry = from_yymmdd(fields["17"])
            except ValueError:
                scan.errors.append("bad expiry date")
        qty = fields.get("30") or fields.get("37")
        scan.quantity = int(qty) if qty and qty.isdigit() else None
        for key in (scan.gtin, scan.sscc):
            if key and not valid(key):
                scan.errors.append(f"bad check digit in {key}")
        return scan
    return Scan(raw, "unknown", errors=["not a recognised barcode"])
