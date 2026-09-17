# MathLogic

Handwriting-first maths practice. Students work on lent iPads with Apple Pencil,
ink is recognised and graded server-side, and parents get one report a night —
including on the nights when nothing was done.

## Where things are

| Path | Contents |
| --- | --- |
| [docs/product-spec.md](docs/product-spec.md) | The product spec. Start here — the decisions carry their rationale |
| [docs/curriculum-templates.md](docs/curriculum-templates.md) | Template format, constraint vocabulary, the level-by-level plan |
| [docs/schema.sql](docs/schema.sql) | PostgreSQL 14+ schema. The invariants are triggers, not conventions |
| [CLAUDE.md](CLAUDE.md) | Project memory: invariants, the rules with numbers in them, what is still open |

## The shape of it

Two in-centre sessions a week of about 45 minutes, plus homework on three other
days. A packet of 5 or 10 pages is the unit of assignment, repetition and
advancement. 95% accuracy advances a packet; two failures drop it automatically.
Homework closes at 100%, because practice is corrected until it is right.

One facilitator covers 25–30 students. The system grades; the facilitator teaches.

## Status

Pre-build. The specification is settled, v1 is one level (2A) end to end, and
nothing is implemented yet.
