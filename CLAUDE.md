# MathLogic

A digital replacement for the Kumon worksheet model. Students work on lent iPads
with Apple Pencil, handwriting is recognised and graded server-side, parents get
one nightly report. Build one owned centre first, then license the software to
independent operators for a per-student royalty. Licensing is the business; the
centre is the proving ground.

Positioning is high quality and modestly cheaper than Kumon's roughly $200/month,
not a discount product. The differentiator is transparency.

## The source documents

| File | What it fixes |
| --- | --- |
| `docs/product-spec.md` | Product spec v0.1 — the decisions and their reasons |
| `docs/curriculum-templates.md` | Template format and the level-by-level content plan |
| `docs/schema.sql` | PostgreSQL 14+ schema, with the invariants enforced in triggers |

These came out of a planning session before the code started. Treat them as
settled unless the user changes them. When a decision is questioned, check the
spec first — most choices there carry their rationale with them.

## Invariants that must not be broken

- **Attempts are append-only.** Three goes at the same packet is three rows. A
  trigger blocks UPDATE on a graded attempt and blocks DELETE outright. Any code
  path that rewrites a graded attempt is a bug.
- **Pages and problems are frozen once published.** A repeated page must present
  identical problems, so the student gets faster rather than getting new work.
  Generation is seeded and deterministic; store the seed with the page.
- **Raw ink is stored permanently**, as stroke data, not bitmaps. It plus
  `recognition_corrections` is the labelled corpus, and it allows re-grading
  history against a better model.
- **Recognition is server-side only.** No correct answers ever land on the
  tablet. Offline work is captured as ink with a timestamp and graded on sync.
- **Packets are runtime, not curriculum.** Packet size is a property of the
  student, so a packet cannot be a row in the curriculum. Pages and problems stay
  canonical; the packet boundary is computed from current position + packet size.

## Rules with numbers in them

- Advancement gate: 95% accuracy, measured **per hundred problems**, not per
  packet. Allowed wrong = `ceil(problems * 0.05)`, minimum 1 (`allowed_wrong()`).
- Two failures on a packet auto-drops the student one packet and flags the
  facilitator. The flag says "go teach", it is not a request for a decision.
- Packet sizing: 3 consecutive in-centre packets over 45 min drops 10 → 5 pages;
  3 consecutive under 20 min raises 5 → 10. That is 4.5 vs 4.0 min/page — a dead
  band, so nobody oscillates. Only in-centre packets resize; home is uncontrolled.
- Active time = pen-down time plus gaps under ~90s, accumulated across sessions.
- Rewrite ceiling is 2. After that the answer is accepted as-is and a legibility
  note is written. No child is stuck in a loop at bedtime.
- Homework closes at 100%; advancement gates at 95%. Both thresholds are
  deliberate and different.
- One parent email per night at 8:30pm, including on days with no work. Work
  after 8:30pm rolls to the next night and is dated honestly.

## Language and framing that matter

- "Illegible" is never presented like "wrong". A child told only "try again"
  will change a correct answer. The message is that the writing could not be
  read.
- Legibility is tracked per digit, surfaced to parents as guidance, and never
  affects the maths score.
- Repeated demotion is its own signal. Both demotion paths (packet failure,
  cancelled corrections backlog) write to `student_events` so the pattern is
  visible; repeated drops escalate to a parent conversation.

## v1 scope

One level (2A) end to end: check in, get a packet, write with the pencil,
submit, grade, corrections, advancement/demotion, facilitator console with
alerts, nightly parent email with pre-send review. Deferred: time standards
(needs ~6 months of timing data), work-analysis on intermediate steps, homework
integrity detection, waiting-room display, remaining levels, multi-centre tooling.

Kumon's worksheets are copyrighted; the pedagogical structure is not. **All
problem content must be independently authored.** Level names follow the Kumon
convention only because instructors and parents already reason in them.

## Naming

The product was called "Digital Kumon" in planning. It is **MathLogic** now — a
competitor's trademark could not be the name, least of all for something meant to
be licensed to independent operators.

Screened before adoption: no tutoring chain or learning-centre franchise by this
name. Minor and unrelated users exist (an AI consultancy in Gurugram, two small
puzzle apps). The open risk is that "math" and "logic" are descriptive terms, so
the mark is likely to be weak and hard to enforce against a similarly named
tutoring business later. Raise this with a solicitor at registration.

## The curriculum generator

`curriculum/` generates a level's pages from a template, then freezes them.

- **Determinism is the whole point.** `curriculum/rng.py` is splitmix64, not
  `random`, because the standard library makes no cross-version promise about
  `shuffle` or `randrange`. Never swap it out: every page ever frozen becomes
  unreproducible if that stream changes, and the pinned test in
  `tests/test_rng.py` exists to stop it.
- Each page draws from its own stream, derived from the band's seed and the page
  number, so page 137 regenerates without replaying the 136 before it.
- **Constraints come in two kinds.** A problem constraint (`sum <= 10`,
  `exclude_trivial`) filters the candidate pool and can never fail at draw time.
  A page constraint (`min_distinct_operands`, `mixed_operand_order`) judges the
  whole page, so the generator draws, checks and redraws.
