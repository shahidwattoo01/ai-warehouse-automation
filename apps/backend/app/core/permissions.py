"""Roles and permissions (role-based access control).

A permission is one specific right ("wms:adjust"); a role is a named set of permissions. The
backend checks the permission on every endpoint (app/core/auth.py `require`); the frontend uses
the same list only to show each role its own menu, dashboard and buttons.

The table is in code so it is versioned, reviewed and tested (apps/backend/tests/test_auth.py
checks every role against the endpoints).
"""

from __future__ import annotations

PERMISSIONS: dict[str, str] = {
    "dashboard:view": "See the live dashboard, robots, orders and the 3D view",
    "analytics:view": "See analytics, experiments and reports",
    "simulation:control": "Start, pause, reset the simulation; change speed and strategy",
    "robots:command": "Pause, resume and reroute robots; close and open aisles",
    "safety:reset": "Release and reset an emergency stop; change slow zones (anyone may press it)",
    "alerts:handle": "Acknowledge and resolve alerts",
    "alerts:configure": "Change alert rules, thresholds and notifications",
    "orders:create": "Create orders",
    "orders:assign": "Assign orders to robots; switch manual / automatic assignment",
    "orders:manage": "Hold, release, cancel and partly ship customer orders",
    "vision:use": "Run object detection on camera images",
    "copilot:use": "Ask the copilot and the knowledge assistant",
    "copilot:approve": "Approve copilot actions that change the warehouse",
    "wms:view": "See inventory, locations, purchase orders, counts and the ledger",
    "wms:receive": "Receive trucks and put away pallets",
    "wms:move": "Move stock between locations",
    "wms:adjust": "Adjust stock (with a reason code)",
    "wms:hold": "Hold and release stock",
    "wms:count": "Create and submit cycle counts",
    "wms:count_approve": "Approve or reject count differences (supervisor)",
    "wms:ship": "Pack, check and load cartons onto carrier trucks",
    "wms:settings": "Choose which work the associates do automatically; order release mode",
    "users:manage": "Create users, change roles, disable accounts, reset passwords",
}

_READ = {"dashboard:view", "analytics:view", "wms:view"}

ROLES: dict[str, dict] = {
    "admin": {
        "label": "Administrator",
        "home": "/admin/users",
        "permissions": set(PERMISSIONS),
    },
    "supervisor": {
        "label": "Shift supervisor",
        "home": "/dashboard",
        "permissions": set(PERMISSIONS) - {"users:manage"},
    },
    "operator": {
        "label": "Control-room operator",
        "home": "/dashboard",
        "permissions": _READ
        | {
            "simulation:control",
            "robots:command",
            "safety:reset",
            "alerts:handle",
            "orders:create",
            "orders:assign",
            "orders:manage",
            "vision:use",
            "copilot:use",
            "copilot:approve",
        },
    },
    "inventory_clerk": {
        "label": "Inventory clerk",
        "home": "/inventory",
        "permissions": _READ
        | {
            "copilot:use",
            "wms:receive",
            "wms:move",
            "wms:adjust",
            "wms:hold",
            "wms:count",
            "wms:ship",
            "alerts:handle",
        },
    },
    "viewer": {
        "label": "Viewer (read only)",
        "home": "/analytics",
        "permissions": set(_READ),
    },
}


def permissions_of(role: str) -> set[str]:
    return set(ROLES.get(role, {}).get("permissions", set()))


def has(role: str, permission: str) -> bool:
    if permission not in PERMISSIONS:
        raise KeyError(f"unknown permission {permission}")  # a typo must fail loudly
    return permission in permissions_of(role)
