#!/usr/bin/env bash
# The standing answer to "is the fleet healthy and is the journal moving",
# written where a redeploy cannot throw it away.
#
# On 6 September the resolver was found to have been stopped since the 3rd:
# 82,622 entries open, nothing scored for three days, and every cycle
# reporting `resolved: 0` while working exactly as it was written. Nobody saw
# it because the evidence only existed in a container log that rotates, and
# because the one command that would have shown it has to be typed by a
# person who already suspects something.
#
# So it is typed by cron instead, and the answer is appended to a file on the
# host. A log line inside a container does not survive `docker compose up`;
# a line in /var/log does.
#
#   # Every six hours, so whenever anybody looks there is a recent picture and
#   # a history behind it - the failure this exists to catch went unseen for
#   # three days, and nobody was watching at any particular hour.
#   17 */6 * * * /opt/molidotrade/infra/checkpoint.sh >> /var/log/molido-checkpoint.log 2>&1
#   # Two hours after the week's open, the first Monday morning of trading,
#   # and every evening: the same plus each brain's week.
#   7 23 * * 0 /opt/molidotrade/infra/checkpoint.sh --scorecard >> /var/log/molido-checkpoint.log 2>&1
#   17 5 * * 1 /opt/molidotrade/infra/checkpoint.sh --scorecard >> /var/log/molido-checkpoint.log 2>&1
#   37 17 * * * /opt/molidotrade/infra/checkpoint.sh --scorecard >> /var/log/molido-checkpoint.log 2>&1
#
# `--scorecard` adds each brain's week beside its own control. It is separate
# because that report walks the whole journal and is worth once a day, while
# knowing whether the cycles are alive is worth more often and costs a query.
#
set -uo pipefail

PROJECT="${COMPOSE_PROJECT_NAME:-molidotrade}"
COLLECTOR="${PROJECT}-collector-1"
POSTGRES="${PROJECT}-postgres-1"
DB_USER="${MOLIDO_DB_USER:-molido}"
DB_NAME="${MOLIDO_DB_NAME:-molidotrade}"

WANT_SCORECARD=0
[ "${1:-}" = "--scorecard" ] && WANT_SCORECARD=1

echo "===== checkpoint $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="

# Deliberately not `set -e`: a checkpoint that dies on its first failing
# section tells you least exactly when something is wrong, which is the only
# time anybody reads it. Each section reports its own failure and the rest
# still runs.

echo "--- cycles"
docker exec "$COLLECTOR" python -m app.workers.health_report \
  || echo "health_report exited non-zero (above), or could not be run"

echo "--- journal"
docker exec "$POSTGRES" psql -U "$DB_USER" -d "$DB_NAME" -At -c "
select
  'open=' || count(*) filter (where closed_at is null) ||
  ' resolved=' || count(*) filter (where outcome is not null) ||
  ' newest_decision=' || coalesce(max(created_at)::text, 'never') ||
  ' newest_resolution=' || coalesce(max(closed_at)::text, 'never')
from journal_entries;" || echo "journal query failed"

if [ "$WANT_SCORECARD" = "1" ]; then
  echo "--- brains, last 7 days"
  docker exec "$COLLECTOR" python -c "
import json
from app.db.session import session_scope
from app.learning.weekly import build_report

with session_scope() as session:
    report = build_report(session)
for brain in report['brains']:
    print(
        '{strategy:<24} decided={decided:<7} resolved={resolved:<7} '
        'edge_r={edge_r} thin={thin_sample}'.format(**brain)
    )
" || echo "scorecard failed"
fi
