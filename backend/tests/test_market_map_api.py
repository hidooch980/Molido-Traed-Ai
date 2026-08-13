"""Market map and scanner (spec §43).

These two were reported as having nothing behind them, which was wrong: the
audit matched menu keys against router names, and their backing lives in a
service. So the first test here is about that mistake — it asserts the routes
exist and answer, which is the check whose absence let the wrong claim stand.

The rest are about the map's one job: telling a measured correlation apart from
an unmeasured pair. Collapsing those is how a book looks diversified while it
is one position, and it is the same distinction the portfolio brain refuses to
blur.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.brain.portfolio import CORRELATION_CLUSTER
from app.core.enums import Timeframe
from app.services.symbol_dna import SymbolProfile
from tests.conftest import BASE_TIME


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def store_correlation(session, instrument, pairs: dict, *, days_old: int = 1):
    """A stored DNA snapshot, the way the collector writes one."""
    moment = BASE_TIME + timedelta(days=30 - days_old)
    session.add(
        SymbolProfile(
            instrument_id=instrument.id,
            timeframe=Timeframe.H1,
            kind="correlation",
            as_of=moment,
            computed_at=moment,
            coverage_start=BASE_TIME,
            coverage_end=moment,
            sample_size=1000,
            profile_version=1,
            data={"pairs": pairs},
        )
    )
    session.flush()


class TestTheRoutesExistAtAll:
    """The check whose absence let me report these as unbacked."""

    def test_the_map_answers(self, client):
        assert client.get("/api/v1/market-map").status_code == 200

    def test_the_scanner_answers(self, client):
        assert client.get("/api/v1/market-map/scanner").status_code == 200

    def test_neither_mutates(self, client):
        from app.api.guard import find_ungated_routes, mutating_routes
        from app.main import app

        assert mutating_routes(app) == []
        assert find_ungated_routes(app, require_auth=False) == []


class TestMeasuredIsNotTheSameAsUnmeasured:
    def test_an_instrument_without_a_snapshot_is_named(self, client, instrument):
        payload = client.get("/api/v1/market-map").json()

        assert payload["measured_pairs"] == 0
        assert any(instrument.symbol in u for u in payload["unmeasured"])

    def test_a_stored_pair_is_reported_with_its_sample(self, client, session, instrument):
        store_correlation(
            session, instrument, {"GBPUSD": {"correlation": 0.82, "aligned_bars": 900}}
        )

        payload = client.get("/api/v1/market-map").json()

        assert payload["measured_pairs"] == 1
        pair = payload["pairs"][0]
        assert pair["aligned_bars"] == 900
        assert pair["clustered"] is True

    def test_a_weak_correlation_is_not_clustered(self, client, session, instrument):
        store_correlation(
            session, instrument, {"USDJPY": {"correlation": 0.11, "aligned_bars": 900}}
        )

        pair = client.get("/api/v1/market-map").json()["pairs"][0]

        assert pair["clustered"] is False

    def test_a_strong_negative_correlation_is_still_one_bet(self, client, session, instrument):
        """Minus 0.9 is as much a shared risk as plus 0.9."""
        store_correlation(
            session, instrument, {"USDCHF": {"correlation": -0.91, "aligned_bars": 900}}
        )

        assert client.get("/api/v1/market-map").json()["pairs"][0]["clustered"] is True

    def test_a_null_correlation_is_dropped_rather_than_shown_as_zero(
        self, client, session, instrument
    ):
        store_correlation(
            session, instrument, {"EURGBP": {"correlation": None, "aligned_bars": 20}}
        )

        assert client.get("/api/v1/market-map").json()["measured_pairs"] == 0

    def test_the_threshold_comes_from_the_portfolio_brain(self, client):
        """Retyping it would let the map and the risk layer disagree about what
        'correlated' means."""
        payload = client.get("/api/v1/market-map").json()

        assert payload["cluster_threshold"] == CORRELATION_CLUSTER

    def test_the_response_states_the_distinction(self, client):
        payload = client.get("/api/v1/market-map").json()

        assert "not an uncorrelated pair" in payload["note"]


class TestFreshnessIsReportedNotImplied:
    def test_the_snapshot_age_is_published(self, client, session, instrument):
        store_correlation(
            session, instrument, {"GBPUSD": {"correlation": 0.8, "aligned_bars": 900}}
        )

        payload = client.get("/api/v1/market-map").json()

        assert payload["oldest_snapshot"] is not None
        assert payload["snapshots_used"] == 1

    def test_the_page_says_it_reads_stored_snapshots(self, client):
        """Rather than implying the number is live."""
        payload = client.get("/api/v1/market-map").json()

        assert "not recomputed" in payload["freshness"]


class TestTheScannerRefusesToRank:
    def test_it_says_it_is_not_a_signal_list(self, client):
        payload = client.get("/api/v1/market-map/scanner").json()

        assert payload["not_a_signal_list"] is True
        assert "almost no information" in payload["note"]

    def test_it_publishes_no_conviction_field(self, client, instrument):
        """Ranking by conviction would publish the one number this system has
        measured to be uninformative."""
        rows = client.get("/api/v1/market-map/scanner").json()["instruments"]

        assert rows
        assert all("conviction" not in row for row in rows)

    def test_an_instrument_with_no_bars_reports_unknown_age_not_zero(
        self, client, instrument
    ):
        """Not knowing how old a feed is is not the same as it being fresh, and
        the risk brain blocks on exactly this distinction."""
        row = client.get("/api/v1/market-map/scanner").json()["instruments"][0]

        assert row["data_age_seconds"] is None

    def test_instruments_without_profiles_are_listed(self, client, instrument):
        payload = client.get("/api/v1/market-map/scanner").json()

        assert instrument.symbol in payload["without_profiles"]

    def test_the_order_is_stable_between_requests(self, client, instrument):
        """A map whose rows move between refreshes cannot be compared with the
        one somebody saw yesterday."""
        first = [r["symbol"] for r in client.get("/api/v1/market-map/scanner").json()["instruments"]]
        second = [r["symbol"] for r in client.get("/api/v1/market-map/scanner").json()["instruments"]]

        assert first == second == sorted(first)

    def test_the_limit_is_bounded(self, client):
        assert client.get("/api/v1/market-map/scanner", params={"limit": 999}).status_code == 422
