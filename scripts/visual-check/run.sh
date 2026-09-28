#!/usr/bin/env bash
# Seed a Stage 3 screen's state on a scratch database and screenshot it (LP-934). Dev only.
#
#   scripts/visual-check/run.sh S3-02            -> stage3/checks/S3-02-actual.png
#   scripts/visual-check/run.sh S3-02 review     -> stage3/checks/S3-02-review.png
#   scripts/visual-check/run.sh base             -> the file with round 1 imported (no reference PNG)
#
# Several screens in one run: VISUAL_STATES="S3-01 S3-02" scripts/visual-check/run.sh all
#
# It creates (or re-creates) the database `mbai_visual_stage3` on the dev Postgres server, migrates it,
# seeds the state, starts an API on :8011 and `next dev` on :3011 against it, shoots, and stops both.
# Your dev database, your API on :8000 and your dev server on :3000 are not touched: the database name
# is checked by seed.py, the frontend builds into `.next-visual`, and Redis uses db 9.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$REPO/backend"
FRONTEND="$REPO/frontend"
HERE="$REPO/scripts/visual-check"
CHECKS="$REPO/docs/design/phase4.5-conditions/stage3/checks"
SCREENS="$REPO/docs/design/phase4.5-conditions/stage3/screens"
DB_NAME="${VISUAL_DB:-mbai_visual_stage3}"
API_PORT=8011
WEB_PORT=3011
KIND="${2:-actual}"
case "$KIND" in actual|review) ;; *) echo "second argument is 'actual' (default) or 'review'" >&2; exit 2;; esac
[[ $# -ge 1 ]] || { echo "usage: run.sh <S3-xx|base|all> [actual|review]" >&2; exit 2; }
if [[ "$1" == "all" ]]; then STATES="${VISUAL_STATES:?set VISUAL_STATES when using all}"; else STATES="$1"; fi
[[ "$DB_NAME" == mbai_visual_* ]] || { echo "refused: VISUAL_DB must start with mbai_visual_" >&2; exit 2; }

dev_url="$(grep -E '^DATABASE_URL=' "$BACKEND/.env" | cut -d= -f2- | tr -d "\"'")"
dev_redis="$(grep -E '^REDIS_URL=' "$BACKEND/.env" | cut -d= -f2- | tr -d "\"'")"
[[ "${dev_url##*/}" != "$DB_NAME" ]] || { echo "refused: $DB_NAME is the dev database" >&2; exit 2; }
SCRATCH_URL="${dev_url%/*}/$DB_NAME"
SCRATCH_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mbai-visual.XXXXXX")"
export DATABASE_URL="$SCRATCH_URL"
export REDIS_URL="${dev_redis%/*}/9"
export STORAGE_BACKEND=local
export STORAGE_LOCAL_PATH="$SCRATCH_DIR/storage"
export CORS_ALLOWED_ORIGINS="[\"http://localhost:$WEB_PORT\"]"
export RECEIVING_ENABLED=false
# The timeline refuses production's inbox domain outside production (LoanFile.get_inbox_address).
export INBOX_DOMAIN="inbox.visual-check.example"

pids=()
# `next dev` rewrites tsconfig.json (it adds `.next-visual/types`) and may touch next-env.d.ts. The
# harness leaves the tree as it found it, so both are saved here and put back on exit.
for f in tsconfig.json next-env.d.ts; do [[ -f "$FRONTEND/$f" ]] && cp "$FRONTEND/$f" "$SCRATCH_DIR/$f.saved"; done
cleanup() {
  for pid in "${pids[@]:-}"; do [[ -n "$pid" ]] && pkill -P "$pid" 2>/dev/null; kill "$pid" 2>/dev/null || true; done
  for f in tsconfig.json next-env.d.ts; do [[ -f "$SCRATCH_DIR/$f.saved" ]] && cp "$SCRATCH_DIR/$f.saved" "$FRONTEND/$f"; done
  rm -rf "$SCRATCH_DIR"
}
trap cleanup EXIT

recreate_db() {
  (cd "$BACKEND" && uv run python - "$DB_NAME" <<'PY'
import asyncio, os, sys
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
name = sys.argv[1]
assert name.startswith("mbai_visual_")
url = make_url(os.environ["DATABASE_URL"]).set(database="postgres")
async def main() -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()
asyncio.run(main())
PY
  )
  (cd "$BACKEND" && uv run alembic upgrade head >"$SCRATCH_DIR/migrate.log" 2>&1) \
    || { tail -20 "$SCRATCH_DIR/migrate.log" >&2; exit 1; }
}

wait_for() {  # url, seconds, name
  for _ in $(seq 1 "$2"); do curl -sf -o /dev/null "$1" && return 0; sleep 1; done
  echo "$3 did not come up at $1 (log: $SCRATCH_DIR)" >&2; exit 1
}

png_height() {
  python3 -c "import struct,sys; d=open(sys.argv[1],'rb').read(24); print(struct.unpack('>I', d[20:24])[0])" "$1"
}

mkdir -p "$CHECKS" "$STORAGE_LOCAL_PATH"
started=0
for state in $STATES; do
  recreate_db
  seed_json="$(cd "$BACKEND" && uv run python "$HERE/seed.py" "$state" | tail -1)"
  if [[ $started -eq 0 ]]; then
    (cd "$BACKEND" && exec uv run uvicorn app.main:app --port "$API_PORT" >"$SCRATCH_DIR/api.log" 2>&1) &
    pids+=($!); disown "$!"
    (cd "$FRONTEND" && NEXT_DIST_DIR=.next-visual NEXT_PUBLIC_API_URL="http://localhost:$API_PORT" \
      exec pnpm exec next dev -p "$WEB_PORT" >"$SCRATCH_DIR/web.log" 2>&1) &
    pids+=($!); disown "$!"
    wait_for "http://localhost:$API_PORT/health/live" 60 "the API"
    wait_for "http://localhost:$WEB_PORT/login" 180 "next dev"
    started=1
  fi
  reference="$(ls "$SCREENS"/"$state"-*.png 2>/dev/null | head -1 || true)"
  height="$([[ -n "$reference" ]] && png_height "$reference" || echo 1000)"
  VISUAL_API="http://localhost:$API_PORT" VISUAL_FRONTEND="http://localhost:$WEB_PORT" \
    node "$HERE/shoot.mjs" "$state" "$CHECKS/$state-$KIND.png" "$height" "$seed_json"
done
