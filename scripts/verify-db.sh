#!/usr/bin/env bash
#
# Stand up a throwaway Postgres, apply the schema, load level 2A, and run the
# invariant checks against it. Leaves nothing behind.
#
#   scripts/verify-db.sh
#
# Needs a Postgres server binary (any 14+). It does not use, touch or need a
# running cluster of your own — it builds its own in a temp directory on port
# 5433 and removes it on exit.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The socket path has a 107-byte limit, so this cannot live under a long temp
# path. Short and predictable, removed on exit.
WORK="${MATHLOGIC_PG_DIR:-/tmp/mathlogic-verify}"
PORT="${MATHLOGIC_PG_PORT:-5433}"
DB=mathlogic

find_pgbin() {
    if command -v initdb >/dev/null 2>&1; then
        dirname "$(command -v initdb)"
        return
    fi
    local candidate
    candidate="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1 || true)"
    if [[ -n "$candidate" && -x "$candidate/initdb" ]]; then
        echo "$candidate"
        return
    fi
    echo "no Postgres server binary found (looked for initdb and /usr/lib/postgresql/*/bin)" >&2
    exit 1
}

PGBIN="$(find_pgbin)"

# Postgres refuses to run as root. If we are root, borrow the postgres account.
AS=""
if [[ "$(id -u)" -eq 0 ]]; then
    if ! id postgres >/dev/null 2>&1; then
        echo "running as root and there is no postgres user to drop to" >&2
        exit 1
    fi
    AS="postgres"
fi

run() {
    if [[ -n "$AS" ]]; then su "$AS" -c "$1"; else bash -c "$1"; fi
}

cleanup() {
    run "$PGBIN/pg_ctl -D $WORK/data stop -m immediate" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

rm -rf "$WORK"
mkdir -p "$WORK/data" "$WORK/sock"

echo "==> generating level 2A"
(cd "$REPO" && python3 -m curriculum generate 2A --out "$WORK/build" >/dev/null)
cp "$REPO/docs/schema.sql" "$WORK/schema.sql"
cp "$REPO/db/checks/invariants.sql" "$WORK/invariants.sql"
cp "$WORK/build/2A.sql" "$WORK/2A.sql"

if [[ -n "$AS" ]]; then chown -R "$AS:$AS" "$WORK"; fi

echo "==> starting postgres on port $PORT"
run "$PGBIN/initdb -D $WORK/data -A trust -U postgres" >/dev/null
run "$PGBIN/pg_ctl -D $WORK/data -o '-k $WORK/sock -h \"\" -p $PORT' -w -l $WORK/data/log start" >/dev/null

PSQL="$PGBIN/psql -h $WORK/sock -p $PORT -U postgres -v ON_ERROR_STOP=1 -q"

run "$PSQL -c 'CREATE DATABASE $DB;'"
echo "==> applying schema"
run "$PSQL -d $DB -f $WORK/schema.sql"
echo "==> loading level 2A"
run "$PSQL -d $DB -f $WORK/2A.sql"
echo "==> checking invariants"
run "$PSQL -d $DB -f $WORK/invariants.sql"

echo
echo "Everything checked out. Tearing the cluster down."
