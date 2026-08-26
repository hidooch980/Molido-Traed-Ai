"""Ingestion pipeline tests: idempotency, resume, revisions, retry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import IngestionStatus, Timeframe
from app.core.errors import ProviderError, RateLimitedError
from app.providers.base import ProviderCapabilities, ProviderSymbol, RawBar
from app.services import ingestion
from app.services.point_in_time import get_bars
from tests.conftest import BASE_TIME, make_bars


class FakeProvider:
    """Scriptable adapter. Counts calls so retry behaviour is observable."""

    code = "fake"
    name = "Fake provider"

    def __init__(self, bars: list[RawBar], *, failures: int = 0, rate_limited: int = 0):
        self._bars = bars
        self.failures_remaining = failures
        self.rate_limits_remaining = rate_limited
        self.calls = 0

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_timeframes=(Timeframe.H1,))

    def list_symbols(self) -> list[ProviderSymbol]:
        return [ProviderSymbol(raw_symbol="EURUSD")]

    def fetch_ohlcv(self, raw_symbol, timeframe, start, end):
        self.calls += 1
        if self.rate_limits_remaining > 0:
            self.rate_limits_remaining -= 1
            raise RateLimitedError("slow down", retry_after_seconds=0.01)
        if self.failures_remaining > 0:
            self.failures_remaining -= 1
            raise ProviderError("transient upstream failure")
        return [b for b in self._bars if start <= b.event_time < end]

    def health_check(self) -> bool:
        return True


def _window(bars):
    return bars[0].event_time, bars[-1].event_time + timedelta(hours=1)


def _run(session, adapter, provider_row, instrument, **kwargs):
    start, end = kwargs.pop("window", _window(adapter._bars))
    return ingestion.ingest_ohlcv(
        session,
        provider=adapter,
        provider_row=provider_row,
        instrument=instrument,
        timeframe=Timeframe.H1,
        start=start,
        end=end,
        sleep=lambda _: None,  # no real waiting in tests
        **kwargs,
    )


def test_happy_path_writes_bars(session, provider, instrument):
    adapter = FakeProvider(make_bars(48))

    result = _run(session, adapter, provider, instrument)

    assert result.status == IngestionStatus.SUCCEEDED
    assert result.written == 48
    assert result.duplicates == 0
    # as_of must be "now": ingestion stamps ingested_at at write time, so the
    # rows only become knowable once as_of passes the moment they were stored.
    bars = get_bars(session, instrument.id, Timeframe.H1, datetime.now(UTC), lookback=100)
    assert len(bars) == 48


def test_rerun_same_window_is_idempotent(session, provider, instrument):
    """The spec forbids duplicate execution; a repeated import must be a no-op."""
    adapter = FakeProvider(make_bars(24))

    first = _run(session, adapter, provider, instrument)
    second = _run(session, adapter, provider, instrument)

    assert first.written == 24
    assert second.written == 0
    assert second.status == IngestionStatus.SUCCEEDED


def test_unchanged_rows_are_counted_as_duplicates_not_rewritten(session, provider, instrument):
    bars = make_bars(24)
    adapter = FakeProvider(bars)
    _run(session, adapter, provider, instrument)

    # Same data, different window key -> the idempotency shortcut does not apply,
    # so the value comparison is what must prevent a second copy.
    start, end = _window(bars)
    second = ingestion.ingest_ohlcv(
        session,
        provider=adapter,
        provider_row=provider,
        instrument=instrument,
        timeframe=Timeframe.H1,
        start=start,
        end=end + timedelta(hours=1),
        resume=False,
        sleep=lambda _: None,
    )

    assert second.written == 0
    assert second.duplicates == 24


def test_changed_bar_becomes_a_new_revision(session, provider, instrument):
    """Corrections append a revision; the original is preserved for PIT reads."""
    from dataclasses import replace

    bars = make_bars(24)
    _run(session, FakeProvider(bars), provider, instrument)

    corrected = list(bars)
    corrected[5] = replace(
        corrected[5],
        close=corrected[5].close + 0.05,
        high=corrected[5].high + 0.05,
    )
    start, end = _window(bars)
    result = ingestion.ingest_ohlcv(
        session,
        provider=FakeProvider(corrected),
        provider_row=provider,
        instrument=instrument,
        timeframe=Timeframe.H1,
        start=start,
        end=end + timedelta(hours=2),
        resume=False,
        sleep=lambda _: None,
    )

    assert result.written == 1
    visible = get_bars(session, instrument.id, Timeframe.H1, datetime.now(UTC), lookback=100)
    revised = next(b for b in visible if b.event_time == bars[5].event_time)
    assert revised.revision == 2


def test_retries_transient_failures(session, provider, instrument):
    adapter = FakeProvider(make_bars(12), failures=2)

    result = _run(session, adapter, provider, instrument)

    assert result.status == IngestionStatus.SUCCEEDED
    assert adapter.calls == 3  # two failures + one success


def test_honours_rate_limit_then_succeeds(session, provider, instrument):
    adapter = FakeProvider(make_bars(12), rate_limited=1)

    result = _run(session, adapter, provider, instrument)

    assert result.status == IngestionStatus.SUCCEEDED
    assert adapter.calls == 2


def test_exhausted_retries_records_failure_without_raising(session, provider, instrument):
    """A dead provider is an operational fact to log, not a crash."""
    adapter = FakeProvider(make_bars(12), failures=99)

    result = _run(session, adapter, provider, instrument)

    assert result.status == IngestionStatus.FAILED
    assert result.error is not None
    assert result.written == 0


def test_checkpoint_enables_resume(session, provider, instrument):
    """After a partial import, a resumed run re-reads only the tail."""
    from sqlalchemy import select

    from app.models.ingestion import IngestionCheckpoint

    bars = make_bars(48)
    _run(session, FakeProvider(bars[:24]), provider, instrument, window=_window(bars[:24]))

    checkpoint = session.scalar(
        select(IngestionCheckpoint).where(
            IngestionCheckpoint.instrument_id == instrument.id,
            IngestionCheckpoint.provider_id == provider.id,
        )
    )
    assert checkpoint is not None
    assert checkpoint.last_event_time == bars[23].event_time

    adapter = FakeProvider(bars)
    result = _run(session, adapter, provider, instrument, window=_window(bars))

    # Resume starts at the last known bar (re-fetched, since providers revise
    # the most recent candle), so the 24 already-stored bars are not rewritten.
    assert result.written == 24
    assert result.duplicates == 1


def test_checkpoint_never_moves_backwards(session, provider, instrument):
    from sqlalchemy import select

    from app.models.ingestion import IngestionCheckpoint

    bars = make_bars(48)
    _run(session, FakeProvider(bars), provider, instrument, window=_window(bars))
    _run(
        session,
        FakeProvider(bars[:10]),
        provider,
        instrument,
        window=_window(bars[:10]),
        resume=False,
    )

    checkpoint = session.scalar(
        select(IngestionCheckpoint).where(
            IngestionCheckpoint.instrument_id == instrument.id
        )
    )
    assert checkpoint.last_event_time == bars[47].event_time


def test_rejects_unusable_rows_and_keeps_the_rest(session, provider, instrument):
    from dataclasses import replace

    bars = make_bars(24)
    bars[3] = replace(bars[3], low=-1.0, open=-1.0, high=-1.0, close=-1.0)
    adapter = FakeProvider(bars)

    result = _run(session, adapter, provider, instrument)

    assert result.rejected == 1
    assert result.written == 23


def test_quality_report_accompanies_every_run(session, provider, instrument):
    bars = make_bars(100)
    del bars[40:45]

    result = _run(session, FakeProvider(bars), provider, instrument)

    assert "missing_candle" in result.findings
    assert 0.0 < result.quality_score < 1.0


def test_invalid_window_is_rejected(session, provider, instrument):
    from app.core.errors import ValidationFailedError

    bars = make_bars(5)
    with pytest.raises(ValidationFailedError):
        ingestion.ingest_ohlcv(
            session,
            provider=FakeProvider(bars),
            provider_row=provider,
            instrument=instrument,
            timeframe=Timeframe.H1,
            start=bars[-1].event_time,
            end=bars[0].event_time,
            sleep=lambda _: None,
        )


def test_idempotency_key_is_stable_and_window_sensitive():
    start, end = BASE_TIME, BASE_TIME + timedelta(days=1)
    a = ingestion.make_idempotency_key("csv", "EURUSD", Timeframe.H1, start, end)
    b = ingestion.make_idempotency_key("csv", "EURUSD", Timeframe.H1, start, end)
    c = ingestion.make_idempotency_key(
        "csv", "EURUSD", Timeframe.H1, start, end + timedelta(hours=1)
    )

    assert a == b
    assert a != c


class TestABarFromOutsideTheWindow:
    """A provider does not promise to answer inside the range it was asked for.

    Yahoo answers a fifteen-minute request with whatever its session
    boundaries produce, and a bar arriving from outside the requested window
    was invisible to a lookup shaped like that window. The insert that
    followed collided with a row already stored and took the whole symbol down
    with it - seven of a hundred and twenty-five entries on every sweep, each
    one an instrument that stops collecting entirely.
    """

    def test_a_bar_already_stored_is_not_inserted_twice(
        self, session, instrument, provider
    ):
        from datetime import UTC, datetime, timedelta

        from app.core.enums import Timeframe
        from app.services import ingestion

        moment = datetime(2026, 7, 2, 14, 30, tzinfo=UTC)

        # Stored once, as an earlier sweep would have left it.
        stored = ingestion._existing_bars(
            session, instrument.id, provider.id, Timeframe.M15, [moment]
        )
        assert stored == {}

        from tests.conftest import insert_bar

        insert_bar(
            session, instrument.id, provider.id,
            event_time=moment, ingested_at=moment,
            close=1.1, open_=1.1, timeframe=Timeframe.M15,
        )
        session.flush()

        # Found by timestamp, even though no window was given.
        found = ingestion._existing_bars(
            session, instrument.id, provider.id, Timeframe.M15, [moment]
        )
        assert moment in found, (
            "the bar is stored; a lookup that cannot see it is the lookup "
            "that lets the next insert collide"
        )

    def test_an_empty_list_asks_the_database_nothing(
        self, session, instrument, provider
    ):
        """A fetch that returned nothing must not turn into `IN ()`."""
        from app.core.enums import Timeframe
        from app.services import ingestion

        assert ingestion._existing_bars(
            session, instrument.id, provider.id, Timeframe.M15, []
        ) == {}
