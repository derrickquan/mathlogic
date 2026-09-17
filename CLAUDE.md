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

## Open, not yet decided

- Recognition engine — MyScript iink vs Mathpix digital ink. Test runs in week
  one with ~10 children, alongside the build, not before it.
- Confidence threshold, and the correction rate it produces. That number decides
  whether one facilitator covers 30 students or becomes a grader again.
- Time standards per level. Need real data first.
- Franchisee royalty, pencilled at $35.
- Trademark registration and domain.
