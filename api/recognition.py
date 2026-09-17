"""Handwriting recognition, behind an interface.

The engine is not chosen yet — MyScript iink and Mathpix are the candidates, and
the trial runs in week one with real children. Nothing else in the build waits on
that answer, so recognition lives behind this protocol and the rest of the system
only ever sees a `Reading`.

Two rules hold whichever engine wins, and both are about where recognition
happens rather than how well:

  * **Server-side only.** The tablet sends ink and gets back a verdict. No
    correct answer is ever on the device, which removes the cheating surface
    entirely and a good deal of client complexity with it.
  * **Confidence is separate from correctness.** A low-confidence read is not a
    wrong answer; it is an answer nobody has read yet. Conflating the two is how
    a child gets told they are wrong when they are not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class Reading:
    """What the recogniser made of one answer.

    `value` is None when it could make nothing of the ink at all. That is
    different from a low-confidence guess, and the grader treats it differently.
    """

    value: str | None
    confidence: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0 and 1, got {self.confidence}")


class Recogniser(Protocol):
    def read(
        self,
        ink: Sequence[Mapping[str, Any]],
        *,
        answer_shape: str = "integer",
        profile: Mapping[str, Any] | None = None,
    ) -> Reading:
        """Read one answer.

        `profile` is the student's handwriting profile — the calibration baseline
        plus everything learned from facilitator overrides since. An engine that
        cannot use it ignores it.
        """
        ...


class NullRecogniser:
    """Reads nothing, with no confidence at all.

    The honest default before an engine is wired in: every answer lands in the
    facilitator's review queue rather than being silently marked. Useful in
    development precisely because it is unmissable.
    """

    def read(self, ink, *, answer_shape="integer", profile=None) -> Reading:
        return Reading(value=None, confidence=0.0)


class DeclaredValueRecogniser:
    """Takes the value the client declares it wrote, at full confidence.

    For tests and for the browser prototype, where a person stands in for the
    engine. It is **not** a fallback for production: trusting the device with
    what it wrote is a short step from trusting it with whether that was right,
    and the whole point of server-side recognition is that it never does.

    The declared value rides on the ink payload as `{"declared": "9"}` so the
    transport does not need a special shape for it.
    """

    def read(self, ink, *, answer_shape="integer", profile=None) -> Reading:
        for stroke in ink:
            declared = stroke.get("declared")
            if declared is not None:
                return Reading(value=str(declared), confidence=1.0)
        return Reading(value=None, confidence=0.0)
