#!/usr/bin/env bash
# Write down what only the host can see, so the containers can grade it.
#
# `readiness` runs inside a container and left nine checks "could not be
# determined" because the docker log driver, the restore history and the
# repository are not visible from there. This runs on the host, from cron,
# and writes one small JSON note per fact into /var/lib/molido/evidence,
# which every container mounts read-only. Each note carries `written_at`;
# a note older than the reader's limit counts as no note.
#
# Only safe facts are written: paths and categories, counts and timestamps.
# Nothing here reads a secret value, a backup's contents or a log line.
#
#   */15 * * * * /opt/molidotrade/infra/readiness-evidence.sh >> /var/log/molido-evidence.log 2>&1
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVIDENCE_DIR="${MOLIDO_EVIDENCE_DIR:-/var/lib/molido/evidence}"
PROJECT="${COMPOSE_PROJECT_NAME:-molidotrade}"

mkdir -p "$EVIDENCE_DIR"
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Atomic: a half-written note must never be read as a note.
put() {
  local name="$1"
  local tmp="$EVIDENCE_DIR/.$name.json.tmp"
  cat > "$tmp"
  mv -f "$tmp" "$EVIDENCE_DIR/$name.json"
}

# ---------------------------------------------------------------- log rotation
# Read from the running containers, not from the compose file: the file says
# what was asked for, `docker inspect` says what the daemon is doing.
{
  echo '{'
  echo "  \"written_at\": \"$(now)\","
  echo '  "containers": ['
  first=1
  for c in $(docker ps --filter "name=^${PROJECT}-" --format '{{.Names}}' | sort); do
    driver=$(docker inspect "$c" --format '{{.HostConfig.LogConfig.Type}}' 2>/dev/null || echo unknown)
    size=$(docker inspect "$c" --format '{{index .HostConfig.LogConfig.Config "max-size"}}' 2>/dev/null || true)
    files=$(docker inspect "$c" --format '{{index .HostConfig.LogConfig.Config "max-file"}}' 2>/dev/null || true)
    bounded=false
    case "$driver" in
      json-file|local) [ -n "$size" ] && bounded=true ;;
      journald|syslog) bounded=true ;;
    esac
    logpath=$(docker inspect "$c" --format '{{.LogPath}}' 2>/dev/null || true)
    logbytes=0; [ -n "$logpath" ] && [ -f "$logpath" ] && logbytes=$(stat -c %s "$logpath")
    [ $first -eq 1 ] || echo ','
    first=0
    printf '    {"name": "%s", "driver": "%s", "max_size": "%s", "max_file": "%s", "bounded": %s, "current_log_bytes": %s}' \
      "$c" "$driver" "$size" "$files" "$bounded" "$logbytes"
  done
  echo
  echo '  ],'
  echo "  \"note\": \"bounded means the daemon caps this container's log; audit events live in the database under their own retention\""
  echo '}'
} | put log-rotation

# ------------------------------------------------------------------ secrets
# Deterministic, standard-library python, values never printed. Exit status is
# informational here; the note carries the verdict.
python3 "$ROOT/backend/app/ops/secrets_scan.py" --root "$ROOT" --output "$EVIDENCE_DIR/secrets-scan.json" || true

# ----------------------------------------------------------------- restore
# Written by backup.sh when a drill runs; this only reports its presence so a
# missing drill shows up in this log as well as in the readiness report.
if [ -f "$EVIDENCE_DIR/restore-drill.json" ]; then
  echo "[$(now)] restore-drill.json present (written $(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('written_at'))" "$EVIDENCE_DIR/restore-drill.json"))"
else
  echo "[$(now)] no restore-drill.json yet: backup.sh has not completed a drill since this was installed"
fi

echo "[$(now)] evidence written to $EVIDENCE_DIR: $(ls "$EVIDENCE_DIR" | tr '\n' ' ')"
