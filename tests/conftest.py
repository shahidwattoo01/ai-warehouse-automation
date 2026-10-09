"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def seed() -> int:
    return 42
