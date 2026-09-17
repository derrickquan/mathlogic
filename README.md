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
| `curriculum/` | The generator, and one template file per level |
| `db/checks/` | Invariant checks, run against a real database |
| [CLAUDE.md](CLAUDE.md) | Project memory: invariants, the rules with numbers in them, what is still open |

## The curriculum generator

Pages are generated from a template, then frozen. Generation is deterministic:
the same template reproduces the same 4,000 problems forever, which is what lets
a published page be regenerated and checked against what students were given.

```
python -m curriculum generate 2A --out build   # JSON + a SQL load script
python -m curriculum verify 2A                 # has the level drifted?
python -m curriculum show 2A --page 43         # print one page
```

Generated output is not committed — it is reproducible from the templates, and
`curriculum/golden/2A.json` records the digest so drift is caught rather than
merged.

## Checks

```
python -m pytest        # 69 tests: the generator, the constraints, level 2A
scripts/verify-db.sh    # throwaway Postgres: schema, load 2A, assert invariants
```

`verify-db.sh` stands up its own cluster, applies the schema, loads the level and
checks that published pages reject every write, that graded attempts cannot be
rewritten, that the gate arithmetic rounds the way the spec says, and that all
4,000 answer keys are right when recomputed in SQL. It tears the cluster down
afterwards and does not touch any Postgres of yours.

## The shape of it

Two in-centre sessions a week of about 45 minutes, plus homework on three other
days. A packet of 5 or 10 pages is the unit of assignment, repetition and
advancement. 95% accuracy advances a packet; two failures drop it automatically.
Homework closes at 100%, because practice is corrected until it is right.

One facilitator covers 25–30 students. The system grades; the facilitator teaches.

## Status

Level 2A is authored: 200 pages, 4,000 problems, loading cleanly into the schema
with every invariant checked. Nothing else is built yet — no tablet app, no
recognition, no grading, no console, no parent email.
