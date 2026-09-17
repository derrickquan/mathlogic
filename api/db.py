"""Everything that touches PostgreSQL.

Plain SQL, one function per thing the service needs. No ORM: the schema is small,
its constraints and triggers are load-bearing, and hand-written statements keep
the relationship between the two readable.

Two habits worth keeping throughout:

  * The queries that feed the progression rules read the views the schema already
    provides. `packet_pacing` computes the in-centre minutes-per-page the sizing
    rule needs, and `student_events` holds the demotion history the escalation
    rule needs. Neither is reassembled here.
  * Nothing returns a correct answer to anything that will reach a tablet. The
    one function that reads answers off the curriculum is named so it is obvious
    which side of that line it is on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from progression import AttemptResult, Location, Packet, Position


class Database:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 8) -> None:
        self.pool = ConnectionPool(
            dsn, min_size=min_size, max_size=max_size, kwargs={"row_factory": dict_row}, open=True
        )

    def close(self) -> None:
        self.pool.close()

    def connection(self):
        return self.pool.connection()


# ---------------------------------------------------------------------------
# People and check-in
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Student:
    id: str
    full_name: str
    parent_id: str
    position: Position
    calibrated: bool


def student_by_badge(conn: psycopg.Connection, code: str) -> Student | None:
    row = conn.execute(
        """
        SELECT s.id, s.full_name, s.parent_id, s.current_page, s.packet_size,
               l.name AS level,
               (hp.calibrated_at IS NOT NULL) AS calibrated
        FROM badges b
        JOIN students s ON s.id = b.student_id
        JOIN levels   l ON l.id = s.current_level_id
        LEFT JOIN handwriting_profiles hp ON hp.student_id = s.id
        WHERE b.code = %s AND b.revoked_at IS NULL AND s.withdrawn_on IS NULL
        """,
        (code,),
    ).fetchone()
    return _student(row) if row else None


def student_by_id(conn: psycopg.Connection, student_id: str) -> Student | None:
    row = conn.execute(
        """
        SELECT s.id, s.full_name, s.parent_id, s.current_page, s.packet_size,
               l.name AS level,
               (hp.calibrated_at IS NOT NULL) AS calibrated
        FROM students s
        JOIN levels l ON l.id = s.current_level_id
        LEFT JOIN handwriting_profiles hp ON hp.student_id = s.id
        WHERE s.id = %s AND s.withdrawn_on IS NULL
        """,
        (student_id,),
    ).fetchone()
    return _student(row) if row else None


def _student(row: dict[str, Any]) -> Student:
    return Student(
        id=str(row["id"]),
        full_name=row["full_name"],
        parent_id=str(row["parent_id"]),
        position=Position(row["level"], row["current_page"], row["packet_size"]),
        calibrated=bool(row["calibrated"]),
    )


def check_in(conn: psycopg.Connection, student_id: str, tablet_id: str | None) -> str:
    row = conn.execute(
        """
        INSERT INTO check_ins (student_id, tablet_id) VALUES (%s, %s) RETURNING id
        """,
        (student_id, tablet_id),
    ).fetchone()
    return str(row["id"])


def save_calibration(conn: psycopg.Connection, student_id: str, samples: dict[str, Any]) -> None:
    """The first-day baseline. Also the row the passive updates later build on."""
    conn.execute(
        """
        INSERT INTO handwriting_profiles (student_id, calibrated_at, digit_bias, updated_at)
        VALUES (%s, now(), %s, now())
        ON CONFLICT (student_id) DO UPDATE
            SET calibrated_at = now(), digit_bias = EXCLUDED.digit_bias, updated_at = now()
        """,
        (student_id, Jsonb({"calibration": samples})),
    )


def handwriting_profile(conn: psycopg.Connection, student_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT digit_bias FROM handwriting_profiles WHERE student_id = %s", (student_id,)
    ).fetchone()
    return dict(row["digit_bias"]) if row else {}


# ---------------------------------------------------------------------------
# Curriculum
# ---------------------------------------------------------------------------


def level_id(conn: psycopg.Connection, name: str) -> str:
    row = conn.execute("SELECT id FROM levels WHERE name = %s", (name,)).fetchone()
    if row is None:
        raise LookupError(f"no level named {name!r}")
    return str(row["id"])


def page_problems(
    conn: psycopg.Connection, level: str, start_page: int, page_count: int
) -> list[dict[str, Any]]:
    """Prompts only. **This is what the tablet is allowed to see.**

    Correct answers never leave the server, which is what makes offline work
    safe to capture and removes the cheating surface altogether.
    """
    rows = conn.execute(
        """
        SELECT p.page_number, pr.id, pr.position, pr.prompt, pr.answer_shape
        FROM problems pr
        JOIN pages  p ON p.id = pr.page_id
        JOIN levels l ON l.id = p.level_id
        WHERE l.name = %s AND p.page_number BETWEEN %s AND %s
        ORDER BY p.page_number, pr.position
        """,
        (level, start_page, start_page + page_count - 1),
    ).fetchall()
    return [
        {
            "page_number": r["page_number"],
            "problem_id": str(r["id"]),
            "position": r["position"],
            "prompt": r["prompt"],
            "answer_shape": r["answer_shape"],
        }
        for r in rows
    ]


def correct_answer_for(conn: psycopg.Connection, problem_id: str) -> str | None:
    """Server-side only. Never serialise the result into a client response."""
    row = conn.execute(
        "SELECT correct_answer FROM problems WHERE id = %s", (problem_id,)
    ).fetchone()
    return row["correct_answer"] if row else None


# ---------------------------------------------------------------------------
# Packets and attempts
# ---------------------------------------------------------------------------


def find_or_create_packet(
    conn: psycopg.Connection,
    student_id: str,
    packet: Packet,
    *,
    due_on: date | None = None,
) -> str:
    """One packet row per assignment, reused across repeats.

    A student repeating a packet meets the same pages, so it is the same packet
    with a second attempt on it — not a new assignment. That is also what makes
    "three attempts, 40% faster each time" answerable from the attempts table.
    """
    row = conn.execute(
        """
        SELECT pk.id FROM packets pk
        JOIN levels l ON l.id = pk.level_id
        WHERE pk.student_id = %s AND l.name = %s
          AND pk.start_page = %s AND pk.page_count = %s AND pk.intended_for = %s
        ORDER BY pk.assigned_at DESC
        LIMIT 1
        """,
        (student_id, packet.level, packet.start_page, packet.page_count,
         packet.intended_for.value),
    ).fetchone()
    if row:
        return str(row["id"])

    row = conn.execute(
        """
        INSERT INTO packets
            (student_id, level_id, start_page, page_count, intended_for, due_on, problem_count)
        VALUES (%s, (SELECT id FROM levels WHERE name = %s), %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (student_id, packet.level, packet.start_page, packet.page_count,
         packet.intended_for.value, due_on, packet.problem_count),
    ).fetchone()
    return str(row["id"])


