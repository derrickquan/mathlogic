"""A deterministic PRNG that will not move under us.

Regenerating a frozen page has to reproduce it exactly, years from now, on
whatever Python is current then. The standard library's `random` makes no such
promise: `Random.random()` is documented as stable, but `choice`, `shuffle` and
`randrange` route through `_randbelow`, which is an implementation detail and
has changed before.

So the curriculum owns its generator. splitmix64 is thirty lines, fully
specified by the constants below, and produces the same stream on any machine
that can multiply 64-bit integers. If this file changes, every page generated
before the change becomes unreproducible — treat it as frozen.
"""

from __future__ import annotations

from typing import Iterable, TypeVar

MASK64 = (1 << 64) - 1

_GOLDEN_GAMMA = 0x9E3779B97F4A7C15
_MIX_A = 0xBF58476D1CE4E5B9
_MIX_B = 0x94D049BB133111EB

T = TypeVar("T")


class Rng:
    """splitmix64. Construct with a seed, draw with `below` or `shuffle`."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & MASK64

    def next_u64(self) -> int:
        self._state = (self._state + _GOLDEN_GAMMA) & MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * _MIX_A) & MASK64
        z = ((z ^ (z >> 27)) * _MIX_B) & MASK64
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        """A uniform integer in [0, n).

        Rejection-sampled rather than taken modulo, so the low values are not
        very slightly more likely than the high ones. With n far below 2**64 the
        loop effectively never runs twice, but the bias it removes would
        otherwise be baked into every page we ever freeze.
        """
        if n <= 0:
            raise ValueError(f"below() needs a positive bound, got {n}")
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            value = self.next_u64()
            if value < limit:
                return value % n

    def shuffle(self, items: list[T]) -> None:
        """Fisher-Yates, in place."""
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]

    def shuffled(self, items: Iterable[T]) -> list[T]:
        out = list(items)
        self.shuffle(out)
        return out


def derive(seed: int, *parts: int) -> int:
    """A child seed from a parent seed plus some integers.

    Used to give every page its own independent stream from the band's single
    stored seed, so page 7 regenerates without replaying pages 1 through 6.
    """
    state = seed & MASK64
    for part in parts:
        state = (state ^ (part & MASK64)) & MASK64
        state = Rng(state).next_u64()
    return state
