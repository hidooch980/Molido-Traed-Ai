# Backend image — serves both the API and the collector worker.
#
# One image, two commands: the API and the collector share every service module,
# and building them separately would let their dependencies drift apart, which
# is exactly how "works in the API, crashes in the worker" happens.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# tzdata is not optional here: the session calendar resolves every market
# boundary through the IANA database, and a missing zone would silently shift
# an entire trading session.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# alembic.ini is not optional here: the migrate service runs `alembic upgrade
# head`, and Alembic reads script_location from this file. Omitting it makes
# the migration container fail at startup with a config error that looks
# nothing like the missing file it actually is.
COPY pyproject.toml alembic.ini ./
COPY app ./app
# The analyst extra is included even though a deployment with no key never
# calls it. Building it out would mean that pasting a key into .env.prod
# produces "the anthropic package is not installed" - a correct message
# about the wrong thing, arriving at the moment somebody thinks they have
# just finished configuring it. The package is small and imported lazily.
RUN pip install --no-cache-dir -e ".[providers,analyst]"

# Run as an unprivileged user. A data-collection process has no business
# running as root on an internet-facing host.
RUN useradd --create-home --uid 10001 molido \
    && mkdir -p /app/data \
    && chown -R molido:molido /app
USER molido

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
