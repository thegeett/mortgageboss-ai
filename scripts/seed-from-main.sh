#!/usr/bin/env bash
# Seed THIS worktree's Postgres from the MAIN worktree's live dev database,
# plus the uploaded files that its rows reference.
#
#   ./scripts/seed-from-main.sh
#
# READ-ONLY ON THE SOURCE. The only thing this script does to
# mortgageboss-postgres is `pg_dump`. Nothing writes to it, ever.
#
# pg_dump and pg_restore both run INSIDE their containers (both postgres:16-alpine),
# so client and server versions match and no host psql/pg_dump is required.
#
# Extraction rows reference files under backend/storage. Copying the database
# without those files leaves rows pointing at files that do not exist, so the
# storage directory is copied too — that is not optional.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# STACK lives in the root .env (Docker Compose interpolation), not in the shell
# environment. Read it so the guards below see the same value Compose does.
# The shell environment WINS over .env — that is Compose's own precedence, and it
# keeps the guards below overridable (and therefore testable).
if [ -f .env ]; then
  while IFS='=' read -r key val; do
    case "$key" in ''|'#'*) continue ;; esac
    [ -n "${!key:-}" ] && continue
    export "$key=$val"
  done < .env
fi

SOURCE_CONTAINER="${SOURCE_CONTAINER:-mortgageboss-postgres}"
SOURCE_STORAGE="${SOURCE_STORAGE:-../mortgageboss-ai/backend/storage}"
DB_USER="${DB_USER:-mortgageboss}"
DB_NAME="${DB_NAME:-mortgageboss_dev}"
DUMP_FILE="${DUMP_FILE:-/tmp/main_dev.dump}"
RESTORE_LOG="${RESTORE_LOG:-/tmp/main_dev.restore.log}"

# ---------------------------------------------------------------------------
# Guards — every one of these exists to stop this script writing to the main
# worktree's live database. Do not weaken them.
# ---------------------------------------------------------------------------
if [ -z "${STACK:-}" ]; then
  echo "REFUSING: STACK is unset. Create a root .env — see .env.stack.example." >&2
  exit 1
fi

if [ "$STACK" = "mortgageboss" ]; then
  echo "REFUSING: STACK=mortgageboss is the MAIN worktree's stack." >&2
  echo "This script restores INTO \${STACK}-postgres — that would overwrite live data." >&2
  exit 1
fi

TARGET_CONTAINER="${STACK}-postgres"

if [ "$TARGET_CONTAINER" = "$SOURCE_CONTAINER" ]; then
  echo "REFUSING: target ($TARGET_CONTAINER) and source ($SOURCE_CONTAINER) are the same." >&2
  exit 1
fi

for c in "$SOURCE_CONTAINER" "$TARGET_CONTAINER"; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || echo false)" != "true" ]; then
    echo "REFUSING: container $c is not running." >&2
    exit 1
  fi
done

# Port guard — the same check that gates Alembic. Confirms the target really is
# this worktree's database and not the other one reached under a different name.
./scripts/check-stack.sh

echo
echo "Source: $SOURCE_CONTAINER (read-only)  ->  Target: $TARGET_CONTAINER"
echo

# ---------------------------------------------------------------------------
# 1. Dump the source (read-only)
# ---------------------------------------------------------------------------
echo "[1/4] pg_dump $SOURCE_CONTAINER -> $DUMP_FILE"
docker exec "$SOURCE_CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc > "$DUMP_FILE"
echo "      $(wc -c < "$DUMP_FILE" | tr -d ' ') bytes"

# ---------------------------------------------------------------------------
# 2. Restore into the target. --clean --if-exists makes this re-runnable;
#    --no-owner avoids depending on the source's role grants.
# ---------------------------------------------------------------------------
echo "[2/4] pg_restore -> $TARGET_CONTAINER"
set +e
docker exec -i "$TARGET_CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" \
  --clean --if-exists --no-owner < "$DUMP_FILE" 2> "$RESTORE_LOG"
RESTORE_RC=$?
set -e

# "does not exist, skipping" is the benign noise --if-exists produces on a fresh
# database. Anything else is a real error and must be seen.
REAL_ERRORS=$(grep -v 'does not exist, skipping' "$RESTORE_LOG" | grep -c . || true)
if [ "$RESTORE_RC" -ne 0 ] || [ "$REAL_ERRORS" -ne 0 ]; then
  echo "pg_restore exited $RESTORE_RC with $REAL_ERRORS non-benign line(s):" >&2
  grep -v 'does not exist, skipping' "$RESTORE_LOG" >&2 || true
  echo "Full log: $RESTORE_LOG" >&2
  [ "$RESTORE_RC" -ne 0 ] && exit "$RESTORE_RC"
fi
echo "      restored (benign --if-exists notices: $(grep -c 'does not exist, skipping' "$RESTORE_LOG" || true))"

# ---------------------------------------------------------------------------
# 3. Copy the uploaded files the restored rows point at.
# ---------------------------------------------------------------------------
echo "[3/4] storage: $SOURCE_STORAGE -> backend/storage"
if [ ! -d "$SOURCE_STORAGE" ]; then
  echo "WARNING: $SOURCE_STORAGE does not exist — extraction rows will reference missing files." >&2
else
  mkdir -p backend/storage
  cp -R "$SOURCE_STORAGE"/. backend/storage/
  echo "      $(find backend/storage -type f | wc -l | tr -d ' ') file(s) present"
fi

# ---------------------------------------------------------------------------
# 4. Report. loan_files is the loan-file table (backend/app/models/loan_file.py).
# ---------------------------------------------------------------------------
echo "[4/4] verifying"
q() { docker exec "$1" psql -U "$DB_USER" -d "$DB_NAME" -tAc "$2" | tr -d '[:space:]'; }

echo
printf '%-22s %-18s %-18s\n' "" "$SOURCE_CONTAINER" "$TARGET_CONTAINER"
printf '%-22s %-18s %-18s\n' "loan_files rows" \
  "$(q "$SOURCE_CONTAINER" 'select count(*) from loan_files;')" \
  "$(q "$TARGET_CONTAINER" 'select count(*) from loan_files;')"
printf '%-22s %-18s %-18s\n' "alembic_version" \
  "$(q "$SOURCE_CONTAINER" 'select version_num from alembic_version;')" \
  "$(q "$TARGET_CONTAINER" 'select version_num from alembic_version;')"
printf '%-22s %-18s %-18s\n' "public tables" \
  "$(q "$SOURCE_CONTAINER" "select count(*) from information_schema.tables where table_schema='public';")" \
  "$(q "$TARGET_CONTAINER" "select count(*) from information_schema.tables where table_schema='public';")"

# The dump carries real borrower data — do not leave it lying in /tmp.
rm -f "$DUMP_FILE"
echo
echo "Done. Dump removed ($DUMP_FILE). Restore log kept at $RESTORE_LOG."