- `curriculum/golden/<level>.json` holds a digest of the level's full generated
  content. If `verify` reports drift on a level that is already in front of
  students, revert the change — do not re-record the digest.
- Generated output is not committed. It is reproducible, and a 4,000-problem
  diff hides more than it shows.
- Loading order is load-bearing: pages go in unpublished, problems attach, then
  a final UPDATE publishes them. The freeze trigger rejects problems added to an
  already-published page, so any other order fails.

## The progression rules

`progression/` is where every decision about a child lives. Pure functions over
frozen dataclasses: no database, no `date.today()` it was not handed, no request
object. That is deliberate — these are the rules that decide whether a
six-year-old moves forward or back, and they should be readable and testable
without standing anything up.

- A decision returns an `Outcome`: the new position, the events to write, and
  whether a person is needed. Events are produced at the moment of the change,
  never reconstructed afterwards from what the row now says.
- `EventKind` and `CorrectionStatus` mirror the PostgreSQL enums exactly. If one
  side gains a member the other has to.
- The rules never import the generator. `catalogue.py` is the four facts they
  need, behind a protocol, so they can be tested against a made-up three-level
  curriculum — which matters, because 2A is currently the only authored level and
  has nothing either side of it to fall back to or advance into.
- Things that are states rather than errors, and are handled as such: passing the
  last packet of the last authored level; failing twice at page 1 of the first
  level with nowhere to drop to. Both flag a person instead of raising.
- Packets are clipped at a level boundary rather than straddling two, so a
  level's last packet can be short. Because the gate is per hundred problems, a
  short packet is not a harsher one.

## The server

`api/` is thin on purpose. Rules live in `progression/`, SQL lives in `db.py`,
and `service.py` is the only file that knows about both. A rule creeping into a
route handler is a smell.

- **Recognition sits behind a protocol and no engine is chosen.** The default,
  `NullRecogniser`, reads nothing at all — so every answer lands in the
  facilitator's review queue rather than being silently marked by a stand-in
  somebody forgot was a stand-in. `DeclaredValueRecogniser` takes the client's
  word for what it wrote and is for tests and the prototype only; trusting the
  device with what it wrote is one step from trusting it with whether that was
  right.
- **Correct answers never leave the server.** `page_problems` returns prompts;
  `correct_answer_for` is named to make the other side of that line obvious.
  `test_the_tablet_is_never_given_a_correct_answer` fails if an answer key ever
  reaches a response, over the wire included.
- **An unfinished packet cannot be graded.** Submitting with 1 of 100 answered
  used to pass the gate on a technicality. The server counts answers against the
  packet's problem count and refuses, because it cannot take the tablet's word
  for having finished.
- The sizing rule reads the `packet_pacing` view and the escalation rule reads
  `student_events`. Neither is reassembled in Python. Sizing runs *after* the
  attempt is graded, because the view only sees graded in-centre attempts.
- Integration tests stand up a real PostgreSQL, apply the schema and load 2A.
  Testing this against a fake would test the wrong thing: the triggers are the
  invariants.

## Two findings from authoring 2A

**The schema did not enforce its second invariant.** `docs/schema.sql` claimed in
its header that pages and problems are frozen once published "(trigger below)",
but no such trigger existed — only the two on `attempts`. It does now:
`pages_frozen_when_published` and `problems_frozen_when_page_published`, covering
UPDATE and DELETE on pages, and INSERT, UPDATE and DELETE on their problems.
Publishing is the one permitted transition, so the check is on the OLD row.

**2A's answers are not all single digits.** `curriculum-templates.md` justified
picking 2A for v1 partly on that basis. It cannot be true of addition within 10:
there are nine ways to make 10 and one way to make 2, so 10 is the level's single
most common answer — 797 of 4,000 problems, on every one of the 200 pages. The
tablet's answer field and the recogniser must handle two digits from day one.
Capping sums at 9 to dodge it would make the level addition within 9, which is a
different level. The document has been corrected and
`tests/test_2a.py` guards against the assumption creeping back.

## Decisions made while building the prototype

- **Calibration is the first screen a new student ever sees**, before check-in,
  and it runs **0 to 10, not 0 to 9**. The spec said 9. Ten is the most common
  answer in 2A and its only two-digit one, so a calibration stopping at 9 never
  exercises the case the recogniser most has to get right.
- **The student never chooses their work.** No page picker, no packet-size
  control, no alternative to writing. Check-in states the assignment; it does not
  offer a menu. Anything that lets a child pick their own page lets them avoid
  what they find hard, and the method depends on them not being able to. In the
  prototype those controls exist only behind a disclosure labelled as not part of
  the product.
- Checking in and calibrating do not count toward active working time.

## Open, not yet decided

- Recognition engine — MyScript iink vs Mathpix digital ink. Test runs in week
  one with ~10 children, alongside the build, not before it.
- Confidence threshold, and the correction rate it produces. That number decides
  whether one facilitator covers 30 students or becomes a grader again.
- Time standards per level. Need real data first.
- Franchisee royalty, pencilled at $35.
- Trademark registration and domain.
