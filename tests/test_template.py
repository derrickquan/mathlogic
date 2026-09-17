from __future__ import annotations

import pytest

from curriculum import build, load_level


def a_band(page_from, page_to, **overrides):
    band = {
        "pages": [page_from, page_to],
        "problems_per_page": 20,
        "form": "a + b = _",
        "operands": {"a": {"range": [1, 9]}, "b": {"range": [1, 9]}},
        "constraints": ["sum <= 10"],
        "seed": 1,
    }
    band.update(overrides)
    return band


def a_level(bands, **overrides):
    level = {
        "level": "T",
        "sort_order": 1,
        "description": "test",
        "page_count": 100,
        "default_packet_size": 10,
        "bands": bands,
    }
    level.update(overrides)
    return level


def test_a_well_formed_level_builds():
    level = build(a_level([a_band(1, 50), a_band(51, 100)]))
    assert len(level.bands) == 2
    assert level.band_for(75).page_from == 51


def test_a_gap_between_bands_is_rejected():
    with pytest.raises(ValueError, match="no gap or overlap"):
        build(a_level([a_band(1, 40), a_band(51, 100)]))


def test_an_overlap_is_rejected():
    with pytest.raises(ValueError, match="no gap or overlap"):
        build(a_level([a_band(1, 60), a_band(51, 100)]))


def test_bands_must_reach_the_end_of_the_level():
    with pytest.raises(ValueError, match="bands stop at page 80"):
        build(a_level([a_band(1, 80)]))


def test_bands_must_start_at_page_one():
    with pytest.raises(ValueError, match="expected a band starting at page 1"):
        build(a_level([a_band(2, 100)]))


def test_packet_size_must_be_one_the_schema_allows():
    with pytest.raises(ValueError, match="default_packet_size"):
        build(a_level([a_band(1, 100)], default_packet_size=7))


def test_seed_must_fit_the_column():
    with pytest.raises(ValueError, match="bigint"):
        build(a_level([a_band(1, 100, seed=1 << 70)]))


def test_unknown_form_is_rejected():
    with pytest.raises(ValueError, match="unknown form"):
        build(a_level([a_band(1, 100, form="a ^ b = _")])).bands[0].form


def test_missing_operand_is_rejected():
    with pytest.raises(ValueError, match="needs operand"):
        build(a_level([a_band(1, 100, operands={"a": {"range": [1, 9]}})]))


def test_2a_template_loads_and_tiles_the_level():
    level = load_level("2A")
    assert level.name == "2A"
    assert level.page_count == 200
    assert level.default_packet_size == 10
    covered = [p for p in range(1, 201) if level.band_for(p)]
    assert len(covered) == 200
