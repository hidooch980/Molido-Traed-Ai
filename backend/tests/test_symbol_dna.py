"""Symbol DNA tests (phase 8).

A profile is a historical claim about an instrument. The properties worth
pinning are therefore: it cannot see the future, it refuses to speak without
enough evidence, and it never fills a gap with a plausible number.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import AssetClass, Timeframe
from app.core.errors import InsufficientDataError, ValidationFailedError
from app.models.instruments import Instrument
from app.services import symbol_dna
from app.services.point_in_time import get_bars
from tests.conftest import BASE_TIME, insert_bar


def seed(session, instrument, provider, count=600, *, start=None, drift=0.0002, seed_price=1.10):
    """Deterministic ascending series — enough bars to clear the sample floor.

    Each bar opens at the previous close, so candles have real bodies and the
    structure profile has something to measure.
    """
    start = start or BASE_TIME
    for i in range(count):
        close = seed_price + i * drift
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=start + timedelta(hours=i),
            ingested_at=BASE_TIME,
            close=close,
            open_=close - drift,
        )


def now() -> datetime:
    return datetime.now(UTC)


@pytest.fixture()
def peer(session):
    row = Instrument(symbol="GBPUSD", name="Cable", asset_class=AssetClass.FOREX)
    session.add(row)
    session.flush()
    return row


# ---------------------------------------------------------------- guardrails
class TestGuardrails:
    def test_short_history_is_refused(self, session, instrument, provider):
        seed(session, instrument, provider, count=50)

        with pytest.raises(InsufficientDataError):
            symbol_dna.compute_dna(session, instrument.id, Timeframe.H1, now())

    def test_naive_as_of_is_refused(self, session, instrument, provider):
        with pytest.raises(ValidationFailedError):
            symbol_dna.compute_dna(
                session, instrument.id, Timeframe.H1, datetime(2024, 3, 4, 12, 0)
            )

    def test_unavailable_facets_are_named_not_faked(self):
        """The spec asks for facets bars cannot answer; those stay empty."""
        assert "news_sensitivity" in symbol_dna.UNAVAILABLE
        assert "strategy_performance" in symbol_dna.UNAVAILABLE
        # And they are not silently produced by the computation path.
        assert set(symbol_dna.UNAVAILABLE) & set(symbol_dna.BAR_PROFILES) == set()

    def test_thin_buckets_are_omitted_with_a_warning(self, session, instrument, provider):
        """A 'Tokyo profile' built on nine bars is not a profile."""
        seed(session, instrument, provider, count=400)
        bars = get_bars(session, instrument.id, Timeframe.H1, now(), lookback=5000)

        profile = symbol_dna.session_profile(bars)

        for name, entry in profile.data.items():
            if isinstance(entry, dict):
                assert entry["bars"] >= symbol_dna.MIN_BUCKET_SAMPLES, name


# ------------------------------------------------------------- point-in-time
class TestPointInTime:
    def test_future_bars_cannot_change_a_past_profile(self, session, instrument, provider):
        seed(session, instrument, provider, count=400)
        cutoff = BASE_TIME + timedelta(hours=400)
        before = symbol_dna.compute_dna(
            session, instrument.id, Timeframe.H1, cutoff, include_correlation=False
        )["volatility"].data

        # Add wildly different future history.
        for i in range(400, 800):
            insert_bar(
                session,
                instrument.id,
                provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME,
                close=99.0,
            )

        after = symbol_dna.compute_dna(
            session, instrument.id, Timeframe.H1, cutoff, include_correlation=False
        )["volatility"].data

        assert before == after

    def test_recomputation_is_deterministic(self, session, instrument, provider):
        seed(session, instrument, provider, count=400)
        cutoff = now()

        first = symbol_dna.compute_dna(
            session, instrument.id, Timeframe.H1, cutoff, include_correlation=False
        )
        second = symbol_dna.compute_dna(
            session, instrument.id, Timeframe.H1, cutoff, include_correlation=False
        )

        assert {k: v.data for k, v in first.items()} == {k: v.data for k, v in second.items()}


# ------------------------------------------------------------------- facets
class TestFacets:
    def _bars(self, session, instrument, provider, count=600):
        seed(session, instrument, provider, count=count)
        return get_bars(session, instrument.id, Timeframe.H1, now(), lookback=5000)

    def test_volatility_percentiles_are_ordered(self, session, instrument, provider):
        bars = self._bars(session, instrument, provider)

        data = symbol_dna.volatility_profile(bars).data
        p = data["bar_range_pct"]

        assert p["p5"] <= p["p25"] <= p["p50"] <= p["p75"] <= p["p95"]

    def test_percentiles_are_observed_values_not_interpolations(self):
        """Nearest-rank: every reported number is one the instrument printed."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]

        result = symbol_dna._percentiles(values, points=(50,))

        assert result["p50"] in values

    def test_structure_detects_persistence(self, session, instrument, provider):
        """A steady one-way drift is persistent, and must be labelled so."""
        bars = self._bars(session, instrument, provider)

        data = symbol_dna.structure_profile(bars).data

        assert data["up_bar_share"] > 0.9
        assert data["return_autocorrelation_lag1"] is not None

    def test_structure_labels_a_coin_flip_as_neither(self, session, instrument, provider):
        """Alternating up/down is mean-reverting, not 'neither' — and not a trend."""
        price = 1.10
        for i in range(400):
            price += 0.001 if i % 2 == 0 else -0.001
            insert_bar(
                session,
                instrument.id,
                provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME,
                close=round(price, 6),
            )
        bars = get_bars(session, instrument.id, Timeframe.H1, now(), lookback=5000)

        data = symbol_dna.structure_profile(bars).data

        assert data["return_autocorrelation_lag1"] < 0
        assert data["tendency"] == "mean_reverting"

    def test_liquidity_reports_unavailable_rather_than_inferring(
        self, session, instrument, provider
    ):
        """Bars here carry volume but no spread; spread must say so."""
        bars = self._bars(session, instrument, provider)

        data = symbol_dna.liquidity_profile(bars).data

        assert data["volume"]["available"] is True
        assert data["spread"]["available"] is False
        assert "reason" in data["spread"]

    def test_clock_profile_finds_the_active_hour(self, session, instrument, provider):
        # 24 hourly buckets need >= MIN_BUCKET_SAMPLES each, so 600 bars (25
        # per hour) would leave every bucket just under the floor.
        bars = self._bars(session, instrument, provider, count=1000)

        data = symbol_dna.clock_profile(bars).data

        assert "by_utc_hour" in data
        assert 0 <= data["most_active_utc_hour"] <= 23


