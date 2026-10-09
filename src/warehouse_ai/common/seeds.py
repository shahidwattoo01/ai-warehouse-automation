"""Seeded random streams.

One master seed is split into independent named streams (orders, faults, noise ...), so changing one
source of randomness never changes another. This is what keeps experiments comparable.
"""

from __future__ import annotations

import numpy as np

STREAM_NAMES = ("orders", "faults", "noise", "workers", "policy", "vision")


class RandomStreams:
    """Independent, reproducible random generators derived from one master seed."""

    def __init__(self, master_seed: int) -> None:
        self.master_seed = master_seed
        children = np.random.SeedSequence(master_seed).spawn(len(STREAM_NAMES))
        self._rngs = {name: np.random.default_rng(seq) for name, seq in zip(STREAM_NAMES, children)}

    def get(self, name: str) -> np.random.Generator:
        if name not in self._rngs:
            raise KeyError(f"unknown stream {name!r}; valid: {STREAM_NAMES}")
        return self._rngs[name]
