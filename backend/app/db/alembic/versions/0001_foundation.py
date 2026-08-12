"""Foundation schema: tenancy, instruments, market data, ingestion, audit.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-08-09

TimescaleDB is used for `ohlcv` and `ticks` when the extension is available.
If it is not (e.g. plain Postgres in CI), the tables remain ordinary tables and
everything else still works - the hypertable is a performance property, not a
correctness one.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB
TS = sa.DateTime(timezone=True)


def _timescale_available(conn) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()

    # ---------------------------------------------------------------- tenancy
    op.create_table(
        "tenants",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("key_prefix", sa.String(12), nullable=False, index=True),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("scopes", sa.String(255), nullable=False, server_default="read"),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("expires_at", TS, nullable=True),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )

    # ------------------------------------------------------------ instruments
    op.create_table(
        "providers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="market_data"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("capabilities", JSONB, nullable=False, server_default="{}"),
        sa.Column("trust_weight", sa.Numeric(4, 3), nullable=False, server_default="0.5"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "instruments",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("symbol", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column("asset_class", sa.String(32), nullable=False),
        sa.Column("base_currency", sa.String(16), nullable=True),
        sa.Column("quote_currency", sa.String(16), nullable=True),
        sa.Column("exchange", sa.String(64), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Etc/UTC"),
        sa.Column("trading_hours", JSONB, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "broker_symbols",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "tenant_id",
            UUID,
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "instrument_id",
            UUID,
            sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("broker_code", sa.String(64), nullable=False),
        sa.Column("raw_symbol", sa.String(64), nullable=False),
        sa.Column("contract_size", sa.Numeric(20, 8), nullable=True),
        sa.Column("digits", sa.Integer, nullable=True),
        sa.Column("point", sa.Numeric(20, 10), nullable=True),
        sa.Column("tick_size", sa.Numeric(20, 10), nullable=True),
        sa.Column("tick_value", sa.Numeric(20, 10), nullable=True),
        sa.Column("volume_min", sa.Numeric(20, 8), nullable=True),
        sa.Column("volume_max", sa.Numeric(20, 8), nullable=True),
        sa.Column("volume_step", sa.Numeric(20, 8), nullable=True),
        sa.Column("margin_rules", JSONB, nullable=False, server_default="{}"),
        sa.Column("spread_model", JSONB, nullable=False, server_default="{}"),
        sa.Column("trading_hours", JSONB, nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "broker_code", "raw_symbol", name="uq_broker_symbol"),
    )

    # ------------------------------------------------------------ market data
    op.create_table(
        "ohlcv",
        sa.Column(
            "instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column(
            "provider_id", UUID, sa.ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("event_time", TS, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("ingested_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("open", sa.Numeric(20, 10), nullable=False),
        sa.Column("high", sa.Numeric(20, 10), nullable=False),
        sa.Column("low", sa.Numeric(20, 10), nullable=False),
        sa.Column("close", sa.Numeric(20, 10), nullable=False),
        sa.Column("volume", sa.Numeric(24, 8), nullable=True),
        sa.Column("tick_volume", sa.Numeric(24, 8), nullable=True),
        sa.Column("spread", sa.Numeric(20, 10), nullable=True),
        sa.Column("quality_score", sa.Numeric(4, 3), nullable=False, server_default="1.0"),
        sa.Column("source_ref", sa.Text, nullable=True),
        sa.PrimaryKeyConstraint(
            "instrument_id", "timeframe", "provider_id", "event_time", "revision"
        ),
    )
    op.create_index("ix_ohlcv_lookup", "ohlcv", ["instrument_id", "timeframe", "event_time"])
    op.create_index("ix_ohlcv_ingested", "ohlcv", ["ingested_at"])

    op.create_table(
        "ticks",
        sa.Column(
            "instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_id", UUID, sa.ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("event_time", TS, nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ingested_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("bid", sa.Numeric(20, 10), nullable=True),
        sa.Column("ask", sa.Numeric(20, 10), nullable=True),
        sa.Column("last", sa.Numeric(20, 10), nullable=True),
        sa.Column("volume", sa.Numeric(24, 8), nullable=True),
        sa.Column("quality_score", sa.Numeric(4, 3), nullable=False, server_default="1.0"),
        sa.PrimaryKeyConstraint("instrument_id", "provider_id", "event_time", "sequence"),
    )
    op.create_index("ix_ticks_lookup", "ticks", ["instrument_id", "event_time"])

    # -------------------------------------------------------------- ingestion
    op.create_table(
        "ingestion_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "provider_id", UUID, sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False,
            index=True,
        ),
        sa.Column(
            "instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("requested_start", TS, nullable=False),
        sa.Column("requested_end", TS, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("rows_fetched", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_written", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_rejected", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("rows_duplicate", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_ingestion_runs_idempotency"),
    )
    op.create_index(
        "ix_ingestion_runs_target", "ingestion_runs", ["instrument_id", "timeframe", "status"]
    )

    op.create_table(
        "ingestion_checkpoints",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "provider_id", UUID, sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("last_event_time", TS, nullable=True),
        sa.Column(
            "last_run_id", UUID, sa.ForeignKey("ingestion_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_success_at", TS, nullable=True),
        sa.Column("cursor", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "provider_id", "instrument_id", "timeframe", name="uq_ingestion_checkpoint_target"
        ),
    )

    op.create_table(
        "data_quality_findings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "provider_id", UUID, sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False,
            index=True,
        ),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column(
            "run_id", UUID, sa.ForeignKey("ingestion_runs.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("issue", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="warning"),
        sa.Column("window_start", TS, nullable=False),
        sa.Column("window_end", TS, nullable=False),
        sa.Column("detected_at", TS, nullable=False),
        sa.Column("affected_rows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expected", sa.Text, nullable=True),
        sa.Column("observed", sa.Text, nullable=True),
        sa.Column("details", JSONB, nullable=False, server_default="{}"),
        sa.Column("resolved_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "instrument_id", "provider_id", "timeframe", "issue", "window_start",
            name="uq_dq_finding_window",
        ),
    )
    op.create_index(
        "ix_dq_lookup",
        "data_quality_findings",
        ["instrument_id", "timeframe", "issue", "detected_at"],
    )

    op.create_table(
        "dataset_quality",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "instrument_id", UUID, sa.ForeignKey("instruments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_id", UUID, sa.ForeignKey("providers.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("score", sa.Numeric(4, 3), nullable=False, server_default="1.0"),
        sa.Column("coverage_start", TS, nullable=True),
        sa.Column("coverage_end", TS, nullable=True),
        sa.Column("expected_bars", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("actual_bars", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("open_findings", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_training_eligible", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("evaluated_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "instrument_id", "provider_id", "timeframe", name="uq_dataset_quality_target"
        ),
    )

    # ------------------------------------------------------------------ audit
    op.create_table(
        "audit_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("occurred_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("trace_id", sa.String(64), nullable=True, index=True),
        sa.Column("tenant_id", UUID, nullable=True),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("account_id", UUID, nullable=True),
        sa.Column("service", sa.String(64), nullable=False, server_default="backend"),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="info"),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("model_version", sa.String(64), nullable=True),
    )
    op.create_index("ix_audit_events_time", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_type", "audit_events", ["event_type", "occurred_at"])
    op.create_index("ix_audit_events_tenant", "audit_events", ["tenant_id", "occurred_at"])

    # -------------------------------------------------------------- timescale
    if _timescale_available(conn):
        op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        op.execute(
            "SELECT create_hypertable('ohlcv', 'event_time', "
            "chunk_time_interval => INTERVAL '30 days', migrate_data => TRUE)"
        )
        op.execute(
            "SELECT create_hypertable('ticks', 'event_time', "
            "chunk_time_interval => INTERVAL '1 day', migrate_data => TRUE)"
        )
        # Compression keeps multi-year history affordable; retention is applied
        # to raw ticks only - bars are the durable record.
        op.execute(
            "ALTER TABLE ohlcv SET (timescaledb.compress, "
            "timescaledb.compress_segmentby = 'instrument_id, timeframe, provider_id')"
        )
        op.execute("SELECT add_compression_policy('ohlcv', INTERVAL '180 days')")
        op.execute(
            "ALTER TABLE ticks SET (timescaledb.compress, "
            "timescaledb.compress_segmentby = 'instrument_id, provider_id')"
        )
        op.execute("SELECT add_compression_policy('ticks', INTERVAL '7 days')")
        op.execute("SELECT add_retention_policy('ticks', INTERVAL '400 days')")


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_table("dataset_quality")
    op.drop_table("data_quality_findings")
    op.drop_table("ingestion_checkpoints")
    op.drop_table("ingestion_runs")
    op.drop_table("ticks")
    op.drop_table("ohlcv")
    op.drop_table("broker_symbols")
    op.drop_table("instruments")
    op.drop_table("providers")
    op.drop_table("api_keys")
    op.drop_table("users")
    op.drop_table("tenants")