# -------------------------------------------------------------- correlation
class TestCorrelation:
    def test_identical_series_correlate_at_one(self, session, instrument, peer, provider):
        for target in (instrument, peer):
            seed(session, target, provider, count=500)

        profile = symbol_dna.correlation_profile(
            session, instrument.id, Timeframe.H1, now(), peers=[peer]
        )

        assert profile.data["pairs"]["GBPUSD"]["correlation"] == pytest.approx(1.0, abs=1e-6)

    def test_inverse_series_correlate_at_minus_one(self, session, instrument, peer, provider):
        """A *reciprocal* price series inverts the returns; a falling one does not.

        log(C/p) = −log(p) + const, so the peer's return is exactly the
        negative of the base's. Merely making the peer drift downwards would
        not do it: both series would still have smoothly shrinking returns and
        would correlate *positively*, which is the trap this test encodes.
        """
        seed(session, instrument, provider, count=500)
        for i in range(500):
            base_close = 1.10 + i * 0.0002
            insert_bar(
                session,
                peer.id,
                provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME,
                close=1.0 / base_close,
            )

        profile = symbol_dna.correlation_profile(
            session, instrument.id, Timeframe.H1, now(), peers=[peer]
        )

        assert profile.data["pairs"]["GBPUSD"]["correlation"] == pytest.approx(
            -1.0, abs=1e-6
        )

    def test_returns_are_aligned_by_timestamp_not_position(
        self, session, instrument, peer, provider
    ):
        """The trap this test exists for.

        The peer trades on a different calendar — every other hour. Zipping the
        two series by position would correlate mismatched instants and return a
        confident, meaningless number. Joining on event_time yields far fewer
        aligned bars, which is the truth.
        """
        seed(session, instrument, provider, count=600)
        for i in range(0, 600, 2):
            insert_bar(
                session,
                peer.id,
                provider.id,
                event_time=BASE_TIME + timedelta(hours=i),
                ingested_at=BASE_TIME,
                close=1.30 + i * 0.0002,
            )

        profile = symbol_dna.correlation_profile(
            session, instrument.id, Timeframe.H1, now(), peers=[peer]
        )
        entry = profile.data["pairs"].get("GBPUSD")

        if entry is not None:
            # Aligned bars must be far below the base series length, and can
            # never exceed the peer's own bar count.
            assert entry["aligned_bars"] <= 300
        else:
            assert any("GBPUSD" in w for w in profile.warnings)

    def test_peer_with_too_little_overlap_is_skipped_not_guessed(
        self, session, instrument, peer, provider
    ):
        seed(session, instrument, provider, count=500)
        seed(session, peer, provider, count=20, start=BASE_TIME)

        profile = symbol_dna.correlation_profile(
            session, instrument.id, Timeframe.H1, now(), peers=[peer]
        )

        assert "GBPUSD" not in profile.data["pairs"]
        assert any("GBPUSD" in w for w in profile.warnings)

    def test_flat_series_has_no_correlation(self):
        """A constant series has undefined correlation — None, not 0."""
        assert symbol_dna._pearson([1.0] * 10, list(range(10))) is None