def open_attempt(conn: psycopg.Connection, student_id: str, packet_id: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id, attempt_number, active_seconds
        FROM attempts
        WHERE student_id = %s AND packet_id = %s AND status = 'in_progress'
        ORDER BY started_at DESC LIMIT 1
        """,
        (student_id, packet_id),
    ).fetchone()


def start_attempt(
    conn: psycopg.Connection, student_id: str, packet_id: str, location: Location
) -> dict[str, Any]:
    existing = open_attempt(conn, student_id, packet_id)
    if existing:
        return {"id": str(existing["id"]), "attempt_number": existing["attempt_number"]}

    row = conn.execute(
        """
        INSERT INTO attempts (student_id, packet_id, attempt_number, location)
        SELECT %s, %s, COALESCE(MAX(attempt_number), 0) + 1, %s
        FROM attempts WHERE packet_id = %s
        RETURNING id, attempt_number
        """,
        (student_id, packet_id, location.value, packet_id),
    ).fetchone()
    return {"id": str(row["id"]), "attempt_number": row["attempt_number"]}


def attempt(conn: psycopg.Connection, attempt_id: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT a.id, a.student_id, a.packet_id, a.attempt_number, a.location, a.status,
               a.active_seconds, pk.problem_count, pk.start_page, pk.page_count,
               l.name AS level
        FROM attempts a
        JOIN packets pk ON pk.id = a.packet_id
        JOIN levels  l  ON l.id = pk.level_id
        WHERE a.id = %s
        """,
        (attempt_id,),
    ).fetchone()


