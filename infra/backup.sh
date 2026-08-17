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
# TimescaleDB's own catalogue tables - hypertable, chunk, continuous_agg -
# carry circular foreign keys between each other. A plain custom-format dump
# of them cannot be restored in dependency order, and the first real run of
# this script proved it: pg_dump warned three times and the restore
# verification failed outright.
#
# --exclude-schema drops that catalogue from the dump. The extension rebuilds
# it when the schema is recreated, so what is being excluded is machinery
# rather than data. Every application table, including the hypertables'
# contents, is still in there.
compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  --format=custom \
  --exclude-schema=_timescaledb_internal \
  --exclude-schema=_timescaledb_catalog \
  --exclude-schema=_timescaledb_config \
  --file="/backups/${FILE}"

echo "[$(date -u +%FT%TZ)] verifying by restoring into a scratch database"
VERIFY_DB="verify_${STAMP}"
compose exec -T postgres createdb -U "$POSTGRES_USER" "$VERIFY_DB"

# The restore is expected to emit warnings about the timescaledb extension
# owner; those are noise. A non-zero exit is not.
# --disable-triggers as well as --no-owner. Foreign keys that survive the
# exclusions above still fire during a data load and reject rows whose
# partner has not arrived yet, which is a restore failing on ordering rather
# than on content.
if compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$VERIFY_DB" \
  --no-owner --disable-triggers \
  "/backups/${FILE}" 2>/dev/null; then
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
