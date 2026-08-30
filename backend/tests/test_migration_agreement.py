"""The new migrations build the tables the models describe.

Two hand-written descriptions of one table drift, and the drift is invisible
until deployment: the suite creates its schema from `Base.metadata`, so every
test passes against a shape the database will never actually have. The failure
arrives on the server, as a column that does not exist, during the first
request that touches it.

CI has a job that applies every migration to the real TimescaleDB image, which
is the complete check and the slow one. It cannot run here - migration 0001
uses `JSONB`, so the chain from base is Postgres-only - and it also does not
compare the result to the models. This does both for the tables added by
`0012_login_attempts` and `0013_human_challenges`, on SQLite, in milliseconds,
by running those two `upgrade()` functions against a bare connection and
reading back what they built.

Extending this to earlier migrations would mean making them portable, which is
not worth doing to their JSONB columns. New tables are portable by default -
`app.db.types` exists so the models are - and staying that way is worth a test.
"""

from __future__ import annotations

import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.models.human_checks import HumanChallenge
from app.models.login_attempts import LoginAttempt
from app.models.recovery_codes import RecoveryCode
from app.models.tenancy import User

MIGRATIONS = [
    "app.db.alembic.versions.0012_login_attempts",
    "app.db.alembic.versions.0013_human_challenges",
    "app.db.alembic.versions.0014_two_factor",
]

TABLES = [LoginAttempt, HumanChallenge, RecoveryCode]


@pytest.fixture()
def migrated():
    """A SQLite database built by the migrations, not by the models."""
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    # `0014` alters `users` and `recovery_codes` points a foreign key at it,
    # but no migration in this list creates it - the real chain builds it in
    # `0001`, which is Postgres-only.
    #
    # So a stand-in is created with the *pre-0014* shape: an id for the foreign
    # key to reference, and none of the columns 0014 adds. Building it from the
    # model instead would already contain them, and the ALTERs would fail as
    # duplicates - which is a test failing because the fixture did the
    # migration's job, not because anything is wrong.
    sa.Table(
        "users",
        sa.MetaData(),
        sa.Column("id", sa.Uuid(), primary_key=True),
    ).create(engine)
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        # Installs the module-level `op` proxy the migration files import.
        with Operations.context(context):
            for name in MIGRATIONS:
                importlib.import_module(name).upgrade()
        yield connection
    engine.dispose()


@pytest.mark.parametrize("model", TABLES, ids=lambda m: m.__tablename__)
def test_the_migration_creates_the_table(migrated, model):
    assert model.__tablename__ in inspect(migrated).get_table_names()


@pytest.mark.parametrize("model", TABLES, ids=lambda m: m.__tablename__)
def test_the_columns_match_the_model(migrated, model):
    """Names, both directions. A column in the model and not the migration is
    the failure that reaches production; a column in the migration and not the
    model is dead weight nobody will ever explain."""
    built = {c["name"] for c in inspect(migrated).get_columns(model.__tablename__)}
    declared = {c.name for c in model.__table__.columns}

    assert built == declared


@pytest.mark.parametrize("model", TABLES, ids=lambda m: m.__tablename__)
def test_nullability_matches(migrated, model):
    """The half that a create_all-based suite never notices. A column the model
    calls NOT NULL and the migration leaves nullable accepts every test row and
    then accepts a null on the server."""
    built = {
        c["name"]: c["nullable"]
        for c in inspect(migrated).get_columns(model.__tablename__)
    }
    declared = {c.name: c.nullable for c in model.__table__.columns}

    assert built == declared


@pytest.mark.parametrize("model", TABLES, ids=lambda m: m.__tablename__)
def test_the_indexes_the_model_declares_are_created(migrated, model):
    """Not decoration. `login_attempts` is read on the hot path of every
    sign-in, and a missing index there is a full table scan per attempt -
    which is a denial of service an attacker can trigger by attempting."""
    built = {i["name"] for i in inspect(migrated).get_indexes(model.__tablename__)}
    declared = {i.name for i in model.__table__.indexes}

    assert declared <= built, declared - built


def test_downgrade_removes_what_upgrade_added(migrated):
    """A migration that cannot be rolled back is a deployment that cannot be.
    `docs/DEPLOYMENT.md` tells the operator to run `alembic downgrade -1` when
    an upgrade goes wrong, which is only true if it works."""
    context = MigrationContext.configure(migrated)
    with Operations.context(context):
        for name in reversed(MIGRATIONS):
            importlib.import_module(name).downgrade()

    remaining = set(inspect(migrated).get_table_names())

    assert remaining.isdisjoint({m.__tablename__ for m in TABLES})


#: The columns `0014` adds to a table it does not create. Checked separately
#: from `TABLES`, whose members are whole tables the migrations build.
ADDED_TO_USERS = ("totp_secret", "totp_confirmed_at", "totp_last_step")


def test_the_second_factor_columns_land_on_users(migrated):
    built = {c["name"] for c in inspect(migrated).get_columns("users")}

    assert set(ADDED_TO_USERS) <= built


def test_those_columns_are_the_ones_the_model_declares(migrated):
    """A column the model calls `totp_last_step` and the migration calls
    `totp_step` is a `None` on every sign-in, and the replay guard silently
    stops guarding."""
    declared = {c.name for c in User.__table__.columns}

    assert set(ADDED_TO_USERS) <= declared


def test_they_are_all_nullable(migrated):
    """An account that predates the second factor has none, and a NOT NULL
    column added to a populated table fails the migration on the server rather
    than in any test that builds its schema from the models."""
    built = {c["name"]: c["nullable"] for c in inspect(migrated).get_columns("users")}

    assert all(built[name] for name in ADDED_TO_USERS)