def record_answer(
    conn: psycopg.Connection,
    *,
    attempt_id: str,
    problem_id: str,
    ink: Sequence[Any],
    recognised_value: str | None,
    confidence: float | None,
    verdict: str,
    rewrite_count: int,
    active_seconds: int,
) -> str:
    """Store the answer with its raw ink.

    Ink is kept permanently and as strokes, not a bitmap: models improve and
    history can be re-graded against a better one, and this plus the override
    table is a labelled corpus of children's handwriting that no competitor
    starting fresh will have.
    """
    row = conn.execute(
        """
        INSERT INTO answers
            (attempt_id, problem_id, ink, recognised_value, confidence, verdict,
             rewrite_count, active_seconds)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (attempt_id, problem_id) DO UPDATE SET
            ink              = EXCLUDED.ink,
            recognised_value = EXCLUDED.recognised_value,
            confidence       = EXCLUDED.confidence,
            verdict          = EXCLUDED.verdict,
            rewrite_count    = EXCLUDED.rewrite_count,
            active_seconds   = answers.active_seconds + EXCLUDED.active_seconds,
            answered_at      = now()
        RETURNING id
        """,
        (attempt_id, problem_id, Jsonb(list(ink)), recognised_value, confidence, verdict,
         rewrite_count, active_seconds),
    ).fetchone()
    return str(row["id"])


def answer_for(conn: psycopg.Connection, attempt_id: str, problem_id: str) -> dict[str, Any] | None:
    return conn.execute(
        """
        SELECT id, recognised_value, confidence, verdict, rewrite_count, override_value
        FROM answers WHERE attempt_id = %s AND problem_id = %s
        """,
        (attempt_id, problem_id),
    ).fetchone()


def add_active_seconds(conn: psycopg.Connection, attempt_id: str, seconds: int) -> None:
    conn.execute(
        "UPDATE attempts SET active_seconds = active_seconds + %s WHERE id = %s AND status <> 'graded'",
        (seconds, attempt_id),
    )


def answered_count(conn: psycopg.Connection, attempt_id: str) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM answers WHERE attempt_id = %s", (attempt_id,)
    ).fetchone()
    return int(row["n"])


def wrong_count(conn: psycopg.Connection, attempt_id: str) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM answers WHERE attempt_id = %s AND verdict = 'wrong'",
        (attempt_id,),
    ).fetchone()
    return int(row["n"])


def finish_attempt(conn: psycopg.Connection, attempt_id: str, wrong: int, passed: bool) -> None:
    """The one and only write that grades an attempt.

    A trigger refuses any later update, so this runs once. Any code path that
    tries to rewrite a graded attempt is a bug and the database says so.
    """
    conn.execute(
        """
        UPDATE attempts
        SET status = 'graded', submitted_at = COALESCE(submitted_at, now()),
            graded_at = now(), wrong_count = %s, passed = %s
        WHERE id = %s
        """,
        (wrong, passed, attempt_id),
    )


# ---------------------------------------------------------------------------
# What the progression rules need to be handed
# ---------------------------------------------------------------------------


def pacing_history(conn: psycopg.Connection, student_id: str, limit: int = 3) -> list[AttemptResult]:
    """The last in-centre packets, from the view the schema already provides.

    `packet_pacing` filters to graded in-centre attempts and computes
    minutes-per-page, which is exactly the sizing rule's input. Returned oldest
    first because that is the order the rule reads them in.
    """
    rows = conn.execute(
        """
        SELECT pp.packet_id, pp.active_seconds, pp.page_count,
               pk.problem_count, pk.start_page, l.name AS level
        FROM packet_pacing pp
        JOIN packets pk ON pk.id = pp.packet_id
        JOIN levels  l  ON l.id = pk.level_id
        WHERE pp.student_id = %s AND pp.recency <= %s
        ORDER BY pp.recency DESC
        """,
        (student_id, limit),
    ).fetchall()

    return [
        AttemptResult(
            packet=Packet(
                level=r["level"],
                start_page=r["start_page"],
                page_count=r["page_count"],
                problem_count=r["problem_count"],
                intended_for=Location.CENTRE,
            ),
            attempt_number=1,
            location=Location.CENTRE,
            wrong_count=0,
            active_seconds=r["active_seconds"],
        )
        for r in rows
    ]


def recent_demotions(conn: psycopg.Connection, student_id: str, within_days: int = 60) -> list[date]:
    """Both demotion paths, from one history.

    Packet failure and a cancelled backlog write the same kind of row, which is
    what lets repeated drops read as one pattern rather than two unrelated ones.
    """
    rows = conn.execute(
        """
        SELECT occurred_at::date AS on_date
        FROM student_events
        WHERE student_id = %s
          AND kind IN ('demoted_failure', 'demoted_backlog')
          AND occurred_at > now() - make_interval(days => %s)
        ORDER BY occurred_at
        """,
        (student_id, within_days),
    ).fetchall()
    return [r["on_date"] for r in rows]


def move_student(conn: psycopg.Connection, student_id: str, position: Position) -> None:
    conn.execute(
        """
        UPDATE students
        SET current_level_id = (SELECT id FROM levels WHERE name = %s),
            current_page = %s,
            packet_size = %s
        WHERE id = %s
        """,
        (position.level, position.page, position.packet_size, student_id),
    )


