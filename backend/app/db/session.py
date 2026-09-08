"""Engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

#: Seconds to wait for the database to answer a new connection.
#:
#: Without one, psycopg waits forever. Every guard in this codebase that
#: promises "a database failure never breaks this page" catches exceptions,
#: and a connection that never returns raises nothing - it just stops. On
#: 2026-09-08, with the host thrashing, `terminal_names.all_names` hung
#: inside its own `try/except`, and with it the digest that calls it and the
#: unit test that only wanted to format a string.
#:
#: Ten seconds is far longer than a healthy connect on the same host and far
#: shorter than a person's patience. It applies to the connect only; a query
#: already running is not touched.
CONNECT_TIMEOUT_SECONDS = 10


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    settings = get_settings()
    url = settings.database_url
    # SQLite takes no such argument, and the unit suite runs on it.
    connect_args = (
        {}
        if url.startswith("sqlite")
        else {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    )
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        future=True,
        connect_args=connect_args,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
