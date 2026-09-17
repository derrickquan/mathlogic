"""The PRNG is the foundation of the freeze invariant, so it gets its own tests."""

from __future__ import annotations

from collections import Counter

from curriculum.rng import Rng, derive


def test_same_seed_gives_the_same_stream():
    assert [Rng(99).next_u64() for _ in range(20)] == [Rng(99).next_u64() for _ in range(20)]


def test_different_seeds_diverge():
    assert Rng(1).next_u64() != Rng(2).next_u64()


def test_stream_is_pinned_to_these_exact_values():
    """A golden stream. If this fails, every page ever frozen is unreproducible.

    splitmix64 from seed 0 is a published sequence; these are its first values.
    Nothing in this repository may change them.
    """
    rng = Rng(0)
    assert [rng.next_u64() for _ in range(3)] == [
        0xE220A8397B1DCDAF,
        0x6E789E6AA1B965F4,
        0x06C45D188009454F,
    ]


def test_below_stays_in_range():
    rng = Rng(7)
    assert all(0 <= rng.below(10) < 10 for _ in range(1000))


def test_below_is_roughly_uniform():
    rng = Rng(11)
    counts = Counter(rng.below(6) for _ in range(60_000))
    assert len(counts) == 6
    # Sampling noise on 10k expected per bucket is far inside 15%.
    assert all(8_500 < n < 11_500 for n in counts.values()), counts


def test_shuffle_is_a_permutation_and_is_reproducible():
    first = Rng(3).shuffled(range(50))
    second = Rng(3).shuffled(range(50))
    assert first == second
    assert sorted(first) == list(range(50))
    assert first != list(range(50))


def test_derive_separates_pages():
    parent = 20481
    seeds = {derive(parent, page) for page in range(1, 201)}
    assert len(seeds) == 200, "page seeds collided"


def test_derive_is_stable():
    assert derive(20481, 43) == derive(20481, 43)
    assert derive(20481, 43) != derive(20481, 44)
    assert derive(20481, 43) != derive(20482, 43)