def write_events(conn: psycopg.Connection, student_id: str, events: Iterable[Any],
                 triggered_by: str | None = None) -> None:
    for event in events:
        conn.execute(
            """
            INSERT INTO student_events
                (student_id, kind, from_level_id, from_page, to_level_id, to_page,
                 triggered_by, note)
            VALUES (
                %s, %s,
                (SELECT id FROM levels WHERE name = %s), %s,
                (SELECT id FROM levels WHERE name = %s), %s,
                %s, %s
            )
            """,
            (
                student_id,
                event.kind.value,
                event.from_position.level if event.from_position else None,
                event.from_position.page if event.from_position else None,
                event.to_position.level if event.to_position else None,
                event.to_position.page if event.to_position else None,
                triggered_by,
                event.note,
            ),
        )


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


def add_correction(conn: psycopg.Connection, student_id: str, answer_id: str) -> None:
    conn.execute(
        """
        INSERT INTO corrections (student_id, answer_id) VALUES (%s, %s)
        ON CONFLICT (answer_id) DO NOTHING
        """,
        (student_id, answer_id),
    )


def open_corrections(conn: psycopg.Connection, student_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.id, c.status, c.created_at::date AS created_on, c.skipped_at::date AS skipped_on,
               pr.prompt, pr.id AS problem_id, p.page_number, a.recognised_value, a.override_value
        FROM corrections c
        JOIN answers  a  ON a.id = c.answer_id
        JOIN problems pr ON pr.id = a.problem_id
        JOIN pages    p  ON p.id = pr.page_id
        WHERE c.student_id = %s AND c.status IN ('pending', 'skipped')
        ORDER BY c.created_at
        """,
        (student_id,),
    ).fetchall()
    return [
        {
            "id": str(r["id"]),
            "status": r["status"],
            "created_on": r["created_on"],
            "skipped_on": r["skipped_on"],
            "problem_id": str(r["problem_id"]),
            "prompt": r["prompt"],
            "page_number": r["page_number"],
            "wrote": r["override_value"] or r["recognised_value"],
        }
        for r in rows
    ]


def set_correction_status(conn: psycopg.Connection, correction_id: str, status: str,
                          staff_id: str | None = None) -> None:
    columns = {
        "resolved": "status = 'resolved', resolved_at = now()",
        "skipped": "status = 'skipped', skipped_at = now()",
        "cancelled": "status = 'cancelled', cancelled_at = now(), cancelled_by = %s",
    }
    if status not in columns:
        raise ValueError(f"unknown correction status {status!r}")

    if status == "cancelled":
        conn.execute(f"UPDATE corrections SET {columns[status]} WHERE id = %s", (staff_id, correction_id))
    else:
        conn.execute(f"UPDATE corrections SET {columns[status]} WHERE id = %s", (correction_id,))


def skip_open_corrections(conn: psycopg.Connection, student_id: str) -> int:
    row = conn.execute(
        """
        UPDATE corrections SET status = 'skipped', skipped_at = now()
        WHERE student_id = %s AND status = 'pending'
        RETURNING id
        """,
        (student_id,),
    ).fetchall()
    return len(row)


def cancel_open_corrections(conn: psycopg.Connection, student_id: str, staff_id: str | None) -> int:
    rows = conn.execute(
        """
        UPDATE corrections SET status = 'cancelled', cancelled_at = now(), cancelled_by = %s
        WHERE student_id = %s AND status IN ('pending', 'skipped')
        RETURNING id
        """,
        (staff_id, student_id),
    ).fetchall()
    return len(rows)


# ---------------------------------------------------------------------------
# Facilitator
# ---------------------------------------------------------------------------


def override_answer(conn: psycopg.Connection, answer_id: str, value: str, staff_id: str) -> dict[str, Any]:
    """A facilitator says what the ink actually reads.

    Writes the override and the training row together. `recognition_corrections`
    does triple duty: per-student recognition tuning, legibility feedback for
    parents, and accumulated training data.
    """
    row = conn.execute(
        """
        UPDATE answers
        SET override_value = %s, overridden_by = %s, overridden_at = now()
        WHERE id = %s
        RETURNING attempt_id, problem_id, recognised_value
        """,
        (value, staff_id, answer_id),
    ).fetchone()
    if row is None:
        raise LookupError(f"no answer {answer_id}")

    conn.execute(
        """
        INSERT INTO recognition_corrections (student_id, answer_id, system_read, actual_value)
        SELECT a.student_id, %s, %s, %s FROM attempts a
        JOIN answers ans ON ans.attempt_id = a.id
        WHERE ans.id = %s
        """,
        (answer_id, row["recognised_value"], value, answer_id),
    )
    return {"attempt_id": str(row["attempt_id"]), "problem_id": str(row["problem_id"])}


def set_answer_verdict(conn: psycopg.Connection, answer_id: str, verdict: str) -> None:
    conn.execute("UPDATE answers SET verdict = %s WHERE id = %s", (verdict, answer_id))


def add_legibility_note(conn: psycopg.Connection, student_id: str, digit: str, observation: str) -> None:
    conn.execute(
        "INSERT INTO legibility_notes (student_id, digit, observation) VALUES (%s, %s, %s)",
        (student_id, digit, observation),
    )


def room(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM room_status ORDER BY checked_in_at").fetchall()
    return [
        {
            "student_id": str(r["student_id"]),
            "full_name": r["full_name"],
            "checked_in_at": r["checked_in_at"],
            "start_page": r["start_page"],
            "page_count": r["page_count"],
            "active_seconds": r["active_seconds"] or 0,
            "pending_review": r["pending_review"] or 0,
            "open_corrections": r["open_corrections"] or 0,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Accounts and sessions
# ---------------------------------------------------------------------------


def parent_by_email(conn: psycopg.Connection, email: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id, email, password_hash, full_name FROM parents WHERE email = %s", (email,)
    ).fetchone()


def staff_by_email(conn: psycopg.Connection, email: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id, email, password_hash, full_name FROM staff "
        "WHERE email = %s AND is_active",
        (email,),
    ).fetchone()


def children_of(conn: psycopg.Connection, parent_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT s.id, s.full_name, s.current_page, s.packet_size, l.name AS level
        FROM students s
        JOIN levels l ON l.id = s.current_level_id
        WHERE s.parent_id = %s AND s.withdrawn_on IS NULL
        ORDER BY s.full_name
        """,
        (parent_id,),
    ).fetchall()
    return [
        {
            "student_id": str(r["id"]),
            "name": r["full_name"],
            "level": r["level"],
            "page": r["current_page"],
            "packet_size": r["packet_size"],
        }
        for r in rows
    ]


