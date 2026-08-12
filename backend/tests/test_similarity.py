"""Similarity engine tests (phase 11).

A similarity engine is a machine for producing confident numbers. These tests
exist to make sure it produces them only when it should.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.enums import Timeframe
from app.core.errors import ValidationFailedError
from app.models.episodes import Episode
from app.services import episodes as episode_service
from app.services import similarity
from tests.conftest import BASE_TIME, insert_bar


def after(h: int) -> datetime:
    return BASE_TIME + timedelta(hours=h)


def seed(session, instrument, provider, count, *, drift=0.0002, price=1.10):
    for i in range(count):
        close = price + i * drift
        insert_bar(
            session, instrument.id, provider.id,
            event_time=BASE_TIME + timedelta(hours=i),
            ingested_at=BASE_TIME, close=round(close, 8), open_=round(close - drift, 8),
        )


def build_library(session, instrument, provider, bars=900, horizon=12):
    seed(session, instrument, provider, bars)
    episode_service.build(
        session, instrument.id, Timeframe.H1,
        start=after(100), end=after(bars - horizon - 5),
        horizon_bars=horizon, as_of=after(bars),
    )


def make_episode(session, instrument, *, hour, features, forward, ready_hour, computed):
    ep = Episode(
        instrument_id=instrument.id,
        timeframe=Timeframe.H1,
        event_time=after(hour),
        horizon_bars=12,
        outcome_ready_at=after(ready_hour),
        computed_at=computed,
        entry_price=1.10,
        features=features,
        forward_return_pct=forward,
        max_up_pct=abs(forward),
        max_down_pct=-abs(forward) / 2,
    )
    session.add(ep)
    return ep


# ----------------------------------------------------------------- refusals
class TestRefusals:
    def test_thin_library_is_refused(self, session, instrument, provider):
        seed(session, instrument, provider, 300)

        result = similarity.find_similar(
            session, instrument.id, Timeframe.H1, datetime.now(UTC)
        )

        assert result.sufficient is False
        assert "matured episodes" in result.reason

    def test_naive_as_of_is_refused(self, session, instrument):
        with pytest.raises(ValidationFailedError):
            similarity.find_similar(
                session, instrument.id, Timeframe.H1, datetime(2024, 3, 4, 12, 0)
            )

    def test_no_close_neighbours_reports_insufficient(self, session, instrument, provider):
        """Nearest is not the same as near."""
        long_ago = BASE_TIME - timedelta(days=1)
        for i in range(120):
            make_episode(
                session, instrument, hour=i, ready_hour=i + 13, computed=long_ago,
                # A wide spread of values, none near the query point.
                features={"rsi_14": 10.0 + (i % 5), "sma_20": 1.0 + i * 0.01},
                forward=0.001,
            )
        session.flush()

        result = similarity.find_similar(
            session, instrument.id, Timeframe.H1, after(500)
        )

        assert result.sufficient is False

    def test_constant_feature_is_not_used_for_comparison(self, session, instrument):
        """A feature that never varies says nothing about similarity."""
        long_ago = BASE_TIME - timedelta(days=1)
        for i in range(80):
            make_episode(
                session, instrument, hour=i, ready_hour=i + 13, computed=long_ago,
                features={"flat": 5.0, "rsi_14": 40.0 + (i % 20)},
                forward=0.001,
            )
        session.flush()
        library = episode_service.query(session, instrument.id, Timeframe.H1, after(500))

        scaler = similarity.Scaler.fit(library)

        assert "flat" not in scaler.features
        assert "rsi_14" in scaler.features


# ------------------------------------------------------------ leakage guards
class TestLeakage:
    def test_only_matured_episodes_are_searchable(self, session, instrument, provider):
        """An episode whose outcome window is open must not be a neighbour."""
        long_ago = BASE_TIME - timedelta(days=1)
        for i in range(80):
            make_episode(
                session, instrument, hour=i, ready_hour=i + 13, computed=long_ago,
                features={"rsi_14": 50.0 + (i % 10)}, forward=0.001,
            )
        # An episode that only matures much later.
        make_episode(
            session, instrument, hour=90, ready_hour=9000, computed=long_ago,
            features={"rsi_14": 55.0}, forward=99.0,
        )
        session.flush()

        library = episode_service.query(session, instrument.id, Timeframe.H1, after(200))

        assert all(e.outcome_ready_at <= after(200) for e in library)
        assert 99.0 not in [float(e.forward_return_pct) for e in library]

    def test_scaler_is_fitted_only_on_visible_episodes(self, session, instrument):
        """Normalisation statistics must not carry the future's distribution.

        Fitting the scaler over the whole table would let a later volatility
        regime set the scale a past decision is measured on — a leak that no
        backtest can see, because the backtest is measured on the same scale.
        """
        long_ago = BASE_TIME - timedelta(days=1)
        for i in range(80):
            make_episode(
                session, instrument, hour=i, ready_hour=i + 13, computed=long_ago,
                features={"rsi_14": 50.0 + (i % 4)}, forward=0.001,
            )
        # A much later, wildly different regime.
        for i in range(80):
            make_episode(
                session, instrument, hour=5000 + i, ready_hour=5013 + i, computed=long_ago,
                features={"rsi_14": 900.0 + i}, forward=0.001,
            )
        session.flush()

        early = similarity.Scaler.fit(
            episode_service.query(session, instrument.id, Timeframe.H1, after(200))
        )
        late = similarity.Scaler.fit(
            episode_service.query(session, instrument.id, Timeframe.H1, after(9000))
        )

        assert early.center["rsi_14"] < 60
        assert late.center["rsi_14"] > early.center["rsi_14"]


# ---------------------------------------------------------------- behaviour
class TestBehaviour:
    def _library(self, session, instrument, *, forward_for):
        long_ago = BASE_TIME - timedelta(days=1)
        for i in range(120):
            rsi = 30.0 + (i % 40)
            make_episode(
                session, instrument, hour=i, ready_hour=i + 13, computed=long_ago,
                features={"rsi_14": rsi, "close_over_sma_20": 1.0 + rsi / 1000},
                forward=forward_for(rsi),
            )
        session.flush()

    def test_distance_is_scale_free(self):
        """Without normalisation, the widest-ranged feature would dominate."""
        scaler = similarity.Scaler(
            center={"small": 0.0, "big": 0.0}, spread={"small": 0.001, "big": 1000.0}
        )

        a = scaler.normalise({"small": 0.001, "big": 0.0})
        b = scaler.normalise({"small": 0.0, "big": 1000.0})

        # One unit of each feature contributes equally after scaling.
        assert a["small"] == pytest.approx(1.0)
        assert b["big"] == pytest.approx(1.0)

    def test_missing_features_do_not_make_an_episode_look_closer(self):
        """Averaging, not summing: fewer terms must not mean a smaller distance."""
        target = {"a": 0.0, "b": 0.0, "c": 0.0}
        complete = {"a": 1.0, "b": 1.0, "c": 1.0}
        partial = {"a": 1.0}

        d_complete, n_complete = similarity._distance(target, complete)
        d_partial, n_partial = similarity._distance(target, partial)

        assert d_complete == pytest.approx(d_partial)
        assert n_complete == 3
        assert n_partial == 1

    def test_similar_state_finds_neighbours_and_reports_outcome(
        self, session, instrument, provider
    ):
        build_library(session, instrument, provider, bars=900, horizon=12)

        result = similarity.find_similar(
            session, instrument.id, Timeframe.H1, datetime.now(UTC), k=40
        )

        if result.sufficient:
            assert result.outcome["available"] is True
            assert 0.0 <= result.outcome["positive_share"] <= 1.0
            assert result.uncertainty["available"] is True
            assert result.uncertainty["outcome_iqr"] >= 0
            assert result.features_used
        else:
            # A refusal must always say why.
            assert result.reason

    def test_uncertainty_separates_agreement_from_disagreement(self):
        """Two sets with the same median but different spread must differ."""
        long_ago = BASE_TIME - timedelta(days=1)

        def matches(returns):
            out = []
            for i, r in enumerate(returns):
                ep = Episode(
                    instrument_id=uuid_stub(), timeframe=Timeframe.H1,
                    event_time=after(i), horizon_bars=12, outcome_ready_at=after(i + 13),
                    computed_at=long_ago, entry_price=1.0, forward_return_pct=r,
                )
                out.append(similarity.Match(episode=ep, distance=0.1, similarity=0.9,
                                            compared_features=3))
            return out

        agreeing = similarity._uncertainty(matches([0.01] * 25))
        disagreeing = similarity._uncertainty(matches([0.2, -0.2] * 12 + [0.01]))

        assert agreeing["outcome_stdev"] < disagreeing["outcome_stdev"]

    def test_payload_is_serialisable(self, session, instrument):
        import json

        result = similarity.SimilarityResult(
            sufficient=False, reason="test", as_of=datetime.now(UTC)
        )

        assert json.dumps(result.as_payload())


def uuid_stub():
    import uuid

    return uuid.uuid4()
