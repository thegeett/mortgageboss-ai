#!/usr/bin/env bash
# Fails unless the DB reached is on the port this worktree expects.
# Prevents running a migration against the other worktree's live database.
set -euo pipefail

EXPECTED_PORT="${EXPECTED_PG_PORT:-5433}"

# current_setting('port'), NOT inet_server_port(): docker exec reaches the server
# over the container's Unix domain socket, and inet_server_port() is NULL for any
# non-TCP connection. It returns empty here and the check silently fails open-ish
# (empty != "5432", so it errors with a confusing message). current_setting('port')
# reports the port the server listens on regardless of how the client connected,
# and needs no password.
ACTUAL_PORT=$(docker exec "${STACK:-mbai-bedrock}-postgres" \
  psql -U mortgageboss -d mortgageboss_dev -tAc "select current_setting('port');" | tr -d '[:space:]')

if [ "$ACTUAL_PORT" != "5432" ]; then
  echo "REFUSING: unexpected in-container port $ACTUAL_PORT." >&2
  exit 1
fi

HOST_PORT=$(docker port "${STACK:-mbai-bedrock}-postgres" 5432 | head -1 | sed 's/.*://')
if [ "$HOST_PORT" != "$EXPECTED_PORT" ]; then
  echo "REFUSING: container publishes $HOST_PORT, expected $EXPECTED_PORT." >&2
  echo "You are probably pointed at the other worktree's database. Check .env." >&2
  exit 1
fi
echo "OK: ${STACK:-mbai-bedrock}-postgres published on $HOST_PORT."