def open_session(
    conn: psycopg.Connection,
    *,
    kind: str,
    token_hash: str,
    expires_in_seconds: int,
    parent_id: str | None = None,
    staff_id: str | None = None,
    student_id: str | None = None,
    unlocked_by: str | None = None,
    opened_with: str = "password",
) -> str:
    row = conn.execute(
        """
        INSERT INTO sessions
            (kind, token_hash, parent_id, staff_id, student_id, unlocked_by, opened_with,
             expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, now() + make_interval(secs => %s))
        RETURNING id
        """,
        (kind, token_hash, parent_id, staff_id, student_id, unlocked_by, opened_with,
         expires_in_seconds),
    ).fetchone()
    return str(row["id"])


def session_by_token_hash(conn: psycopg.Connection, token_hash: str) -> dict[str, Any] | None:
    """A live session, or nothing. Expiry and revocation are checked in the
    query so no caller can forget to."""
    return conn.execute(
        """
        SELECT id, kind, parent_id, staff_id, student_id, unlocked_by
        FROM sessions
        WHERE token_hash = %s AND revoked_at IS NULL AND expires_at > now()
        """,
        (token_hash,),
    ).fetchone()


def revoke_session(conn: psycopg.Connection, session_id: str) -> None:
    conn.execute(
        "UPDATE sessions SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
        (session_id,),
    )


def revoke_student_sessions(conn: psycopg.Connection, student_id: str) -> int:
    rows = conn.execute(
        """
        UPDATE sessions SET revoked_at = now()
        WHERE student_id = %s AND revoked_at IS NULL AND expires_at > now()
        RETURNING id
        """,
        (student_id,),
    ).fetchall()
    return len(rows)


def parent_owns(conn: psycopg.Connection, parent_id: str, student_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 AS ok FROM students WHERE id = %s AND parent_id = %s AND withdrawn_on IS NULL",
        (student_id, parent_id),
    ).fetchone()
    return row is not None


def student_of_attempt(conn: psycopg.Connection, attempt_id: str) -> str | None:
    row = conn.execute("SELECT student_id FROM attempts WHERE id = %s", (attempt_id,)).fetchone()
    return str(row["student_id"]) if row else None


def student_of_correction(conn: psycopg.Connection, correction_id: str) -> str | None:
    row = conn.execute(
        "SELECT student_id FROM corrections WHERE id = %s", (correction_id,)
    ).fetchone()
    return str(row["student_id"]) if row else None
