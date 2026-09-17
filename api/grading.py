"""Turning a reading into a verdict.

Grading is on the final answer only. Working — carry marks, intermediate
products — is captured as ink but not graded, so work analysis can be added later
without having to re-collect anything.

The three verdicts are not three degrees of the same thing. Correct and wrong are
about the maths. Illegible is about the writing and says nothing about the maths,
which is why a child is told something different for it: told only "try again",
a child assumes the arithmetic was wrong and changes an answer that was right.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .recognition import Reading

#: Below this, nobody has read the answer yet — it goes to a facilitator rather
#: than to the child as a verdict. Worth watching closely in the first month:
#: the resulting correction rate is what decides whether one facilitator can
#: cover a class of thirty or is pushed back into being a grader.
DEFAULT_CONFIDENCE_THRESHOLD = 0.80

#: After this many rewrites the answer is accepted as written and a legibility
#: note is made instead. No child gets stuck in a loop at bedtime.
REWRITE_CEILING = 2


class Verdict(str, Enum):
    """Matches `answer_verdict` in the schema."""

    CORRECT = "correct"
    WRONG = "wrong"
    ILLEGIBLE = "illegible"


@dataclass(frozen=True)
class Grade:
    verdict: Verdict
    value: str | None
    confidence: float
    needs_review: bool
    accepted_as_written: bool = False

    @property
    def message(self) -> str:
        """What the child is told. Deliberately different for each verdict.

        Being accepted as written is checked first: the child has been asked to
        rewrite twice and needs to hear that the loop has ended, whether or not
        the answer underneath turned out to be right.
        """
        if self.accepted_as_written:
            return "I'll keep what you've written. That's fine — on we go."
        if self.verdict is Verdict.CORRECT:
            return ""
        if self.verdict is Verdict.WRONG:
            return "Not quite — we'll come back to this one."
        return "I couldn't read that one. Write it again for me?"


def grade(
    reading: Reading,
    correct_answer: str,
    *,
    rewrites_so_far: int = 0,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    override: str | None = None,
) -> Grade:
    """Grade one answer.

    `override` is a facilitator's reading, which always wins: a person looking at
    the ink is the most reliable recogniser available.
    """
    if override is not None:
        return Grade(
            verdict=Verdict.CORRECT if override == correct_answer else Verdict.WRONG,
            value=override,
            confidence=1.0,
            needs_review=False,
        )

    unreadable = reading.value is None
    unsure = reading.confidence < threshold

    if unreadable or unsure:
        if rewrites_so_far >= REWRITE_CEILING:
            # Two tries was enough. Take what is there, note the legibility, and
            # move on; the child is not marked down for their handwriting.
            return Grade(
                verdict=Verdict.CORRECT if reading.value == correct_answer else Verdict.WRONG,
                value=reading.value,
                confidence=reading.confidence,
                needs_review=True,
                accepted_as_written=True,
            )
        return Grade(
            verdict=Verdict.ILLEGIBLE,
            value=reading.value,
            confidence=reading.confidence,
            needs_review=True,
        )

    return Grade(
        verdict=Verdict.CORRECT if reading.value == correct_answer else Verdict.WRONG,
        value=reading.value,
        confidence=reading.confidence,
        needs_review=False,
    )
