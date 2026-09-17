# Level templates

One file per level. Each holds the level's own row (`name`, `sort_order`,
`description`, `page_count`, `default_packet_size`) and its bands — one band per
page range, which becomes one `page_templates` row.

A band's `seed` is the thing that matters most. Generation is deterministic, so
the seed plus the band config reproduces the band's pages exactly, forever. Change
a seed, a range or a constraint and every page in that band becomes a different
page. Once a band's pages are published, its entry here is as frozen as they are.

The bands of a level must tile it exactly — page 1 to `page_count`, no gap and no
overlap. The database's exclusion constraint catches overlaps; the loader catches
gaps.

## 2A — addition within 10

The v1 level. Answers are single digits, the form never changes, and the
constraint set is small, so the end-to-end loop can be proven without the
generator or the recogniser being the hard part.

| Pages | Addends | Distinct problems available | What the band is for |
| --- | --- | --- | --- |
| 1–40 | b 1–3 | 24 | Introduce. Small second addend, one new idea at a time |
| 41–80 | b 1–5 | 35 | Widen |
| 81–120 | b 1–9 | 45 | The full range of the level |
| 121–160 | b 1–9, order mixed | 45 | Same facts, addend order varied |
| 161–200 | b 1–9, sums 5–10 | 39 | The harder facts, for speed |

Twenty problems per page against pools of 24 to 45 means consecutive pages within
a band are mostly the same facts in a different order. That is the method working
as intended: repetition is how the page gets faster, and a page that introduced
new facts every time would be testing rather than drilling.

### Two judgement calls worth knowing about

**Band 1 takes addends up to 3, not up to 2.** The level plan in
`docs/curriculum-templates.md` describes the first band as "+1 and +2". With
`sum <= 10` and no trivial problems that yields 17 distinct problems, and a page
needs 20 without repeating one. Adding +3 brings the pool to 24. The alternative
was allowing a problem to appear twice on one page, which is worse: a child
notices, and it looks like a mistake.

**`mixed_operand_order` is a new constraint.** The plan asks the late bands for
the same facts "with the addend order varied" — a child who has only ever seen
3 + 6 should meet 6 + 3 and recognise the same fact rather than a new one. No
constraint in the documented vocabulary expressed that, so there is now one, and
it is a page constraint: it judges the shape of the whole page, not any single
problem.
