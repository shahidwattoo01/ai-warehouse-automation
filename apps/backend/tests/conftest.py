"""Test settings: never record API test runs into the developer's real database, and log every
test in as an administrator unless it is marked `real_auth` (then it logs in for real).

Environment variables override .env, and this runs before any test imports the app.
Database tests that need PostgreSQL opt in explicitly (see test_run_store.py).
"""

import os

os.environ["PERSIST_RUNS"] = "false"
os.environ["AUTH_STORE"] = "memory"  # users of the tests live in memory, never in the real table
os.environ["JWT_SECRET"] = "tests-only-secret-" + "x" * 40
os.environ["RATE_LIMIT_ENABLED"] = "false"  # tests call the API in fast loops; test_ratelimit.py

import pytest  # noqa: E402

from app.core import auth  # noqa: E402
from app.core.permissions import permissions_of  # noqa: E402
from app.main import app  # noqa: E402
from app.services.users import hash_password  # noqa: E402

TEST_ADMIN = auth.Principal(
    "test-admin", "test-admin", "Test Admin", "admin", frozenset(permissions_of("admin"))
)


@pytest.fixture(autouse=True)
def logged_in_admin(request):
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    app.dependency_overrides[auth.current_user] = lambda: TEST_ADMIN
    yield
    app.dependency_overrides.pop(auth.current_user, None)


def make_user(username: str, role: str, password: str = "Test#Pass2026") -> str:
    """A user in the test store (created once); returns a valid access token."""
    store = auth.get_store()
    user = store.get_by_username(username) or store.create(
        username, username.title(), role, hash_password(password)
    )
    return auth.create_access_token(user)[0]


@pytest.fixture(name="make_user")
def make_user_fixture():
    """make_user(username, role) -> access token, as a fixture (test packages share the name
    "tests", so test modules do not import from conftest)."""
    return make_user


@pytest.fixture()
def ws_token() -> str:
    """A real access token, for the live stream (it authenticates by its first message)."""
    return make_user("stream-viewer", "viewer")
