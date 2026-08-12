"""Operator CLI: `python -m app.cli <command>` (or `molido <command>`)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import typer
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.enums import Timeframe
from app.core.logging import bind_trace, configure_logging
from app.db.session import session_scope
from app.features import all_specs
from app.models.instruments import Instrument
from app.models.market_data import Bar
from app.models.tenancy import Tenant
from app.providers.csv_provider import CsvProvider
from app.providers.registry import get_provider, install_defaults, registered_codes
from app.seed.demo_data import demo_window, generate_csv
from app.seed.holidays import seed_fx_holidays
from app.services import episodes, feature_store, ingestion, symbol_dna
from app.services.instruments import upsert_instrument
from app.services.point_in_time import get_bars
from app.services.sessions import active_sessions, build_calendar

app = typer.Typer(help="MolidoTrade AI operator CLI", no_args_is_help=True)

DATA_ROOT = Path("data/providers/csv")


def _bootstrap() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    bind_trace()
    install_defaults()


@app.command()
def config() -> None:
    """Print the redacted effective configuration."""
    _bootstrap()
    typer.echo(json.dumps(get_settings().safe_summary(), indent=2))


@app.command()
def providers() -> None:
    """List registered market-data adapters."""
    _bootstrap()
    for code in registered_codes():
        adapter = get_provider(code)
        caps = adapter.capabilities()
        typer.echo(f"{code:12} {adapter.name:24} healthy={adapter.health_check()}")
        typer.echo(f"             timeframes: {[t.value for t in caps.supported_timeframes]}")


@app.command("seed-demo")
def seed_demo(
    symbol: str = "EURUSD",
    timeframe: Timeframe = Timeframe.H1,
    tenant_slug: str = "demo",
) -> None:
    """Generate the demo CSV (with known defects) and ingest it.

    Safe to re-run: instrument upsert, ingestion idempotency and finding
    deduplication all collapse a second run into a no-op.
    """
    _bootstrap()
    defects = generate_csv(DATA_ROOT, symbol=symbol, timeframe=timeframe.value)
    typer.echo(f"Wrote demo CSV with injected defects: {json.dumps(defects.as_dict(), indent=2)}")

    start, end = demo_window()

    with session_scope() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
        if tenant is None:
            tenant = Tenant(slug=tenant_slug, name="Demo tenant")
            session.add(tenant)
            session.flush()

        adapter = CsvProvider(DATA_ROOT)
        provider_row = ingestion.get_or_create_provider(
            session,
            code=adapter.code,
            name=adapter.name,
            capabilities=adapter.capabilities().as_dict(),
            trust_weight=0.4,
        )
        instrument = upsert_instrument(session, symbol, name="Euro / US Dollar")

        result = ingestion.ingest_ohlcv(
            session,
            provider=adapter,
            provider_row=provider_row,
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end,
        )

    typer.echo(
        json.dumps(
            {
                "run_id": str(result.run_id),
                "status": result.status.value,
                "fetched": result.fetched,
                "written": result.written,
                "duplicates": result.duplicates,
                "rejected": result.rejected,
                "quality_score": result.quality_score,
                "findings": result.findings,
            },
            indent=2,
        )
    )
    typer.echo(
        "\nQuality score is intentionally below 1.0 - the demo data contains "
        "deliberate defects so the detectors can be verified."
    )


@app.command("seed-holidays")
def seed_holidays(years: str = "2023,2024,2025,2026") -> None:
    """Load the baseline FX holiday calendar. Safe to re-run."""
    _bootstrap()
    parsed = [int(y.strip()) for y in years.split(",") if y.strip()]
    with session_scope() as session:
        written = seed_fx_holidays(session, parsed)
    typer.echo(f"Seeded {written} baseline FX holiday entries for {parsed}.")
    typer.echo(
        "Only unambiguous closures are included. Venue-specific holidays must be "
        "loaded from an operator-maintained source - a wrong entry would mask a "
        "real outage."
    )


@app.command("session-status")
def session_status(
    symbol: str = "EURUSD",
    at: str | None = typer.Option(None, help="UTC ISO-8601 instant, defaults to now"),
) -> None:
    """Report whether a market is open, and which sessions are active."""
    _bootstrap()
    moment = datetime.now(UTC)
    if at:
        moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)

    with session_scope() as session:
        instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
        if instrument is None:
            typer.echo(f"Unknown instrument {symbol}")
            raise typer.Exit(code=1)

        calendar = build_calendar(session, instrument)
        typer.echo(
            json.dumps(
                {
                    "symbol": instrument.symbol,
                    "at": moment.isoformat(),
                    "timezone": calendar.timezone,
                    "market_code": instrument.market_code,
                    "is_open": calendar.is_open(moment),
                    "active_sessions": [s.value for s in active_sessions(moment)],
                    "next_open": _iso(calendar.next_open(moment)),
                    "next_close": _iso(calendar.next_close(moment)),
                },
                indent=2,
            )
        )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


@app.command("build-features")
def build_features(
    symbol: str = "EURUSD",
    timeframe: Timeframe = Timeframe.H1,
    features: str | None = typer.Option(
        None, help="Comma-separated feature names. Defaults to the whole catalog."
    ),
    recompute: bool = False,
) -> None:
    """Materialize features over an instrument's full stored history."""
    _bootstrap()
    names = [n.strip() for n in features.split(",")] if features else None

    with session_scope() as session:
        instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
        if instrument is None:
            typer.echo(f"Unknown instrument {symbol}")
            raise typer.Exit(code=1)

        bounds = session.execute(
            select(func.min(Bar.event_time), func.max(Bar.event_time)).where(
                Bar.instrument_id == instrument.id, Bar.timeframe == timeframe
            )
        ).one()
        first, last = bounds
        if first is None:
            typer.echo(f"No {timeframe.value} bars stored for {symbol}. Run seed-demo first.")
            raise typer.Exit(code=1)

        result = feature_store.materialize(
            session,
            instrument.id,
            timeframe,
            start=first,
            end=last + timeframe.delta,
            feature_names=names,
            recompute=recompute,
        )

    typer.echo(
        json.dumps(
            {
                "symbol": symbol.upper(),
                "timeframe": timeframe.value,
                "bars_processed": result.bars_processed,
                "values_written": result.values_written,
                "values_skipped": result.values_skipped,
                "features": result.features,
            },
            indent=2,
        )
    )


