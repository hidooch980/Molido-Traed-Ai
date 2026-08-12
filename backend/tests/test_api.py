"""API contract tests.

The database dependency is overridden with the in-memory session, so these
exercise routing, validation and error mapping without a live Postgres.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.enums import Timeframe
from app.db.session import get_db
from app.main import app
from tests.conftest import BASE_TIME, insert_bar


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_liveness_does_not_require_dependencies(client):
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_trace_id_is_echoed(client):
    response = client.get("/health/live", headers={"x-trace-id": "abc123"})

    assert response.headers["x-trace-id"] == "abc123"


def test_list_instruments(client, instrument):
    response = client.get("/api/v1/instruments")

    assert response.status_code == 200
    assert [row["symbol"] for row in response.json()] == ["EURUSD"]


def test_unknown_instrument_returns_404_with_error_code(client):
    response = client.get(f"/api/v1/instruments/{'0' * 8}-0000-0000-0000-{'0' * 12}")

    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_bars_endpoint_requires_as_of(client, instrument):
    response = client.get(
        "/api/v1/bars",
        params={"instrument_id": str(instrument.id), "timeframe": "H1"},
    )

    assert response.status_code == 422, "an implicit 'now' would invite lookahead"


def test_bars_endpoint_enforces_point_in_time(client, session, instrument, provider):
    for i in range(6):
        insert_bar(
            session,
            instrument.id,
            provider.id,
            event_time=BASE_TIME + timedelta(hours=i),
            ingested_at=BASE_TIME,
            close=1.1 + i * 0.001,
        )

    response = client.get(
        "/api/v1/bars",
        params={
            "instrument_id": str(instrument.id),
            "timeframe": Timeframe.H1.value,
            "as_of": (BASE_TIME + timedelta(hours=3)).isoformat(),
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["count"] == 3
    assert body["training_eligible"] is False
    assert all(
        datetime.fromisoformat(bar["event_time"]) + timedelta(hours=1)
        <= BASE_TIME + timedelta(hours=3)
        for bar in body["bars"]
    )


def test_data_quality_endpoint_reports_seeded_defects(client, session, instrument, provider):
    from app.core.enums import Timeframe as TF
    from app.services import data_quality
    from tests.conftest import make_bars

    bars = make_bars(120)
    del bars[40:45]
    report = data_quality.evaluate_bars(bars, TF.H1)
    data_quality.persist_findings(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=TF.H1,
        findings=report.findings,
    )
    data_quality.update_dataset_quality(
        session,
        instrument_id=instrument.id,
        provider_id=provider.id,
        timeframe=TF.H1,
        report=report,
    )

    response = client.get(f"/api/v1/data-quality/{instrument.id}")
    body = response.json()

    assert response.status_code == 200
    assert any(f["issue"] == "missing_candle" for f in body["findings"])
    # No bars were stored here, only evaluated — and the rollup measures stored
    # history, so the dataset reports zero and stays ineligible.
    assert body["datasets"][0]["actual_bars"] == 0
    assert body["datasets"][0]["is_training_eligible"] is False


def test_session_status_reports_open_market(client, instrument):
    response = client.get(
        f"/api/v1/sessions/{instrument.id}",
        params={"at": "2024-03-06T14:00:00Z"},  # Wednesday, London/NY overlap
    )
    body = response.json()

    assert response.status_code == 200
    assert body["is_open"] is True
    assert set(body["active_sessions"]) >= {"london", "new_york"}
    assert body["market_code"] == "FX"


def test_session_status_reports_closed_weekend(client, instrument):
    response = client.get(
        f"/api/v1/sessions/{instrument.id}",
        params={"at": "2024-03-09T14:00:00Z"},  # Saturday
    )
    body = response.json()

    assert body["is_open"] is False
    assert body["active_sessions"] == ["off"]
    assert body["next_open"] is not None, "a closed market must say when it reopens"


def test_holiday_listing(client, session):
    from datetime import date

    from app.services.sessions import upsert_holiday

    upsert_holiday(session, "FX", date(2024, 12, 25), name="Christmas")

    response = client.get("/api/v1/sessions", params={"market_code": "FX"})
    body = response.json()

    assert response.status_code == 200
    assert body[0]["name"] == "Christmas"


def test_symbol_dna_names_what_it_cannot_compute(client, session, instrument, provider):
    """The response must show the gaps, not just the answers."""
    from tests.test_symbol_dna import seed

    seed(session, instrument, provider, count=400)

    response = client.get(
        f"/api/v1/symbol-dna/{instrument.id}", params={"live": "true"}
    )
    body = response.json()

    assert response.status_code == 200
    kinds = {p["kind"] for p in body["profiles"]}
    assert {"volatility", "structure", "clock"} <= kinds
    assert "news_sensitivity" in body["unavailable"]
    # Every profile states how much evidence it rests on.
    assert all(p["sample_size"] > 0 for p in body["profiles"])


def test_symbol_dna_without_history_is_a_clear_error(client, instrument):
    response = client.get(
        f"/api/v1/symbol-dna/{instrument.id}", params={"live": "true"}
    )

    assert response.status_code == 409
    assert response.json()["error"] == "insufficient_data"


def test_memory_returns_every_horizon(client, session, instrument, provider):
    """Unavailable horizons are listed too — an absent key would hide them."""
    from tests.test_market_memory import after, seed

    seed(session, instrument, provider, 200)

    response = client.get(
        f"/api/v1/memory/{instrument.id}",
        params={"as_of": after(200).isoformat()},
    )
    body = response.json()

    assert response.status_code == 200
    assert {h["horizon"] for h in body["horizons"]} == {"short", "medium", "long"}

    short = next(h for h in body["horizons"] if h["horizon"] == "short")
    assert short["available"] is True
    assert short["trend"] == "up"

    long_term = next(h for h in body["horizons"] if h["horizon"] == "long")
    assert long_term["available"] is False
    assert "needs" in long_term["reason"]


def test_memory_agreement_is_reported_not_resolved(client, session, instrument, provider):
    from tests.test_market_memory import after, seed

    seed(session, instrument, provider, 200)

    body = client.get(
        f"/api/v1/memory/{instrument.id}",
        params={"as_of": after(200).isoformat()},
    ).json()

    assert "aligned" in body["agreement"]
    assert "trends" in body["agreement"]


def test_root_advertises_docs(client):
    assert client.get("/").json()["docs"] == "/docs"


def test_naive_as_of_is_rejected_with_domain_error(client, instrument):
    """A naive timestamp must fail loudly, not be silently assumed to be UTC."""
    response = client.get(
        "/api/v1/bars",
        params={
            "instrument_id": str(instrument.id),
            "timeframe": "H1",
            "as_of": "2024-03-04T12:00:00",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"] == "validation_failed"
