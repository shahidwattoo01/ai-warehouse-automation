"""Create a user (the first admin, or anyone while no admin can log in yet).

    python scripts/create_user.py --username amna --name "Amna Khan" --role admin
    python scripts/create_user.py --list

The password is asked twice at the prompt and never shown or stored in plain text (Argon2 hash in
the users table). For unattended setups the environment variable NEW_USER_PASSWORD is used instead
of the prompt. Roles: admin, supervisor, operator, inventory_clerk, viewer.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "backend"))


def main() -> int:
    from app.core.config import get_settings
    from app.core.permissions import ROLES
    from app.services.users import SqlUserStore, hash_password, password_problem

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--username")
    parser.add_argument("--name", help="full name")
    parser.add_argument("--role", choices=sorted(ROLES))
    parser.add_argument("--list", action="store_true", help="list the users")
    args = parser.parse_args()
    store = SqlUserStore(get_settings().database_url)

    if args.list:
        for u in store.list():
            state = "active" if u.active else "disabled"
            print(f"{u.username:20s} {u.role:16s} {state:9s} {u.full_name}")
        return 0
    if not (args.username and args.name and args.role):
        parser.error("--username, --name and --role are required")

    password = os.environ.get("NEW_USER_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("✗ the passwords differ")
            return 1
    problem = password_problem(password, args.username)
    if problem:
        print(f"✗ password rejected: {problem}")
        return 1
    try:
        user = store.create(args.username, args.name, args.role, hash_password(password))
    except ValueError as err:
        print(f"✗ {err}")
        return 1
    print(f"✓ created {user.username} ({ROLES[user.role]['label']})")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
