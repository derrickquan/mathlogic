"""Curriculum authoring: templates in, frozen pages out.

    from curriculum import load_level, generate_level

    level = load_level("2A")
    pages = generate_level(level)

Generation is deterministic. Two runs of the same template produce byte-identical
pages, which is what lets a published page be regenerated and checked years later.
"""

from __future__ import annotations

from pathlib import Path

from .emit import digest, pretty_json, sql
from .generate import Page, Problem, generate_level, generate_page
from .template import Band, Level, build, load

TEMPLATE_DIR = Path(__file__).parent / "templates"
GOLDEN_DIR = Path(__file__).parent / "golden"


def template_path(level_name: str) -> Path:
    return TEMPLATE_DIR / f"{level_name}.json"


def load_level(level_name: str) -> Level:
    path = template_path(level_name)
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in TEMPLATE_DIR.glob("*.json"))) or "none"
        raise FileNotFoundError(f"no template for level {level_name!r}; available: {available}")
    return load(path)


__all__ = [
    "Band",
    "GOLDEN_DIR",
    "Level",
    "Page",
    "Problem",
    "TEMPLATE_DIR",
    "build",
    "digest",
    "generate_level",
    "generate_page",
    "load",
    "load_level",
    "pretty_json",
    "sql",
    "template_path",
]
