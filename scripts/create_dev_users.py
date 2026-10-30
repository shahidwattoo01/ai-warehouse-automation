"""Create one development user per role (dev-admin, dev-supervisor, dev-operator, dev-clerk,
dev-viewer) with random passwords, saved to dev_users.local.json (git-ignored) for manual testing
and the browser tests. Existing dev users get a new password. Not for production.

    python scripts/create_dev_users.py
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "backend"))
OUT = ROOT / "dev_users.local.json"
USERS = {
    "dev-admin": "admin",
    "dev-supervisor": "supervisor",
    "dev-operator": "operator",
    "dev-clerk": "inventory_clerk",
    "dev-viewer": "viewer",
}


def main() -> int:
    from app.core.config import get_settings
    from app.services.users import SqlUserStore, hash_password

    store = SqlUserStore(get_settings().database_url)
    saved = {}
    for username, role in USERS.items():
        password = f"Dev-{secrets.token_urlsafe(12)}"
        user = store.get_by_username(username)
        if user is None:
            store.create(
                username, f"Dev {role.replace('_', ' ').title()}", role, hash_password(password)
            )
        else:
            store.update(
                user.user_id,
                password_hash=hash_password(password),
                role=role,
                active=True,
                failed_logins=0,
                locked_until=None,
            )
        saved[username] = {"role": role, "password": password}
    OUT.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    print(f"{len(saved)} development users ready; passwords in {OUT.name} (git-ignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
