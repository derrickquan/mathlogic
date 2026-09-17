"""A real PostgreSQL for the integration tests.

The schema's triggers and constraints are load-bearing — append-only attempts,
frozen published pages — so testing the server against a fake would test the
wrong thing. This stands up a throwaway cluster once per session, applies the
schema, loads level 2A, and tears it down afterwards.

If no Postgres server binary is present the integration tests skip rather than
fail: the pure-rule tests still run anywhere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: scrypt is deliberately slow, so hash the fixtures' passwords once for the
#: whole session rather than once per test.
PARENT_PASSWORD = "correct horse battery staple"
STAFF_PASSWORD = "a facilitator's password"


def _hashes():
    from api.auth import hash_password

    if not hasattr(_hashes, "cached"):
        _hashes.cached = (hash_password(PARENT_PASSWORD), hash_password(STAFF_PASSWORD))
    return _hashes.cached

# The Unix socket path has a 107-byte limit, so this cannot live under a long
# temp directory.
WORK = Path("/tmp/mathlogic-tests")
PORT = 5441
DB = "mathlogic_test"


def _pg_bin() -> Path | None:
    found = shutil.which("initdb")
    if found:
        return Path(found).parent
    candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True)
    for candidate in candidates:
        if (candidate / "initdb").exists():
            return candidate
    return None


def _tail(path: Path, lines: int = 20) -> str:
    try:
        return "\n" + "\n".join(path.read_text(encoding="utf-8").splitlines()[-lines:])
    except OSError:
        return ""


def _run(command: str, *, as_postgres: bool) -> subprocess.CompletedProcess:
    if as_postgres:
        command = f"su postgres -c {command!r}"
    return subprocess.run(command, shell=True, capture_output=True, text=True)


@pytest.fixture(scope="session")
def dsn() -> str:
    pg_bin = _pg_bin()
    if pg_bin is None:
        pytest.skip("no PostgreSQL server binary; integration tests need one")

    as_postgres = os.geteuid() == 0
    if as_postgres and subprocess.run("id postgres", shell=True, capture_output=True).returncode:
        pytest.skip("running as root with no postgres account to drop to")

    if WORK.exists():
        _run(f"{pg_bin}/pg_ctl -D {WORK}/data stop -m immediate", as_postgres=as_postgres)
        shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "data").mkdir(parents=True)
    (WORK / "sock").mkdir(parents=True)

    build = WORK / "build"
    subprocess.run(
        ["python3", "-m", "curriculum", "generate", "2A", "--out", str(build)],
        cwd=REPO, check=True, capture_output=True,
    )
    shutil.copy(REPO / "docs" / "schema.sql", WORK / "schema.sql")
    shutil.copy(build / "2A.sql", WORK / "2A.sql")

    if as_postgres:
        subprocess.run(f"chown -R postgres:postgres {WORK}", shell=True, check=True)

    init = _run(f"{pg_bin}/initdb -D {WORK}/data -A trust -U postgres", as_postgres=as_postgres)
    assert init.returncode == 0, init.stderr

    # Socket-only, on our own port. Written into the config rather than passed
    # through -o, because nesting quotes inside `su -c` is a losing game.
    with (WORK / "data" / "postgresql.conf").open("a", encoding="utf-8") as conf:
        conf.write(
            f"\nlisten_addresses = ''\n"
            f"unix_socket_directories = '{WORK}/sock'\n"
            f"port = {PORT}\n"
        )

    start = _run(f"{pg_bin}/pg_ctl -D {WORK}/data -w -l {WORK}/data/log start",
                 as_postgres=as_postgres)
    assert start.returncode == 0, start.stderr + _tail(WORK / "data" / "log")

    psql = f"{pg_bin}/psql -h {WORK}/sock -p {PORT} -U postgres -v ON_ERROR_STOP=1 -q"
    for command in (
        f"{psql} -c 'CREATE DATABASE {DB};'",
        f"{psql} -d {DB} -f {WORK}/schema.sql",
        f"{psql} -d {DB} -f {WORK}/2A.sql",
    ):
        done = _run(command, as_postgres=as_postgres)
        assert done.returncode == 0, done.stderr

    url = f"postgresql://postgres@/{DB}?host={WORK}/sock&port={PORT}"
    yield url

    _run(f"{pg_bin}/pg_ctl -D {WORK}/data stop -m immediate", as_postgres=as_postgres)
    shutil.rmtree(WORK, ignore_errors=True)


@pytest.fixture
def database(dsn):
    from api import db as db_module

    database = db_module.Database(dsn)
    yield database
    database.close()


@pytest.fixture
def clean(database):
    """A fresh student on page 41 with nothing behind them.

    The curriculum is left alone — its pages are published and frozen, and
    reloading them between tests is exactly what the schema refuses.
    """
    parent_hash, staff_hash = _hashes()

    with database.connection() as conn:
        for table in (
            "sessions", "recognition_corrections", "legibility_notes", "corrections",
            "answers", "student_events", "check_ins", "handwriting_profiles",
        ):
            conn.execute(f"DELETE FROM {table}")
        # attempts refuse DELETE by design, so step past the trigger to reset.
        conn.execute("ALTER TABLE attempts DISABLE TRIGGER attempts_no_delete_trg")
        conn.execute("DELETE FROM attempts")
        conn.execute("ALTER TABLE attempts ENABLE TRIGGER attempts_no_delete_trg")
        conn.execute("DELETE FROM packets")
        conn.execute("DELETE FROM students")
        conn.execute("DELETE FROM parents")
        conn.execute("DELETE FROM staff")

        parent = conn.execute(
            "INSERT INTO parents (email, password_hash, full_name) "
            "VALUES ('parent@example.test', %s, 'A Parent') RETURNING id",
            (parent_hash,),
        ).fetchone()["id"]
        staff = conn.execute(
            "INSERT INTO staff (email, password_hash, full_name) "
            "VALUES ('priya@example.test', %s, 'Priya') RETURNING id",
            (staff_hash,),
        ).fetchone()["id"]
        student = conn.execute(
            """
            INSERT INTO students (parent_id, full_name, current_level_id, current_page, packet_size)
            VALUES (%s, 'Amara O.', (SELECT id FROM levels WHERE name = '2A'), 41, 5)
            RETURNING id
            """,
            (parent,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO badges (student_id, code) VALUES (%s, 'BADGE-AMARA')", (student,)
        )

        # A second family, so "not your child" can actually be tested.
        other_parent = conn.execute(
            "INSERT INTO parents (email, password_hash, full_name) "
            "VALUES ('other@example.test', %s, 'Another Parent') RETURNING id",
            (parent_hash,),
        ).fetchone()["id"]
        other_student = conn.execute(
            """
            INSERT INTO students (parent_id, full_name, current_level_id, current_page, packet_size)
            VALUES (%s, 'Theo B.', (SELECT id FROM levels WHERE name = '2A'), 61, 10)
            RETURNING id
            """,
            (other_parent,),
        ).fetchone()["id"]
        conn.execute(
            "INSERT INTO badges (student_id, code) VALUES (%s, 'BADGE-THEO')", (other_student,)
        )

    return {
        "student_id": str(student),
        "staff_id": str(staff),
        "parent_id": str(parent),
        "badge": "BADGE-AMARA",
        "parent_email": "parent@example.test",
        "parent_password": PARENT_PASSWORD,
        "staff_email": "priya@example.test",
        "staff_password": STAFF_PASSWORD,
        "other_student_id": str(other_student),
        "other_parent_email": "other@example.test",
        "other_badge": "BADGE-THEO",
    }


@pytest.fixture
def service(database, clean):
    from api.recognition import DeclaredValueRecogniser
    from api.service import Service
    from progression import from_templates

    return Service(
        database=database,
        catalogue=from_templates(),
        recogniser=DeclaredValueRecogniser(),
    )
