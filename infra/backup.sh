#!/usr/bin/env bash
#
# Nightly database backup with restore verification.
#
# The spec is explicit: never claim a backup is valid without a restore test.
# So this script does not stop at pg_dump — it restores the dump into a
# throwaway database and counts rows. A dump that cannot be restored is not a
# backup, it is a file.
#
#   crontab -e
#   15 3 * * *  /opt/molidotrade/infra/backup.sh >> /var/log/molido-backup.log 2>&1

set -euo pipefail

COMPOSE_FILE="$(dirname "$0")/docker-compose.prod.yml"
ENV_FILE="$(dirname "$0")/.env.prod"
BACKUP_DIR="$(dirname "$0")/backups"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

# shellcheck disable=SC1090
source "$ENV_FILE"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="molido-${STAMP}.dump"

mkdir -p "$BACKUP_DIR"

compose() {
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

echo "[$(date -u +%FT%TZ)] dumping ${POSTGRES_DB}"
# TimescaleDB's catalogue tables carry circular foreign keys between each
# other, so pg_dump warns and a plain restore fails on ordering. The first
# fix excluded the _timescaledb_* schemas and made it worse: the restore
# passed and the database came back with zero bars, because a hypertable's
# rows live in _timescaledb_internal chunks. Excluding the catalogue excluded
# the data, and an empty backup that reports OK is worse than one that fails.
#
# The whole database is dumped. The ordering problem is solved at restore
# time by --disable-triggers, which is where it belongs.
compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --format=custom --file="/backups/${FILE}"

echo "[$(date -u +%FT%TZ)] verifying by restoring into a scratch database"
VERIFY_DB="verify_${STAMP}"
compose exec -T postgres createdb -U "$POSTGRES_USER" "$VERIFY_DB"

# The restore is expected to emit warnings about the timescaledb extension
# owner; those are noise. A non-zero exit is not.
# TimescaleDB has to be told a restore is happening. Its event triggers and
# background machinery reject a bulk load otherwise, and two earlier attempts
# proved it: excluding the extension's schemas restored an empty database,
# and --disable-triggers alone still failed.
#
# post_restore runs whether or not the restore worked. Leaving a database in
# restoring mode breaks every later attempt against it, and the failure then
# looks like a bad dump rather than a dirty target.
compose exec -T postgres psql -U "$POSTGRES_USER" -d "$VERIFY_DB" -tAc \
  "SELECT timescaledb_pre_restore()" >/dev/null 2>&1 || true

RESTORE_OK=1
compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$VERIFY_DB" \
  --no-owner --disable-triggers "/backups/${FILE}" 2>/dev/null || RESTORE_OK=0

compose exec -T postgres psql -U "$POSTGRES_USER" -d "$VERIFY_DB" -tAc \
  "SELECT timescaledb_post_restore()" >/dev/null 2>&1 || true

if [ "$RESTORE_OK" -eq 1 ]; then
  ROWS=$(compose exec -T postgres psql -U "$POSTGRES_USER" -d "$VERIFY_DB" -tAc \
    "SELECT count(*) FROM ohlcv" || echo "0")
  echo "[$(date -u +%FT%TZ)] restore OK — ohlcv rows: ${ROWS}"
  if [ "${ROWS:-0}" -eq 0 ]; then
    echo "[$(date -u +%FT%TZ)] WARNING: restored database has no bars" >&2
  fi
else
  echo "[$(date -u +%FT%TZ)] RESTORE FAILED for ${FILE} — backup is NOT valid" >&2
  compose exec -T postgres dropdb -U "$POSTGRES_USER" --if-exists "$VERIFY_DB"
  exit 1
fi

compose exec -T postgres dropdb -U "$POSTGRES_USER" "$VERIFY_DB"

echo "[$(date -u +%FT%TZ)] pruning dumps older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -name 'molido-*.dump' -mtime "+${RETENTION_DAYS}" -delete

echo "[$(date -u +%FT%TZ)] done: ${FILE}"
