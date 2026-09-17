#!/usr/bin/env bash
#
# Stand the whole thing up and walk a student through a session.
#
#   scripts/demo.sh
#
# Builds a throwaway PostgreSQL, applies the schema, loads level 2A, seeds two
# families and a facilitator, starts the server, and drives the loop over HTTP
# exactly as a tablet would. Removes everything afterwards.
#
# Needs a Postgres server binary (any 14+) and the server extras installed:
#   pip install -e '.[server,dev]'

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

WORK="${MATHLOGIC_DEMO_DIR:-/tmp/mathlogic-demo}"
PGPORT="${MATHLOGIC_DEMO_PGPORT:-5442}"
APPPORT="${MATHLOGIC_DEMO_PORT:-8111}"
DB=mathlogic_demo

find_pgbin() {
    if command -v initdb >/dev/null 2>&1; then dirname "$(command -v initdb)"; return; fi
    local candidate
    candidate="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1 || true)"
    if [[ -n "$candidate" && -x "$candidate/initdb" ]]; then echo "$candidate"; return; fi
    echo "no Postgres server binary found" >&2
    exit 1
}
PGBIN="$(find_pgbin)"

AS=""
if [[ "$(id -u)" -eq 0 ]]; then
    id postgres >/dev/null 2>&1 || { echo "root with no postgres account" >&2; exit 1; }
    AS="postgres"
fi
run() { if [[ -n "$AS" ]]; then su "$AS" -c "$1"; else bash -c "$1"; fi; }

SERVER_PID=""
cleanup() {
    [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
    run "$PGBIN/pg_ctl -D $WORK/data stop -m immediate" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

rm -rf "$WORK"; mkdir -p "$WORK/data" "$WORK/sock"

echo "==> generating level 2A"
(cd "$REPO" && python3 -m curriculum generate 2A --out "$WORK/build" >/dev/null)
cp "$REPO/docs/schema.sql" "$WORK/schema.sql"
cp "$WORK/build/2A.sql" "$WORK/2A.sql"

# Two families and a facilitator. Passwords are hashed by the application's own
# hasher rather than written in, so the login path is the real one.
python3 - "$WORK/seed.sql" <<'PY'
import sys
sys.path.insert(0, ".")
from api.auth import hash_password

parent = hash_password("correct horse battery staple")
staff = hash_password("a facilitators password")

open(sys.argv[1], "w", encoding="utf-8").write(f"""
BEGIN;
INSERT INTO parents (email, password_hash, full_name) VALUES
  ('parent@example.test', '{parent}', 'A Parent'),
  ('other@example.test',  '{parent}', 'Another Parent');
INSERT INTO staff (email, password_hash, full_name) VALUES
  ('priya@example.test', '{staff}', 'Priya');

INSERT INTO students (parent_id, full_name, current_level_id, current_page, packet_size)
SELECT p.id, 'Amara O.', l.id, 41, 5
FROM parents p, levels l WHERE p.email = 'parent@example.test' AND l.name = '2A';

INSERT INTO students (parent_id, full_name, current_level_id, current_page, packet_size)
SELECT p.id, 'Theo B.', l.id, 61, 10
FROM parents p, levels l WHERE p.email = 'other@example.test' AND l.name = '2A';

INSERT INTO badges (student_id, code)
SELECT id, 'BADGE-AMARA' FROM students WHERE full_name = 'Amara O.';
INSERT INTO badges (student_id, code)
SELECT id, 'BADGE-THEO' FROM students WHERE full_name = 'Theo B.';
COMMIT;
""")
PY

[[ -n "$AS" ]] && chown -R "$AS:$AS" "$WORK"

echo "==> starting postgres"
run "$PGBIN/initdb -D $WORK/data -A trust -U postgres" >/dev/null
cat >> "$WORK/data/postgresql.conf" <<CONF

listen_addresses = ''
unix_socket_directories = '$WORK/sock'
port = $PGPORT
CONF
run "$PGBIN/pg_ctl -D $WORK/data -w -l $WORK/data/log start" >/dev/null

PSQL="$PGBIN/psql -h $WORK/sock -p $PGPORT -U postgres -v ON_ERROR_STOP=1 -q"
run "$PSQL -c 'CREATE DATABASE $DB;'"
echo "==> applying schema and loading 2A"
run "$PSQL -d $DB -f $WORK/schema.sql"
run "$PSQL -d $DB -f $WORK/2A.sql"
run "$PSQL -d $DB -f $WORK/seed.sql"

echo "==> starting the server"
cd "$REPO"
MATHLOGIC_DSN="postgresql://postgres@/$DB?host=$WORK/sock&port=$PGPORT" \
MATHLOGIC_RECOGNISER=declared \
  python3 -m uvicorn api.app:app --factory --host 127.0.0.1 --port "$APPPORT" \
  --log-level warning > "$WORK/server.log" 2>&1 &
SERVER_PID=$!

for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$APPPORT/health" >/dev/null 2>&1; then break; fi
    sleep 0.5
done
curl -fsS "http://127.0.0.1:$APPPORT/health" >/dev/null || {
    echo "the server did not come up:" >&2; tail -30 "$WORK/server.log" >&2; exit 1; }

MATHLOGIC_URL="http://127.0.0.1:$APPPORT" python3 "$REPO/scripts/demo.py"
