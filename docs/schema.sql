-- ============================================================================
-- MathLogic — database schema
-- PostgreSQL 14+
--
-- Two invariants this schema enforces rather than trusts:
--   1. attempts are append-only (trigger below blocks UPDATE)
--   2. pages and problems are frozen once published (trigger below)
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";    -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";      -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS "btree_gist";  -- uuid '=' inside the EXCLUDE below

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------

CREATE TYPE answer_verdict     AS ENUM ('correct', 'wrong', 'illegible');
CREATE TYPE attempt_status     AS ENUM ('in_progress', 'submitted', 'graded');
CREATE TYPE work_location      AS ENUM ('centre', 'home');
CREATE TYPE correction_status  AS ENUM ('pending', 'resolved', 'skipped', 'cancelled');
CREATE TYPE student_event_kind AS ENUM ('advanced', 'demoted_failure', 'demoted_backlog',
                                        'packet_size_up', 'packet_size_down', 'placed');

-- ---------------------------------------------------------------------------
-- People and accounts
-- ---------------------------------------------------------------------------

-- The parent holds the account. Students have no credentials of their own;
-- they check in at the centre with a badge and at home via a parent unlock.
CREATE TABLE parents (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           citext UNIQUE NOT NULL,
    password_hash   text NOT NULL,
    full_name       text NOT NULL,
    phone           text,
    -- Payment authorisation captured at enrolment; needed to charge for an
    -- unreturned tablet (replacement + 10%) after a family leaves.
    payment_method_ref text,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE staff (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email           citext UNIQUE NOT NULL,
    password_hash   text NOT NULL,
    full_name       text NOT NULL,
    is_active       boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE students (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id       uuid NOT NULL REFERENCES parents(id) ON DELETE RESTRICT,
    full_name       text NOT NULL,
    date_of_birth   date,
    enrolled_on     date NOT NULL DEFAULT CURRENT_DATE,
    withdrawn_on    date,

    -- Position in the curriculum. current_page is the next page to be worked,
    -- NOT a packet pointer: packets are generated at runtime (see packets).
    current_level_id uuid NOT NULL,
    current_page     integer NOT NULL DEFAULT 1 CHECK (current_page >= 1),

    -- Packet size tracks the student, not the level. Adjusted by the sizing
    -- rule: 3 consecutive in-centre packets over 45 min drops 10 -> 5;
    -- 3 consecutive under 20 min raises 5 -> 10.
    packet_size      integer NOT NULL DEFAULT 10 CHECK (packet_size IN (5, 10)),

    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX students_parent_idx ON students(parent_id);
CREATE INDEX students_active_idx ON students(withdrawn_on) WHERE withdrawn_on IS NULL;

-- ---------------------------------------------------------------------------
-- Sessions
--
-- Three kinds, and the difference between them is the point.
--
--   parent   the account holder, on their own phone. Reports and history.
--   staff    a facilitator at the console. Short-lived: the console is a shared
--            machine in a room full of children and should not stay open
--            overnight.
--   student  the tablet, working. Opened either by a badge scan at the centre or
--            by a parent unlocking at home, and scoped to one student. It can
--            never reach the parent view: a child handed an unlocked tablet must
--            not be able to wander into their own scores and reports.
--
-- Tokens are opaque random strings; only their SHA-256 is stored, so the table
-- is useless to anyone who reads it.
-- ---------------------------------------------------------------------------

CREATE TYPE session_kind AS ENUM ('parent', 'staff', 'student');

CREATE TABLE sessions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            session_kind NOT NULL,
    token_hash      text UNIQUE NOT NULL,

    parent_id       uuid REFERENCES parents(id)  ON DELETE CASCADE,
    staff_id        uuid REFERENCES staff(id)    ON DELETE CASCADE,
    student_id      uuid REFERENCES students(id) ON DELETE CASCADE,

    -- For a student session: which parent unlocked it, when it was not a badge.
    unlocked_by     uuid REFERENCES parents(id) ON DELETE SET NULL,
    opened_with     text NOT NULL DEFAULT 'password',   -- password | badge | unlock

    created_at      timestamptz NOT NULL DEFAULT now(),
    expires_at      timestamptz NOT NULL,
    revoked_at      timestamptz,

    -- Exactly one subject, and it must be the one the kind names. Without this
    -- a student session could carry a parent_id and quietly become one.
    CONSTRAINT sessions_subject_matches_kind CHECK (
        (kind = 'parent'  AND parent_id  IS NOT NULL AND staff_id IS NULL AND student_id IS NULL) OR
        (kind = 'staff'   AND staff_id   IS NOT NULL AND parent_id IS NULL AND student_id IS NULL) OR
        (kind = 'student' AND student_id IS NOT NULL AND parent_id IS NULL AND staff_id IS NULL)
    )
);

CREATE INDEX sessions_live_idx ON sessions(expires_at)
    WHERE revoked_at IS NULL;

-- ---------------------------------------------------------------------------
-- Curriculum (canonical, frozen once published)
-- ---------------------------------------------------------------------------

CREATE TABLE levels (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                text UNIQUE NOT NULL,          -- '2A', 'B', ...
    sort_order          integer UNIQUE NOT NULL,
    description         text,
    default_packet_size integer NOT NULL DEFAULT 10 CHECK (default_packet_size IN (5, 10)),
    page_count          integer NOT NULL DEFAULT 200 CHECK (page_count > 0)
);

ALTER TABLE students
    ADD CONSTRAINT students_current_level_fkey
    FOREIGN KEY (current_level_id) REFERENCES levels(id);

-- Generator config per page band within a level. Seeded so a frozen page
-- can be regenerated byte-identically.
CREATE TABLE page_templates (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    level_id          uuid NOT NULL REFERENCES levels(id) ON DELETE CASCADE,
    page_from         integer NOT NULL CHECK (page_from >= 1),
    page_to           integer NOT NULL,
    problems_per_page integer NOT NULL CHECK (problems_per_page > 0),
    form              text NOT NULL,                   -- 'a + b = _'
    operands          jsonb NOT NULL DEFAULT '{}'::jsonb,
    constraints       jsonb NOT NULL DEFAULT '[]'::jsonb,
    seed              bigint NOT NULL,
    CHECK (page_to >= page_from),
    EXCLUDE USING gist (
        level_id WITH =,
        int4range(page_from, page_to, '[]') WITH &&
    )
);

CREATE TABLE pages (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    level_id        uuid NOT NULL REFERENCES levels(id) ON DELETE RESTRICT,
    page_number     integer NOT NULL CHECK (page_number >= 1),
    template_id     uuid REFERENCES page_templates(id),
    -- Once true the page is immutable: students may be repeating it, and a
    -- repeat must present identical problems.
    published       boolean NOT NULL DEFAULT false,
    published_at    timestamptz,
    UNIQUE (level_id, page_number)
);

CREATE TABLE problems (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id         uuid NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    position        integer NOT NULL CHECK (position >= 1),
    prompt          text NOT NULL,                     -- '7 + 2'
    correct_answer  text NOT NULL,                     -- '9'
    -- Shape the tablet should render and the recogniser should expect:
    -- 'integer', 'fraction', 'signed_integer', ...
    answer_shape    text NOT NULL DEFAULT 'integer',
    UNIQUE (page_id, position)
);

-- Freeze enforcement. A published page is immutable, and so are its problems:
-- students may be repeating it, and a repeat must present identical problems or
-- it is new work rather than practice. Publishing itself is the one permitted
-- transition, so the check is on the OLD row.
CREATE FUNCTION pages_frozen_when_published() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.published THEN
            RAISE EXCEPTION 'page % of level % is published and cannot be deleted',
                OLD.page_number, OLD.level_id;
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.published THEN
        RAISE EXCEPTION 'page % of level % is published and frozen: a student repeating a packet must meet the same problems',
            OLD.page_number, OLD.level_id;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER pages_frozen_when_published_trg
    BEFORE UPDATE OR DELETE ON pages
    FOR EACH ROW EXECUTE FUNCTION pages_frozen_when_published();

-- The same freeze, one level down. INSERT is blocked too: adding a twenty-first
-- problem to a published page changes it just as surely as editing one.
CREATE FUNCTION problems_frozen_when_page_published() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    frozen boolean;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        SELECT published INTO frozen FROM pages WHERE id = OLD.page_id;
        IF frozen THEN
            RAISE EXCEPTION 'page % is published: its problems are frozen', OLD.page_id;
        END IF;
    END IF;

    IF TG_OP <> 'DELETE' THEN
        SELECT published INTO frozen FROM pages WHERE id = NEW.page_id;
        IF frozen THEN
            RAISE EXCEPTION 'page % is published: its problems are frozen', NEW.page_id;
        END IF;
        RETURN NEW;
    END IF;

    RETURN OLD;
END;
$$;

CREATE TRIGGER problems_frozen_when_page_published_trg
    BEFORE INSERT OR UPDATE OR DELETE ON problems
    FOR EACH ROW EXECUTE FUNCTION problems_frozen_when_page_published();

-- ---------------------------------------------------------------------------
-- Packets — generated per student at runtime, not part of the curriculum
-- ---------------------------------------------------------------------------

CREATE TABLE packets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    level_id        uuid NOT NULL REFERENCES levels(id),
    start_page      integer NOT NULL CHECK (start_page >= 1),
    page_count      integer NOT NULL CHECK (page_count IN (5, 10)),
    intended_for    work_location NOT NULL,
    assigned_at     timestamptz NOT NULL DEFAULT now(),
    due_on          date,
    -- Denormalised at assignment time so the advancement gate does not have to
    -- recount, and so the gate is stable even if pages change later.
    problem_count   integer NOT NULL CHECK (problem_count > 0)
);

CREATE INDEX packets_student_idx ON packets(student_id, assigned_at DESC);

-- Allowed wrong answers = ceil(problems * 0.05), minimum 1.
-- Measured per problem rather than per packet so packet size does not change
-- how strict the gate is.
CREATE FUNCTION allowed_wrong(problem_count integer)
RETURNS integer
LANGUAGE sql IMMUTABLE AS $$
    SELECT GREATEST(1, CEIL(problem_count * 0.05)::integer);
$$;

-- ---------------------------------------------------------------------------
-- Attempts — APPEND-ONLY
-- ---------------------------------------------------------------------------

CREATE TABLE attempts (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    packet_id       uuid NOT NULL REFERENCES packets(id) ON DELETE RESTRICT,
    attempt_number  integer NOT NULL CHECK (attempt_number >= 1),
    location        work_location NOT NULL,
    status          attempt_status NOT NULL DEFAULT 'in_progress',

    started_at      timestamptz NOT NULL DEFAULT now(),
    submitted_at    timestamptz,
    graded_at       timestamptz,

    -- Pen-down time plus gaps under 90s. Accumulates across sessions, which
    -- is what the packet-sizing rule measures.
    active_seconds  integer NOT NULL DEFAULT 0 CHECK (active_seconds >= 0),

    wrong_count     integer,
    passed          boolean,

    UNIQUE (packet_id, attempt_number)
);

CREATE INDEX attempts_student_idx ON attempts(student_id, started_at DESC);

-- Append-only enforcement. Grading fills in results, so UPDATE is permitted
-- only while the row is not yet graded, and never on the identifying columns.
CREATE FUNCTION attempts_no_rewrite() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'graded' THEN
        RAISE EXCEPTION 'attempts are append-only: % is already graded', OLD.id;
    END IF;
    IF NEW.student_id     IS DISTINCT FROM OLD.student_id
    OR NEW.packet_id      IS DISTINCT FROM OLD.packet_id
    OR NEW.attempt_number IS DISTINCT FROM OLD.attempt_number
    OR NEW.started_at     IS DISTINCT FROM OLD.started_at THEN
        RAISE EXCEPTION 'attempt identity is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER attempts_no_rewrite_trg
    BEFORE UPDATE ON attempts
    FOR EACH ROW EXECUTE FUNCTION attempts_no_rewrite();

CREATE FUNCTION attempts_no_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'attempts are append-only: delete is not permitted';
END;
$$;

CREATE TRIGGER attempts_no_delete_trg
    BEFORE DELETE ON attempts
    FOR EACH ROW EXECUTE FUNCTION attempts_no_delete();

-- ---------------------------------------------------------------------------
-- Answers — raw ink is stored permanently
-- ---------------------------------------------------------------------------

CREATE TABLE answers (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id          uuid NOT NULL REFERENCES attempts(id) ON DELETE RESTRICT,
    problem_id          uuid NOT NULL REFERENCES problems(id) ON DELETE RESTRICT,

    -- Stroke data, not a bitmap. Kept permanently: models improve and history
    -- can be re-graded, and this plus recognition_corrections is a labelled
    -- corpus of children's handwritten digits.
    ink                 jsonb NOT NULL,

    recognised_value    text,
    confidence          numeric(4,3) CHECK (confidence BETWEEN 0 AND 1),
    verdict             answer_verdict,

    -- Rewrite ceiling is 2. After that the answer is accepted as-is and a
    -- legibility note is written instead of looping the child again.
    rewrite_count       integer NOT NULL DEFAULT 0 CHECK (rewrite_count BETWEEN 0 AND 2),

    active_seconds      integer NOT NULL DEFAULT 0,
    answered_at         timestamptz NOT NULL DEFAULT now(),

    -- Set when a facilitator overrides a low-confidence read.
    override_value      text,
    overridden_by       uuid REFERENCES staff(id),
    overridden_at       timestamptz,

    UNIQUE (attempt_id, problem_id)
);

CREATE INDEX answers_attempt_idx ON answers(attempt_id);
-- Facilitator review queue: low confidence, not yet overridden.
CREATE INDEX answers_review_idx ON answers(confidence)
    WHERE override_value IS NULL AND confidence IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Corrections — a persistent per-student queue, not a property of an attempt
-- ---------------------------------------------------------------------------

CREATE TABLE corrections (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    answer_id       uuid NOT NULL REFERENCES answers(id) ON DELETE RESTRICT,
    status          correction_status NOT NULL DEFAULT 'pending',

    created_at      timestamptz NOT NULL DEFAULT now(),
    skipped_at      timestamptz,
    resolved_at     timestamptz,
    -- Set when a facilitator clears an entire backlog, which also demotes
    -- the student: the backlog is read as a placement signal.
    cancelled_at    timestamptz,
    cancelled_by    uuid REFERENCES staff(id),

    UNIQUE (answer_id)
);

CREATE INDEX corrections_open_idx ON corrections(student_id, created_at)
    WHERE status IN ('pending', 'skipped');

-- ---------------------------------------------------------------------------
-- Recognition learning and legibility
-- ---------------------------------------------------------------------------

-- Every facilitator override lands here. Feeds per-student recognition
-- tuning, parent-facing legibility notes, and the training corpus.
CREATE TABLE recognition_corrections (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    answer_id       uuid NOT NULL REFERENCES answers(id) ON DELETE RESTRICT,
    system_read     text,
    actual_value    text NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX recognition_corrections_student_idx
    ON recognition_corrections(student_id, created_at DESC);

-- Baseline from the first-day calibration, then updated passively from
-- confirmed answers so it tracks handwriting as it matures.
CREATE TABLE handwriting_profiles (
    student_id      uuid PRIMARY KEY REFERENCES students(id) ON DELETE CASCADE,
    calibrated_at   timestamptz,
    -- Per-digit bias weights, e.g. {"4": {"confusable_with": ["9"], "weight": 0.7}}
    digit_bias      jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- Surfaced to parents as guidance. Never affects the maths score.
CREATE TABLE legibility_notes (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    digit           text NOT NULL,
    observation     text NOT NULL,
    noted_on        date NOT NULL DEFAULT CURRENT_DATE
);

-- ---------------------------------------------------------------------------
-- Progression history
-- ---------------------------------------------------------------------------

-- Both demotion paths write here, so repeated drops are visible as a pattern
-- rather than as isolated events.
CREATE TABLE student_events (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    kind            student_event_kind NOT NULL,
    from_level_id   uuid REFERENCES levels(id),
    from_page       integer,
    to_level_id     uuid REFERENCES levels(id),
    to_page         integer,
    triggered_by    uuid REFERENCES staff(id),   -- null when automatic
    note            text,
    occurred_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX student_events_idx ON student_events(student_id, occurred_at DESC);

-- ---------------------------------------------------------------------------
-- Hardware
-- ---------------------------------------------------------------------------

CREATE TABLE tablets (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    serial_number   text UNIQUE NOT NULL,
    asset_tag       text UNIQUE,
    assigned_to     uuid REFERENCES students(id) ON DELETE SET NULL,
    assigned_at     timestamptz,
    returned_at     timestamptz,
    condition_note  text
);

-- QR badge scanned at the tablet camera to check in. The scan also assigns
-- the tablet for that session.
CREATE TABLE badges (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    code            text UNIQUE NOT NULL,
    issued_at       timestamptz NOT NULL DEFAULT now(),
    revoked_at      timestamptz
);

CREATE TABLE check_ins (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    tablet_id       uuid REFERENCES tablets(id),
    checked_in_at   timestamptz NOT NULL DEFAULT now(),
    checked_out_at  timestamptz,
    -- Set when a facilitator checks a student in manually (forgotten badge).
    checked_in_by   uuid REFERENCES staff(id)
);

CREATE INDEX check_ins_open_idx ON check_ins(checked_in_at)
    WHERE checked_out_at IS NULL;

-- ---------------------------------------------------------------------------
-- Parent reporting — one email per night at 8:30pm, including "no work today"
-- ---------------------------------------------------------------------------

CREATE TABLE daily_reports (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id      uuid NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    report_date     date NOT NULL,
    body            jsonb NOT NULL,
    -- v1 queues for a facilitator glance before sending; once confidence data
    -- is solid this flips to automatic.
    reviewed_by     uuid REFERENCES staff(id),
    reviewed_at     timestamptz,
    sent_at         timestamptz,
    UNIQUE (student_id, report_date)
);

CREATE INDEX daily_reports_unsent_idx ON daily_reports(report_date)
    WHERE sent_at IS NULL;

-- ---------------------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------------------

-- Facilitator console: who is in the room, how long they have been working,
-- and what needs attention.
CREATE VIEW room_status AS
SELECT
    s.id                AS student_id,
    s.full_name,
    ci.checked_in_at,
    a.id                AS attempt_id,
    p.start_page,
    p.page_count,
    a.active_seconds,
    (SELECT count(*) FROM answers ans
       WHERE ans.attempt_id = a.id
         AND ans.override_value IS NULL
         AND ans.confidence < 0.80)          AS pending_review,
    (SELECT count(*) FROM corrections c
       WHERE c.student_id = s.id
         AND c.status IN ('pending', 'skipped')) AS open_corrections
FROM check_ins ci
JOIN students s   ON s.id = ci.student_id
LEFT JOIN attempts a ON a.student_id = s.id AND a.status = 'in_progress'
LEFT JOIN packets  p ON p.id = a.packet_id
WHERE ci.checked_out_at IS NULL;

-- Packet-sizing input: the last three in-centre attempts per student.
-- Only in-centre packets drive resizing; home conditions are uncontrolled.
CREATE VIEW packet_pacing AS
SELECT
    a.student_id,
    a.packet_id,
    a.active_seconds,
    p.page_count,
    a.active_seconds::numeric / NULLIF(p.page_count, 0) / 60 AS minutes_per_page,
    row_number() OVER (PARTITION BY a.student_id ORDER BY a.graded_at DESC) AS recency
FROM attempts a
JOIN packets p ON p.id = a.packet_id
WHERE a.location = 'centre' AND a.status = 'graded';
