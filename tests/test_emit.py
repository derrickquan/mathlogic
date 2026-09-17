from __future__ import annotations

from curriculum import generate_level, load_level, sql
from curriculum.emit import _quote


def test_quoting_doubles_single_quotes():
    assert _quote("it's") == "'it''s'"


def test_sql_refuses_to_load_over_published_pages():
    level = load_level("2A")
    statements = sql(level, generate_level(level))
    assert "RAISE EXCEPTION" in statements
    assert "refusing to load over" in statements


def test_pages_are_inserted_unpublished_then_published_last():
    """Ordering is load-bearing: the freeze trigger rejects problems added to a
    page that is already published."""
    level = load_level("2A")
    statements = sql(level, generate_level(level))

    insert_pages = statements.index("INSERT INTO pages")
    first_problems = statements.index("INSERT INTO problems")
    publish = statements.index("SET published = true")

    assert insert_pages < first_problems < publish
    assert statements.rindex("INSERT INTO problems") < publish


def test_unpublished_load_does_not_publish():
    level = load_level("2A")
    statements = sql(level, generate_level(level), published=False)
    assert "SET published = true" not in statements


def test_every_band_becomes_a_page_template_row():
    level = load_level("2A")
    statements = sql(level, generate_level(level))
    assert statements.count("INSERT INTO page_templates") == len(level.bands)


def test_one_problems_statement_per_page():
    level = load_level("2A")
    statements = sql(level, generate_level(level))
    assert statements.count("INSERT INTO problems") == level.page_count


def test_the_whole_load_is_one_transaction():
    level = load_level("2A")
    statements = sql(level, generate_level(level))
    assert statements.count("BEGIN;") == 1
    assert statements.count("COMMIT;") == 1
    assert statements.index("BEGIN;") < statements.index("COMMIT;")
