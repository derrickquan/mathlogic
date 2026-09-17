# Curriculum templates

Every page is generated from a template, then frozen. This document defines the template format and specifies the early levels concretely enough to generate from.

## Template format

A template is a config the generator consumes to emit a page of problems. One template per page range within a level, so difficulty ramps across the 200 pages rather than sitting flat.

```json
{
  "level": "2A",
  "pages": [1, 40],
  "problems_per_page": 20,
  "form": "a + b = _",
  "operands": {
    "a": { "range": [1, 9] },
    "b": { "range": [1, 5] }
  },
  "constraints": ["sum <= 10"],
  "no_repeat_within_page": true,
  "seed": 20481
}
```

The seed matters: generation must be deterministic, so regenerating a frozen page reproduces it exactly. Store the seed with the page, not just the output.

**Constraints are where the pedagogy lives.** The operand ranges alone would produce problems that skip the point of the level. A level teaching addition within 10 must exclude sums of 11, or it is silently teaching the next level. Constraints are also what prevent degenerate problems — a page of 1+1, 2+1, 3+1 satisfies the ranges and teaches nothing.

Standard constraint vocabulary worth building once:

| Constraint | Purpose |
| --- | --- |
| `sum <= n`, `product <= n` | Keeps results inside the level's scope |
| `no_carry`, `requires_carry` | Separates the page that introduces carrying from the ones before it |
| `no_borrow`, `requires_borrow` | Same, for subtraction |
| `result_positive` | Prevents negatives before they are taught |
| `divides_evenly` | Division before remainders are introduced |
| `min_distinct_operands: n` | Stops a page collapsing into near-identical problems |
| `exclude_trivial` | Drops +0, ×1, ×0 unless the page is specifically teaching them |

**Difficulty ramps within a level, not just between levels.** Pages 1–40 of a level should be noticeably easier than 161–200. Splitting each level into four or five page bands, each with its own template, is enough.

## Early levels

Level names follow the Kumon convention purely because instructors and parents already reason in it. Content is independently specified.

| Level | Teaches | Form | Constraints | Per page |
| --- | --- | --- | --- | --- |
| 6A | Counting to 10 | trace / sequence | — | 10 |
| 5A | Counting to 30, number order | `_` in a sequence | — | 12 |
| 4A | Writing numerals to 50 | write the numeral | — | 15 |
| 3A | Adding 1, 2, 3 | `a + b = _` | a 1–10, b 1–3, sum ≤ 13 | 20 |
| 2A | Addition within 10 | `a + b = _` | sum ≤ 10, `exclude_trivial` | 20 |
| A | Horizontal addition and subtraction | `a + b = _`, `a - b = _` | sum ≤ 20, `result_positive` | 20 |
| B | Vertical addition and subtraction, carrying | stacked | 2-digit, bands split `no_carry` then `requires_carry` | 16 |
| C | Multiplication tables, basic division | `a × b = _`, `a ÷ b = _` | factors 1–9, `divides_evenly` | 20 |

**The handwriting-recognition consequence of this table is worth noting.** Levels 6A to 4A have the youngest, messiest writers and answers that are single digits or short numerals. That is the easiest recognition problem paired with the hardest handwriting. Levels B and C have tidier writers but longer answers and stacked layouts, where the recogniser must also know which box an answer belongs to.

**Pick level 2A for the version-one build.** The form is uniform and the constraint set is small, so the loop can be proven without the generator or the recogniser being the hard part.

Note that answers are **not** all single digits, as an earlier draft of this document claimed. Addition within 10 makes 10 itself the most common answer in the level — there are nine ways to reach it and one way to reach 2 — and it appears on every page. About a fifth of the level's answers have two digits. The tablet's answer field and the recogniser must handle two digits from the first day; capping sums at 9 to avoid this would make the level addition within 9, which is not the level.

Band splits within a level follow the same pattern throughout: roughly pages 1–40 introduce, 41–120 drill, 121–200 mix and speed up. For level 2A that means +1 and +2 first, then the full range, then mixed with the addend order varied.

## Middle levels

| Level | Teaches | Constraints that matter | Per page |
| --- | --- | --- | --- |
| D | Multi-digit multiplication | 2×1 then 2×2 digit, bands by carry depth | 12 |
| E | Fractions: reducing, adding like denominators | denominators ≤ 12, `result_reduced` | 12 |
| F | Fractions: unlike denominators, four operations | lcm ≤ 60, mixed numbers in later bands | 10 |
| G | Negative numbers, basic algebra | single variable, integer solutions | 10 |
| H | Simultaneous equations, linear functions | two variables, integer solutions | 8 |

Two things change here and both affect the generator.

**Answers stop being a single number.** A reduced fraction has a numerator and denominator in separate positions; an equation has a solution that may be negative. The recogniser needs to know the expected answer shape per problem, not just read digits — and the answer field on the tablet has to match that shape.

**Inverse generation becomes necessary.** For fractions and algebra, generating operands at random produces mostly ugly problems. The generator has to work backwards from a clean answer: pick the solution first, then construct the problem that yields it. This is a different code path from the forward generation used below level D, and is worth knowing about before the generator is written rather than after.

Problems per page drops as problems get longer. That interacts with the advancement gate — fewer problems per page means fewer per packet, which is exactly why the gate is measured per hundred problems rather than per packet.

## Where templates stop

Templates work cleanly through roughly level H. Past that, generation stops being the right tool.

Levels beyond simultaneous equations — factorisation, quadratics, trigonometry, calculus — have answers that are expressions rather than numbers, and problems whose difficulty depends on structure rather than operand size. A generator can produce a thousand quadratics, but it cannot tell which ones are instructive. Those levels need hand-authored problem banks, with the generator reduced to producing variants of an authored seed problem.

This is not a v1 concern. A centre serving primary-age students may never reach them, and by the time it does there is a business funding the authoring.

**Grading changes too.** Everything below level G has one correct answer that a recogniser can match exactly. An algebraic answer can be correct in several written forms, so grading has to compare mathematical equivalence rather than characters. That is a genuinely different problem and a reason to stop the generated curriculum at H until the earlier levels are working.

**Suggested authoring order:** 2A first and completely, as the v1 proving ground. Then A, 3A, B — the levels most new students place into. Then outward in both directions as enrolment demands.
