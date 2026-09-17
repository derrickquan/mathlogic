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
| `progression/` | The rules: packet assembly, the gate, demotion, sizing, corrections |
| `api/` | The server: recognition, grading, the database, the loop |
| `prototype/` | A playable browser prototype of the student loop |
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

## The server

```
pip install -e '.[server,dev]'
scripts/verify-db.sh                       # proves a database is loadable
MATHLOGIC_DSN=postgresql:///mathlogic \
  uvicorn api.app:app --factory --reload
```

| File | Job |
| --- | --- |
| `api/auth.py` | Passwords, tokens, and the three kinds of session |
| `api/recognition.py` | The engine, behind a protocol. None chosen yet, so the default reads nothing and everything goes to a person |
| `api/grading.py` | A reading plus the answer key becomes a verdict. Confidence is kept separate from correctness |
| `api/db.py` | Every statement that touches PostgreSQL |
| `api/service.py` | The loop — the only place rules, queries and ink meet |
| `api/app.py` | Routes |

**Correct answers never leave the server.** The tablet is sent prompts and gets
back verdicts, which is what makes offline capture safe and removes the cheating
surface. There is a test that fails if an answer key ever appears in a response.

### Who can do what

| Session | Opened by | Lasts | Reaches |
| --- | --- | --- | --- |
| Parent | Email and password | 30 days | Their own children's reports and history; unlocking a tablet |
| Staff | Email and password | 12 hours | The console, overrides, clearing a backlog |
| Student | A badge scan, or a parent unlock | 4 hours | One student's own work, and nothing else |

A student session can never reach the parent view — a child handed an unlocked
tablet must not be able to wander into their own scores. A parent can only ever
reach their own children. Identity always comes from the token: a `staff_id` in a
JSON body is a `staff_id` anyone can type.

## Checks

```
python -m pytest        # 202 tests; the API ones stand up their own PostgreSQL
python -m pytest -m 'not integration'   # just the pure ones, no database needed
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

## The rules

`progression/` holds every decision the system makes about a child, as pure
functions over frozen values — no database, no clock it was not handed, no HTTP.
Each rule lives in one place:

| File | Rule |
| --- | --- |
| `packets.py` | A packet is computed from position and packet size, and clipped at a level boundary rather than straddling two |
| `gate.py` | 95% per hundred problems; a first failure repeats, a second drops a packet and flags a person |
| `sizing.py` | Three consecutive in-centre packets either side of a dead band; homework never resizes |
| `corrections.py` | A queue belonging to the student, and the second demotion path |
| `catalogue.py` | The little the rules need to know about the curriculum |

## Status

Level 2A is authored — 200 pages, 4,000 problems, loading cleanly into the
schema with every invariant checked — and the progression rules are written and
tested. There is a playable browser prototype of the student loop.

The API server runs the whole loop against the real schema: check in, fetch the
assignment, submit ink, grade, corrections, advancement and demotion.

Not built: real handwriting recognition (no engine chosen — the default reads
nothing and sends everything to a person), the facilitator console, the nightly
email, and the native tablet app.
