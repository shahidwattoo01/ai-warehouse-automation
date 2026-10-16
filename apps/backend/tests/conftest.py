"""Test settings: never record API test runs into the developer's real database.

Environment variables override .env, and this runs before any test imports the app.
Database tests that need PostgreSQL opt in explicitly (see test_run_store.py).
"""

import os

os.environ["PERSIST_RUNS"] = "false"
