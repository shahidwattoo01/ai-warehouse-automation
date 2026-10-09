"""Seeded streams are reproducible and independent."""

from __future__ import annotations

from warehouse_ai.common.seeds import RandomStreams


def test_same_seed_same_numbers() -> None:
    a, b = RandomStreams(42), RandomStreams(42)
    assert a.get("orders").integers(0, 10**9, 5).tolist() == b.get("orders").integers(0, 10**9, 5).tolist()


def test_streams_are_independent() -> None:
    a, b = RandomStreams(42), RandomStreams(42)
    a.get("faults").random(1000)  # consuming one stream must not change another
    assert a.get("orders").random() == b.get("orders").random()
