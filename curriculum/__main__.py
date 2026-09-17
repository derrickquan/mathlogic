"""Command line: generate a level, verify it has not drifted, or look at a page.

    python -m curriculum generate 2A --out build
    python -m curriculum verify 2A
    python -m curriculum show 2A --page 43
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import GOLDEN_DIR, digest, generate_level, load_level, pretty_json, sql


def _summary(level, pages) -> str:
    problems = sum(len(page.problems) for page in pages)
    return f"{level.name}: {len(pages)} pages, {problems} problems, digest {digest(level, pages)[:16]}"


def cmd_generate(args: argparse.Namespace) -> int:
    level = load_level(args.level)
    pages = generate_level(level)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    json_path = out / f"{level.name}.json"
    sql_path = out / f"{level.name}.sql"
    json_path.write_text(pretty_json(level, pages), encoding="utf-8")
    sql_path.write_text(sql(level, pages, published=not args.unpublished), encoding="utf-8")

    print(_summary(level, pages))
    print(f"  {json_path}")
    print(f"  {sql_path}")

    if args.write_golden:
        golden_path = _write_golden(level, pages)
        print(f"  {golden_path} (rewritten)")
    return 0


def _golden_path(level_name: str) -> Path:
    return GOLDEN_DIR / f"{level_name}.json"


def _write_golden(level, pages) -> Path:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = _golden_path(level.name)
    payload = {
        "level": level.name,
        "digest": digest(level, pages),
        "page_count": len(pages),
        "problem_count": sum(len(page.problems) for page in pages),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def cmd_verify(args: argparse.Namespace) -> int:
    level = load_level(args.level)
    pages = generate_level(level)
    current = digest(level, pages)

    path = _golden_path(level.name)
    if not path.exists():
        print(
            f"no recorded digest for {level.name}. If this level has never been published, "
            f"record one with: python -m curriculum generate {level.name} --write-golden",
            file=sys.stderr,
        )
        return 2

    recorded = json.loads(path.read_text(encoding="utf-8"))
    if recorded["digest"] == current:
        print(f"{level.name} matches its recorded digest ({current[:16]})")
        return 0

    print(
        f"{level.name} HAS DRIFTED\n"
        f"  recorded: {recorded['digest']}\n"
        f"  current:  {current}\n"
        "Published pages are frozen. If pages of this level are already in front of\n"
        "students, this change must be reverted, not re-recorded.",
        file=sys.stderr,
    )
    return 1


def cmd_show(args: argparse.Namespace) -> int:
    level = load_level(args.level)
    band = level.band_for(args.page)
    from .generate import generate_page

    page = generate_page(band, args.page)
    print(f"{level.name} page {page.page_number}  (band {band.page_from}-{band.page_to})")
    print(f"  {', '.join(band.constraint_sources)}")
    print()
    for problem in page.problems:
        print(f"  {problem.position:>2}.  {problem.prompt:<8} = {problem.correct_answer}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="curriculum", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="generate a level's pages to JSON and SQL")
    gen.add_argument("level")
    gen.add_argument("--out", default="build", help="output directory (default: build)")
    gen.add_argument(
        "--unpublished",
        action="store_true",
        help="load the pages without publishing them, leaving them editable",
    )
    gen.add_argument(
        "--write-golden",
        action="store_true",
        help="record the digest as the level's frozen content",
    )
    gen.set_defaults(func=cmd_generate)

    ver = sub.add_parser("verify", help="check a level still generates its recorded content")
    ver.add_argument("level")
    ver.set_defaults(func=cmd_verify)

    show = sub.add_parser("show", help="print one page")
    show.add_argument("level")
    show.add_argument("--page", type=int, required=True)
    show.set_defaults(func=cmd_show)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