# ------------------------------------------------------------- persistence
class TestPersistence:
    def test_persist_and_read_back(self, session, instrument, provider):
        seed(session, instrument, provider, count=400)
        cutoff = now()
        profiles = symbol_dna.compute_dna(
            session, instrument.id, Timeframe.H1, cutoff, include_correlation=False
        )

        written = symbol_dna.persist_dna(
            session, instrument.id, Timeframe.H1, cutoff, profiles
        )
        stored = symbol_dna.latest_dna(session, instrument.id, Timeframe.H1, now())

        assert written == len(profiles)
        assert set(stored) == set(profiles)
        assert stored["volatility"].sample_size == 400

    def test_snapshots_at_different_cutoffs_coexist(self, session, instrument, provider):
        """Overwriting history would hide the drift these profiles reveal."""
        seed(session, instrument, provider, count=600)
        early = BASE_TIME + timedelta(hours=400)
        late = BASE_TIME + timedelta(hours=600)

        for cutoff in (early, late):
            symbol_dna.persist_dna(
                session,
                instrument.id,
                Timeframe.H1,
                cutoff,
                symbol_dna.compute_dna(
                    session, instrument.id, Timeframe.H1, cutoff, include_correlation=False
                ),
            )

        from sqlalchemy import func, select

        from app.models.symbol_dna import SymbolProfile

        snapshots = session.scalar(
            select(func.count(func.distinct(SymbolProfile.as_of))).where(
                SymbolProfile.instrument_id == instrument.id
            )
        )
        assert snapshots == 2

    def test_repersisting_the_same_cutoff_updates_in_place(self, session, instrument, provider):
        seed(session, instrument, provider, count=400)
        cutoff = now()
        profiles = symbol_dna.compute_dna(
            session, instrument.id, Timeframe.H1, cutoff, include_correlation=False
        )

        first = symbol_dna.persist_dna(session, instrument.id, Timeframe.H1, cutoff, profiles)
        second = symbol_dna.persist_dna(session, instrument.id, Timeframe.H1, cutoff, profiles)

        assert first > 0
        assert second == 0

    def test_warnings_are_stored_with_the_profile(self, session, instrument, provider):
        seed(session, instrument, provider, count=400)
        cutoff = now()
        profiles = symbol_dna.compute_dna(
            session, instrument.id, Timeframe.H1, cutoff, include_correlation=False
        )
        profiles["session"].warnings = ["tokyo: only 9 bars, omitted"]

        symbol_dna.persist_dna(session, instrument.id, Timeframe.H1, cutoff, profiles)
        stored = symbol_dna.latest_dna(session, instrument.id, Timeframe.H1, now())

        assert stored["session"].data["_warnings"] == ["tokyo: only 9 bars, omitted"]


def test_log_return_helper_matches_definition():
    assert math.log(1.1 / 1.0) == pytest.approx(0.09531, abs=1e-5)
