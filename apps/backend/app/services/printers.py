"""Network label printers (backlog PR-30): ZPL sent to a printer's raw port (9100, "JetDirect").

Printers are configured by name only (LABEL_PRINTERS=pack1=10.0.0.21:9100,dock=10.0.0.22), so the
API never connects to an address taken from a request (no server-side request forgery).
"""

from __future__ import annotations

import socket

from app.core.config import get_settings


class PrinterError(RuntimeError):
    pass


def printers() -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    for entry in get_settings().label_printers.split(","):
        if "=" not in entry:
            continue
        name, address = (part.strip() for part in entry.split("=", 1))
        host, _, port = address.partition(":")
        if name and host:
            out[name] = (host, int(port or 9100))
    return out


def send(name: str, zpl: str, copies: int = 1, timeout: float = 5.0) -> int:
    """Send the labels; returns the number of bytes sent."""
    target = printers().get(name)
    if target is None:
        raise PrinterError(f"unknown printer {name}")
    data = (zpl * copies).encode("ascii", "replace")
    try:
        with socket.create_connection(target, timeout=timeout) as conn:
            conn.sendall(data)
    except OSError as err:
        raise PrinterError(
            f"printer {name} ({target[0]}:{target[1]}) did not answer: {err}"
        ) from err
    return len(data)