@app.command("features")
def list_features() -> None:
    """Show the feature catalog with declared versions and lookbacks."""
    _bootstrap()
    for spec in all_specs():
        typer.echo(
            f"{spec.name:22} v{spec.version}  lookback={spec.lookback:<4} "
            f"{spec.description}"
        )


@app.command("build-dna")
def build_dna(
    symbol: str = "EURUSD",
    timeframe: Timeframe = Timeframe.H1,
    lookback: int = 5000,
) -> None:
    """Compute and store the behavioural profile for an instrument."""
    _bootstrap()
    cutoff = datetime.now(UTC)

    with session_scope() as session:
        instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
        if instrument is None:
            typer.echo(f"Unknown instrument {symbol}")
            raise typer.Exit(code=1)

        profiles = symbol_dna.compute_dna(
            session, instrument.id, timeframe, cutoff, lookback=lookback
        )
        symbol_dna.persist_dna(session, instrument.id, timeframe, cutoff, profiles)

        summary = {
            kind: {
                "sample_size": p.sample_size,
                "warnings": len(p.warnings),
            }
            for kind, p in profiles.items()
        }

    typer.echo(json.dumps({"symbol": symbol.upper(), "profiles": summary}, indent=2))
    typer.echo(
        "\nNot computed (needs later phases): "
        + ", ".join(sorted(symbol_dna.UNAVAILABLE))
    )


@app.command("build-episodes")
def build_episodes(
    symbol: str = "EURUSD",
    timeframe: Timeframe = Timeframe.H1,
    horizon: int = 24,
    step: int = 1,
    recompute: bool = False,
) -> None:
    """Build historical episodes over an instrument's stored history."""
    _bootstrap()
    cutoff = datetime.now(UTC)

    with session_scope() as session:
        instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
        if instrument is None:
            typer.echo(f"Unknown instrument {symbol}")
            raise typer.Exit(code=1)

        first, last = session.execute(
            select(func.min(Bar.event_time), func.max(Bar.event_time)).where(
                Bar.instrument_id == instrument.id, Bar.timeframe == timeframe
            )
        ).one()
        if first is None:
            typer.echo(f"No {timeframe.value} bars stored for {symbol}.")
            raise typer.Exit(code=1)

        result = episodes.build(
            session,
            instrument.id,
            timeframe,
            start=first,
            end=last + timeframe.delta,
            horizon_bars=horizon,
            as_of=cutoff,
            step=step,
            recompute=recompute,
        )
        stats = episodes.coverage(session, instrument.id, timeframe)

    typer.echo(json.dumps({**result.as_payload(), "stored_total": stats["episodes"]}, indent=2))
    typer.echo(
        "\nEpisodes whose forward window has not closed are skipped, not stored "
        "with a partial outcome - they are not evidence yet."
    )


@app.command("show-bars")
def show_bars(
    symbol: str = "EURUSD",
    timeframe: Timeframe = Timeframe.H1,
    as_of: str = typer.Option(..., help="UTC ISO-8601 knowledge cutoff"),
    lookback: int = 10,
) -> None:
    """Read bars through the point-in-time choke point."""
    _bootstrap()
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)

    with session_scope() as session:
        instrument = session.scalar(select(Instrument).where(Instrument.symbol == symbol.upper()))
        if instrument is None:
            typer.echo(f"Unknown instrument {symbol}")
            raise typer.Exit(code=1)

        bars = get_bars(session, instrument.id, timeframe, cutoff, lookback=lookback)
        typer.echo(f"{len(bars)} bar(s) knowable at {cutoff.isoformat()}")
        for bar in bars:
            typer.echo(
                f"{bar.event_time.isoformat()}  O{bar.open:.5f} H{bar.high:.5f} "
                f"L{bar.low:.5f} C{bar.close:.5f}  rev{bar.revision}"
            )


if __name__ == "__main__":
    app()
