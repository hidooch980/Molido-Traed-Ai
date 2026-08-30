#!/usr/bin/env bash
#
# One deploy command, stamped.
#
# The stamp exists because a browser will happily serve a cached shell after a
# successful deploy, which is indistinguishable from a deploy that failed. With
# a visible build time in the footer, "did it land?" is answered by looking,
# not by diffing page text.
#
#   ./infra/deploy.sh            # everything
#   ./infra/deploy.sh web        # one service
#
# Run from the project root on the server.

set -euo pipefail

cd "$(dirname "$0")/.."

BUILD_STAMP="$(date -u '+%Y-%m-%d %H:%M')"
export BUILD_STAMP

# Version and commit travel with the build, so the footer can answer
# "which release is this" and "which code exactly" without anybody
# checking by hand.
APP_VERSION="$(grep -oE '[0-9]+[.][0-9]+[.][0-9]+' backend/app/__init__.py | head -1)"
export APP_VERSION

# Pull first, and say which commit is being deployed.
#
# This script used to build whatever happened to be in the working tree. A
# deploy would then restart every container, report all of them healthy, and
# run the previous commit - which looks exactly like a successful deploy from
# the outside. It cost one wrong "deployed" claim before it was noticed.
#
# --ff-only rather than a merge: an unexpected divergence must stop the deploy
# rather than resolve itself into something nobody wrote.
echo "-> at ${BEFORE:=$(git rev-parse --short HEAD)}, pulling"
git pull --ff-only --quiet origin main
AFTER="$(git rev-parse --short HEAD)"
GIT_COMMIT="$AFTER"
export GIT_COMMIT
if [ "$BEFORE" = "$AFTER" ]; then
  echo "-> already at ${AFTER} - nothing new to deploy, rebuilding anyway"
else
  echo "-> ${BEFORE} -> ${AFTER}"
fi
git --no-pager log --oneline -1

# A function, not a string variable. The stamp contains a space, so an unquoted
# "$COMPOSE" expansion would split it into two arguments; and `sudo -E` is
# silently ignored under a sudoers policy that does not keep the environment,
# which bakes an empty stamp into the image without failing. Passing the one
# variable through `sudo env` is explicit and cannot be dropped.
# The IP overlay is opt-in, and the default is the domain.
#
# `docker-compose.ip.yml` rebinds Caddy to port 80 alone and swaps in
# `Caddyfile.ip`, which is right for a host reached by bare IP and wrong for
# one reached by name: on the domain host it takes 443 down and every https
# request returns 502. This script composed it in unconditionally, so running
# it on trade.molido.shop broke HTTPS - which it did, on 26 Aug, for several
# minutes until Caddy was recreated from prod.yml alone. Production has been
# deployed by hand ever since, and that is the real cost: the one command
# meant to make deploying safe became the one nobody could run.
#
# The default is the domain because the two mistakes are not equal. Wrong
# here, HTTPS goes down on the live host; wrong the other way, an IP-only
# host asks for a certificate it cannot get and serves plain HTTP - visible
# at once, and it breaks nothing that was already working.
#
#   ./infra/deploy.sh                    # domain host (trade.molido.shop)
#   MOLIDO_IP_ONLY=1 ./infra/deploy.sh   # host reached by bare IP
IP_OVERLAY=()
if [ "${MOLIDO_IP_ONLY:-0}" = "1" ]; then
  echo "-> IP-only host: adding docker-compose.ip.yml, so no HTTPS"
  IP_OVERLAY=(-f infra/docker-compose.ip.yml)
else
  echo "-> domain host: prod.yml alone, HTTPS left to Caddy"
fi

compose() {
  sudo env "BUILD_STAMP=${BUILD_STAMP}" \
    "APP_VERSION=${APP_VERSION}" \
    "GIT_COMMIT=${GIT_COMMIT}" \
    docker compose \
    -f infra/docker-compose.prod.yml \
    "${IP_OVERLAY[@]}" \
    --env-file infra/.env.prod \
    "$@"
}

echo "-> build stamp: ${BUILD_STAMP} UTC"

if [ "$#" -gt 0 ]; then
  echo "-> building: $*"
  compose build "$@"
  compose up -d "$@"
else
  echo "-> building everything"
  compose build
  # Migrations run to completion before the API and collector start, so a
  # service can never come up against a schema it does not understand.
  compose up -d
fi

echo "-> waiting for readiness"
for _ in $(seq 1 40); do
  if curl -fsS -m 5 http://localhost/health/ready >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

# Cap the build cache. One build regenerates ~2.5 GB of it, and left alone it
# reached 11.5 GB and put a 23 GB disk at 80% - at which point the next build
# fails for want of space, which reads as a broken deploy rather than a full
# disk. Two gigabytes keeps layer reuse fast without letting it grow forever.
# The data is not the problem: the database grows about 2.5 MB a day.
echo
echo "-> capping the build cache at ${CACHE_LIMIT:-2GB}"
sudo docker builder prune --force --keep-storage "${CACHE_LIMIT:-2GB}" >/dev/null 2>&1 || true
df -h / | tail -1

echo
echo "=== services ==="
compose ps --format '{{.Name}}  {{.State}}'

echo
echo "=== health ==="
curl -s -m 10 http://localhost/health/ready || echo "API not answering"
echo

# Only the web image carries the stamp. Verifying it after a backend-only
# deploy compares against a build that was never made, which reads as a
# failure and exits non-zero on a perfectly good deployment.
case " $* " in
  *" web "*|"  ") ;;
  *) echo; echo "=== deployed build ==="; echo "skipped - web was not rebuilt"; exit 0 ;;
esac

echo
echo "=== deployed build ==="
# Retry: the web container answers on :3000 a moment before Next has finished
# compiling its first request, and a single early check reads as a failure.
deployed=""
for _ in $(seq 1 15); do
  page="$(curl -s -m 20 http://localhost/ || true)"
  if printf '%s' "$page" | grep -qF "$BUILD_STAMP"; then
    deployed="yes"
    break
  fi
  sleep 3
done

if [ -n "$deployed" ]; then
  echo "OK - the page is serving build ${BUILD_STAMP}"
else
  echo "WARNING: the page is not serving ${BUILD_STAMP}."
  echo "Check:  sudo docker compose ... logs web --tail 40"
  exit 1
fi
