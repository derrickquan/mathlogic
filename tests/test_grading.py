"""Grading one answer. No database, no engine — just a reading and the key."""

from __future__ import annotations

import pytest

from api.grading import REWRITE_CEILING, Verdict, grade
from api.recognition import DeclaredValueRecogniser, NullRecogniser, Reading


def read(value, confidence=1.0):
    return Reading(value=value, confidence=confidence)


def test_a_confident_correct_reading_is_correct():
    result = grade(read("9"), "9")
    assert result.verdict is Verdict.CORRECT
    assert not result.needs_review
    assert result.message == "", "nothing is said; the next problem opens"


def test_a_confident_wrong_reading_is_wrong():
    result = grade(read("6"), "8")
    assert result.verdict is Verdict.WRONG
    assert "Not quite" in result.message


def test_unreadable_ink_is_never_called_wrong():
    """A child told only 'try again' assumes the maths was wrong and changes a
    correct answer. The message has to be about the writing."""
    result = grade(read(None), "9")
    assert result.verdict is Verdict.ILLEGIBLE
    assert "couldn't read" in result.message
    assert "wrong" not in result.message.lower()


def test_a_low_confidence_reading_is_not_a_verdict_yet():
    """Confidence is separate from correctness: an unsure read is an answer
    nobody has looked at, not a mistake."""
    result = grade(read("9", confidence=0.4), "9")
    assert result.verdict is Verdict.ILLEGIBLE
    assert result.needs_review


def test_the_threshold_is_where_it_is_set():
    assert grade(read("9", 0.81), "9", threshold=0.80).verdict is Verdict.CORRECT
    assert grade(read("9", 0.79), "9", threshold=0.80).verdict is Verdict.ILLEGIBLE
    assert grade(read("9", 0.79), "9", threshold=0.50).verdict is Verdict.CORRECT


def test_after_two_rewrites_the_answer_is_taken_as_written():
    """No child gets stuck in a loop at bedtime."""
    result = grade(read("9", confidence=0.2), "9", rewrites_so_far=REWRITE_CEILING)
    assert result.accepted_as_written
    assert result.verdict is Verdict.CORRECT, "the maths was right, however it looked"
    assert result.needs_review, "a person should still see it"
    assert "keep what you've written" in result.message


def test_being_taken_as_written_does_not_make_a_wrong_answer_right():
    result = grade(read("7", confidence=0.2), "9", rewrites_so_far=REWRITE_CEILING)
    assert result.accepted_as_written
    assert result.verdict is Verdict.WRONG


def test_ink_nobody_could_read_is_never_marked_wrong():
    """The bug the end-to-end demo caught, and the reason it matters.

    After two rewrites with nothing readable, grading `None` against the answer
    key made it wrong: it joined the corrections queue and counted against the
    95% gate. That is a child marked down for their handwriting, which is the
    one thing legibility must never do. It stays illegible and waits for a
    person to read the ink.
    """
    result = grade(read(None), "7", rewrites_so_far=REWRITE_CEILING)

    assert result.verdict is Verdict.ILLEGIBLE
    assert result.accepted_as_written, "the child moves on"
    assert result.needs_review, "but somebody has to look at it"
    assert result.value is None


def test_a_low_confidence_reading_at_the_ceiling_is_still_graded():
    """Different case: something was read, only not confidently. That is the
    best evidence anyone has, so it is graded and the review queue can correct
    it."""
    right = grade(read("7", confidence=0.3), "7", rewrites_so_far=REWRITE_CEILING)
    wrong = grade(read("4", confidence=0.3), "7", rewrites_so_far=REWRITE_CEILING)

    assert right.verdict is Verdict.CORRECT
    assert wrong.verdict is Verdict.WRONG
    assert right.needs_review and wrong.needs_review


def test_a_facilitator_override_beats_the_engine():
    result = grade(read("4", confidence=0.99), "9", override="9")
    assert result.verdict is Verdict.CORRECT
    assert result.confidence == 1.0
    assert not result.needs_review


def test_the_null_recogniser_reads_nothing_and_says_so():
    """The honest default before an engine is chosen: everything goes to a person."""
    reading = NullRecogniser().read([{"x": 1}])
    assert reading.value is None and reading.confidence == 0.0
    assert grade(reading, "9").verdict is Verdict.ILLEGIBLE


def test_the_declared_recogniser_takes_the_client_at_its_word():
    reading = DeclaredValueRecogniser().read([{"declared": "9", "points": []}])
    assert reading == Reading("9", 1.0)


def test_the_declared_recogniser_reads_nothing_when_nothing_is_declared():
    assert DeclaredValueRecogniser().read([{"points": []}]).value is None


def test_confidence_has_to_be_a_probability():
    with pytest.raises(ValueError, match="between 0 and 1"):
        Reading("9", 1.4)
