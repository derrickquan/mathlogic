-- ---------------------------------------------------------------------------
-- Invariant checks — run against a database with the schema applied and level
-- 2A loaded. Raises on the first failure, so a clean run means every assertion
-- below holds.
--
--   scripts/verify-db.sh
--
-- These are the invariants the product spec leans on. They are checked here
-- rather than trusted, because every one of them is the kind of thing that
-- quietly stops being true.
-- ---------------------------------------------------------------------------

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- The curriculum loaded correctly
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    n integer;
BEGIN
    SELECT count(*) INTO n FROM pages p JOIN levels l ON l.id = p.level_id WHERE l.name = '2A';
    IF n <> 200 THEN RAISE EXCEPTION 'expected 200 pages in 2A, found %', n; END IF;

    SELECT count(*) INTO n FROM pages p JOIN levels l ON l.id = p.level_id
    WHERE l.name = '2A' AND NOT p.published;
    IF n <> 0 THEN RAISE EXCEPTION '% pages of 2A are unpublished', n; END IF;

    SELECT count(*) INTO n FROM problems pr
    JOIN pages p ON p.id = pr.page_id JOIN levels l ON l.id = p.level_id
    WHERE l.name = '2A';
    IF n <> 4000 THEN RAISE EXCEPTION 'expected 4000 problems in 2A, found %', n; END IF;

    -- The answer key, recomputed independently of the generator that wrote it.
    SELECT count(*) INTO n FROM problems
    WHERE correct_answer
       <> (split_part(prompt, ' + ', 1)::int + split_part(prompt, ' + ', 2)::int)::text;
    IF n <> 0 THEN RAISE EXCEPTION '% problems have a wrong answer key', n; END IF;

    -- Addition within 10. A sum of 11 is silently teaching the next level.
    SELECT count(*) INTO n FROM problems WHERE correct_answer::int > 10;
    IF n <> 0 THEN RAISE EXCEPTION '% problems leave the level', n; END IF;

    SELECT count(*) INTO n FROM (
        SELECT page_id FROM problems GROUP BY page_id HAVING count(*) <> 20
    ) bad;
    IF n <> 0 THEN RAISE EXCEPTION '% pages do not have 20 problems', n; END IF;

    RAISE NOTICE 'curriculum: 200 pages, 4000 problems, every answer key correct';
END $$;

-- ---------------------------------------------------------------------------
-- Published pages are frozen
--
-- Each block does something that must be refused. If it succeeds, the block
-- raises its own failure; the handler re-raises that rather than swallowing it.
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    BEGIN
        UPDATE problems SET correct_answer = '99'
        WHERE id = (SELECT id FROM problems ORDER BY id LIMIT 1);
        RAISE EXCEPTION 'FAIL: edited a problem on a published page';
    EXCEPTION WHEN others THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    BEGIN
        DELETE FROM problems WHERE id = (SELECT id FROM problems ORDER BY id LIMIT 1);
        RAISE EXCEPTION 'FAIL: deleted a problem from a published page';
    EXCEPTION WHEN others THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    BEGIN
        INSERT INTO problems (page_id, position, prompt, correct_answer)
        SELECT id, 21, '1 + 1', '2' FROM pages ORDER BY id LIMIT 1;
        RAISE EXCEPTION 'FAIL: added a problem to a published page';
    EXCEPTION WHEN others THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    BEGIN
        UPDATE pages SET page_number = 999 WHERE page_number = 1;
        RAISE EXCEPTION 'FAIL: edited a published page';
    EXCEPTION WHEN others THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    BEGIN
        UPDATE pages SET published = false WHERE page_number = 1;
        RAISE EXCEPTION 'FAIL: unpublished a published page';
    EXCEPTION WHEN others THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    BEGIN
        DELETE FROM pages WHERE page_number = 1;
        RAISE EXCEPTION 'FAIL: deleted a published page';
    EXCEPTION WHEN others THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    RAISE NOTICE 'freeze: published pages and their problems reject every write';
END $$;

-- ---------------------------------------------------------------------------
-- The advancement gate arithmetic, from the spec: 100 allows 5, 30 allows 2,
-- 20 allows 1, and a short packet is never harsher than a long one.
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    n integer;
BEGIN
    IF allowed_wrong(100) <> 5 THEN RAISE EXCEPTION '100 problems should allow 5 wrong'; END IF;
    IF allowed_wrong(30) <> 2 THEN RAISE EXCEPTION '30 problems should allow 2 wrong'; END IF;
    IF allowed_wrong(20) <> 1 THEN RAISE EXCEPTION '20 problems should allow 1 wrong'; END IF;
    IF allowed_wrong(6) <> 1 THEN RAISE EXCEPTION 'a 6-problem packet should still allow 1'; END IF;

    -- Rounding up, so the shortest packets are not the strictest.
    FOR n IN 1..200 LOOP
        IF allowed_wrong(n) < 1 THEN
            RAISE EXCEPTION 'allowed_wrong(%) is below the minimum of 1', n;
        END IF;
        IF allowed_wrong(n)::numeric / n < 0.05 AND n > 1 THEN
            RAISE EXCEPTION 'allowed_wrong(%) is stricter than 95%%', n;
        END IF;
    END LOOP;

    RAISE NOTICE 'gate: allowed_wrong rounds up and never drops below 1';
END $$;

-- ---------------------------------------------------------------------------
-- Attempts are append-only
-- ---------------------------------------------------------------------------

DO $$
DECLARE
    parent_id  uuid;
    student    uuid;
    packet     uuid;
    attempt    uuid;
    level      uuid;
BEGIN
    SELECT id INTO level FROM levels WHERE name = '2A';

    INSERT INTO parents (email, password_hash, full_name)
    VALUES ('invariant-check@example.test', 'x', 'Check') RETURNING id INTO parent_id;

    INSERT INTO students (parent_id, full_name, current_level_id)
    VALUES (parent_id, 'Check Student', level) RETURNING id INTO student;

    INSERT INTO packets (student_id, level_id, start_page, page_count, intended_for, problem_count)
    VALUES (student, level, 1, 10, 'centre', 200) RETURNING id INTO packet;

    INSERT INTO attempts (student_id, packet_id, attempt_number, location, status, wrong_count, passed)
    VALUES (student, packet, 1, 'centre', 'graded', 3, true) RETURNING id INTO attempt;

    BEGIN
        UPDATE attempts SET wrong_count = 0 WHERE id = attempt;
        RAISE EXCEPTION 'FAIL: rewrote a graded attempt';
    EXCEPTION WHEN others THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    BEGIN
        DELETE FROM attempts WHERE id = attempt;
        RAISE EXCEPTION 'FAIL: deleted an attempt';
    EXCEPTION WHEN others THEN
        IF SQLERRM LIKE 'FAIL:%' THEN RAISE; END IF;
    END;

    RAISE NOTICE 'attempts: a graded attempt cannot be rewritten or deleted';
END $$;

\echo
\echo 'All invariant checks passed.'
