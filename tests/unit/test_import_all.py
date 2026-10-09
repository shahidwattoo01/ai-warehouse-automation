"""Every module must import (third-party extras may be missing; those are skipped)."""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import warehouse_ai


def _modules() -> list[str]:
    return [m.name for m in pkgutil.walk_packages(warehouse_ai.__path__, "warehouse_ai.")]


@pytest.mark.parametrize("name", _modules())
def test_module_imports(name: str) -> None:
    try:
        importlib.import_module(name)
    except ModuleNotFoundError as exc:
        pytest.skip(f"optional dependency missing: {exc.name}")
