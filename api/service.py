"""The loop, wired up.

This is the only place where the database, the progression rules and the
recogniser meet. The rules stay pure and the queries stay plain; everything that
has to know about both lives here, in one file you can read top to bottom.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from progression import (
    AttemptResult,
    Catalogue,
    Location,
    Position,
    assemble,
    decide,
    resize,
)

from . import db
from .grading import Grade, Verdict, grade
from .recognition import Recogniser


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


@dataclass
class Service:
    database: db.Database
    catalogue: Catalogue
    recogniser: Recogniser
    confidence_threshold: float = 0.80

    # -- arriving ----------------------------------------------------------

    def check_in(self, badge_code: str, tablet_id: str | None = None) -> dict[str, Any]:
        """A badge held up to the camera. The scan also takes the tablet."""
        with self.database.connection() as conn:
            student = db.student_by_badge(conn, badge_code)
            if student is None:
                raise NotFound("no student holds that badge")

            db.check_in(conn, student.id, tablet_id)
            corrections = db.open_corrections(conn, student.id)

            return {
                "student_id": student.id,
                "name": student.full_name,
                "needs_calibration": not student.calibrated,
                "assignment": self._assignment(conn, student, Location.CENTRE),
                "corrections_waiting": len(corrections),
            }

    def calibrate(self, student_id: str, samples: dict[str, Any]) -> dict[str, Any]:
        """The first-day baseline: 0 through 10, in the student's own hand.

        It runs to 10 because 10 is the most common answer in 2A and its only
        two-digit one, so a calibration stopping at 9 would never once exercise
        the case the recogniser most has to get right.
        """
        expected = {str(n) for n in range(11)}
        missing = expected - set(samples)
        if missing:
            raise Conflict(f"calibration needs 0 to 10; missing {sorted(missing, key=int)}")

        with self.database.connection() as conn:
            if db.student_by_id(conn, student_id) is None:
                raise NotFound("no such student")
            db.save_calibration(conn, student_id, samples)
        return {"calibrated": True, "digits": sorted(expected, key=int)}

    # -- the work ----------------------------------------------------------

    def assignment(self, student_id: str, location: Location) -> dict[str, Any]:
        with self.database.connection() as conn:
            student = db.student_by_id(conn, student_id)
            if student is None:
                raise NotFound("no such student")
            return self._assignment(conn, student, location)

    def _assignment(self, conn, student: db.Student, location: Location) -> dict[str, Any]:
        """The packet the student is on. Never a choice — always a statement.

        The page comes from where they are in the level and the size from the
        sizing rule. A child who can pick their own page can avoid the work they
        find hard, and the method rests on them not being able to.
        """
        packet = assemble(student.position, self.catalogue, location)
        packet_id = db.find_or_create_packet(conn, student.id, packet)
        problems = db.page_problems(conn, packet.level, packet.start_page, packet.page_count)

        pages: dict[int, list[dict[str, Any]]] = {}
        for problem in problems:
            pages.setdefault(problem["page_number"], []).append(
                {k: v for k, v in problem.items() if k != "page_number"}
            )

        return {
            "packet_id": packet_id,
            "level": packet.level,
            "start_page": packet.start_page,
            "end_page": packet.end_page,
            "page_count": packet.page_count,
            "problem_count": packet.problem_count,
            "intended_for": packet.intended_for.value,
            "pages": [
                {"page_number": number, "problems": pages[number]} for number in sorted(pages)
            ],
        }

    def start_attempt(self, student_id: str, location: Location) -> dict[str, Any]:
        with self.database.connection() as conn:
            student = db.student_by_id(conn, student_id)
            if student is None:
                raise NotFound("no such student")

            packet = assemble(student.position, self.catalogue, location)
            packet_id = db.find_or_create_packet(conn, student.id, packet)
            started = db.start_attempt(conn, student.id, packet_id, location)
            return {"attempt_id": started["id"], "attempt_number": started["attempt_number"],
                    "packet_id": packet_id}

    def submit_answer(
        self,
        attempt_id: str,
        problem_id: str,
        ink: Sequence[Any],
        *,
        active_seconds: int = 0,
    ) -> dict[str, Any]:
        """One answer, recognised and graded server-side.

        The tablet sends ink and gets back a verdict. It never held the correct
        answer, so there is nothing on the device to cheat with and nothing to
        go stale when a page is re-graded against a better model later.
        """
        with self.database.connection() as conn:
            current = db.attempt(conn, attempt_id)
            if current is None:
                raise NotFound("no such attempt")
            if current["status"] == "graded":
                raise Conflict("that attempt is already graded; attempts are append-only")

            correct = db.correct_answer_for(conn, problem_id)
            if correct is None:
                raise NotFound("no such problem")

            previous = db.answer_for(conn, attempt_id, problem_id)
            rewrites = previous["rewrite_count"] if previous else 0

            profile = db.handwriting_profile(conn, str(current["student_id"]))
            reading = self.recogniser.read(ink, profile=profile)
            result = grade(
                reading,
                correct,
                rewrites_so_far=rewrites,
                threshold=self.confidence_threshold,
            )

            next_rewrites = rewrites + 1 if result.verdict is Verdict.ILLEGIBLE else rewrites
            answer_id = db.record_answer(
                conn,
                attempt_id=attempt_id,
                problem_id=problem_id,
                ink=ink,
                recognised_value=result.value,
                confidence=result.confidence,
                verdict=result.verdict.value,
                rewrite_count=min(next_rewrites, 2),
                active_seconds=active_seconds,
            )
            db.add_active_seconds(conn, attempt_id, active_seconds)

            if result.verdict is Verdict.WRONG:
                db.add_correction(conn, str(current["student_id"]), answer_id)

            if result.accepted_as_written:
                db.add_legibility_note(
                    conn,
                    str(current["student_id"]),
                    correct,
                    "Accepted as written after two rewrites. Worth a little practice; "
                    "it does not affect the score.",
                )

            return {
                "answer_id": answer_id,
                "verdict": result.verdict.value,
                "message": result.message,
                "needs_review": result.needs_review,
                "rewrites_used": min(next_rewrites, 2),
                "accepted_as_written": result.accepted_as_written,
            }

    def submit_attempt(self, attempt_id: str, *, today: date | None = None) -> dict[str, Any]:
        """Grade the packet and move the student.

        The system decides. Nothing here asks a facilitator to rule on anything —
        it tells them when to go and teach, which is what keeps one person
        covering thirty children.
        """
        with self.database.connection() as conn:
            current = db.attempt(conn, attempt_id)
            if current is None:
                raise NotFound("no such attempt")
            if current["status"] == "graded":
                raise Conflict("that attempt is already graded; attempts are append-only")

            student = db.student_by_id(conn, str(current["student_id"]))
            if student is None:
                raise NotFound("no such student")

            # The gate must never be reachable with the packet half done. A
            # client that submits early would otherwise advance a student on the
            # strength of the problems they happened to answer, and the server
            # cannot take the tablet's word for having finished.
            answered = db.answered_count(conn, attempt_id)
            expected = current["problem_count"]
            if answered < expected:
                raise Conflict(
                    f"that packet is not finished: {answered} of {expected} answered"
                )

            wrong = db.wrong_count(conn, attempt_id)
            result = AttemptResult(
                packet=assemble(student.position, self.catalogue,
                                Location(current["location"])),
                attempt_number=current["attempt_number"],
                location=Location(current["location"]),
                wrong_count=wrong,
                active_seconds=current["active_seconds"],
            )

            outcome = decide(
                student.position,
                result,
                self.catalogue,
                recent_demotions=db.recent_demotions(conn, student.id),
                today=today,
            )

            db.finish_attempt(conn, attempt_id, wrong, outcome.passed)

            position = outcome.position
            events = list(outcome.events)

            # Sizing reads the pacing view, which only sees graded in-centre
            # attempts — so it has to run after the write above, not before.
            position, resize_events = resize(position, db.pacing_history(conn, student.id))
            events.extend(resize_events)

            if position != student.position:
                db.move_student(conn, student.id, position)
            if events:
                db.write_events(conn, student.id, events)

            return {
                "wrong_count": wrong,
                "problem_count": result.packet.problem_count,
                "passed": outcome.passed,
                "repeat": outcome.repeat,
                "flag_facilitator": outcome.flag_facilitator,
                "escalate_to_parents": outcome.escalate_to_parents,
                "note": outcome.note,
                "position": _position(position),
                "events": [
                    {"kind": e.kind.value, "note": e.note} for e in events
                ],
            }

    # -- corrections -------------------------------------------------------

    def corrections(self, student_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            return db.open_corrections(conn, student_id)

    def resolve_correction(self, correction_id: str) -> dict[str, Any]:
        with self.database.connection() as conn:
            db.set_correction_status(conn, correction_id, "resolved")
        return {"status": "resolved"}

    def close_homework(self, student_id: str) -> dict[str, Any]:
        """The child stops for the night with work outstanding.

        Allowed, logged, and in tonight's email. Nothing disappears quietly and
        no child is trapped at bedtime.
        """
        with self.database.connection() as conn:
            skipped = db.skip_open_corrections(conn, student_id)
            remaining = db.open_corrections(conn, student_id)
        return {"skipped": skipped, "still_outstanding": len(remaining)}

    def cancel_backlog(self, student_id: str, staff_id: str) -> dict[str, Any]:
        """A facilitator clears the pile, which drops the student a packet.

        Not an administrative tidy-up. A backlog that size means the material was
        too hard, so the honest response is to move the child back rather than to
        make the queue disappear. This is the second demotion path, and it writes
        to the same history as the first.
        """
        from progression import Correction, CorrectionStatus
        from progression import cancel_backlog as decide_backlog

        with self.database.connection() as conn:
            student = db.student_by_id(conn, student_id)
            if student is None:
                raise NotFound("no such student")

            outstanding = db.open_corrections(conn, student_id)
            if not outstanding:
                raise Conflict("there is no backlog to cancel")

            queue = [
                Correction(answer_id=c["id"], status=CorrectionStatus(c["status"]))
                for c in outstanding
            ]
            _, outcome = decide_backlog(student.position, queue, self.catalogue)

            db.cancel_open_corrections(conn, student_id, staff_id)
            db.move_student(conn, student_id, outcome.position)
            db.write_events(conn, student_id, outcome.events, triggered_by=staff_id)

            return {
                "cancelled": len(outstanding),
                "position": _position(outcome.position),
                "note": outcome.note,
            }

    # -- facilitator -------------------------------------------------------

    def override(self, answer_id: str, value: str, staff_id: str) -> dict[str, Any]:
        """A person reads the ink and says what it is.

        Always wins over the engine, and teaches it: every override lands in
        `recognition_corrections`, which tunes this student's profile, feeds the
        parent's legibility notes, and accumulates training data.
        """
        with self.database.connection() as conn:
            where = db.override_answer(conn, answer_id, value, staff_id)
            correct = db.correct_answer_for(conn, where["problem_id"])
            verdict = Verdict.CORRECT if value == correct else Verdict.WRONG
            db.set_answer_verdict(conn, answer_id, verdict.value)

            attempt_row = db.attempt(conn, where["attempt_id"])
            if verdict is Verdict.WRONG and attempt_row:
                db.add_correction(conn, str(attempt_row["student_id"]), answer_id)

            return {"verdict": verdict.value, "value": value}

    def room(self) -> list[dict[str, Any]]:
        with self.database.connection() as conn:
            return db.room(conn)


def _position(position: Position) -> dict[str, Any]:
    return {"level": position.level, "page": position.page, "packet_size": position.packet_size}
