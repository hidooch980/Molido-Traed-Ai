"""TradingView webhook: a wrong secret is refused, a right one is stored, and
nothing on the way can reach an order."""

from __future__ import annotations

import ast
import inspect

import pytest
from fastapi.testclient import TestClient

from app.integrations import tradingview
from app.models.tradingview import TradingViewAlert, TradingViewConfig

WEBHOOK = "/api/v1/tradingview/webhook"


@pytest.fixture()
def client(session):
    from app.db.session import get_db
    from app.main import app

    tradingview.LIMIT._seen.clear()
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def configure(session, secret="s3cret-value"):
    session.add(TradingViewConfig(secret_hash=tradingview.hash_secret(secret), secret_hint=secret[:4]))
    session.commit()
    return secret


class TestNothingCanTrade:
    @pytest.mark.parametrize(
        "module", ["app.api.v1.tradingview", "app.integrations.tradingview"]
    )
    def test_the_modules_never_import_execution_or_the_pipeline(self, module):
        import importlib

        tree = ast.parse(inspect.getsource(importlib.import_module(module)))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        assert not any(m.startswith(("app.execution", "app.pipeline", "app.workers")) for m in imported)


class TestTheWebhook:
    def test_unconfigured_refuses_everything(self, client, session):
        response = client.post(WEBHOOK, json={"secret": "anything", "symbol": "EURUSD"})

        assert response.status_code == 401
        assert session.query(TradingViewAlert).count() == 0

    def test_a_wrong_secret_is_refused(self, client, session):
        configure(session)

        response = client.post(WEBHOOK, json={"secret": "wrong", "symbol": "EURUSD"})

        assert response.status_code == 401
        assert session.query(TradingViewAlert).count() == 0

    def test_a_missing_secret_is_refused(self, client, session):
        configure(session)

        assert client.post(WEBHOOK, json={"symbol": "EURUSD"}).status_code == 401

    def test_plain_text_is_refused_with_a_hint(self, client, session):
        configure(session)

        response = client.post(WEBHOOK, content=b"EURUSD buy")

        assert response.status_code == 400
        assert "JSON" in response.text

    def test_the_right_secret_stores_and_trades_nothing(self, client, session):
        secret = configure(session)

        response = client.post(
            WEBHOOK,
            json={"secret": secret, "ticker": "eurusd", "action": "BUY", "price": "1.1", "interval": "60"},
        )

        assert response.status_code == 202
        assert response.json()["traded"] is False
        row = session.query(TradingViewAlert).one()
        assert (row.symbol, row.action, row.price, row.timeframe) == ("EURUSD", "buy", 1.1, "60")
        assert "secret" not in row.payload

    def test_a_burst_is_limited(self, client, session):
        configure(session)
        codes = [
            client.post(WEBHOOK, json={"secret": "wrong"}).status_code
            for _ in range(tradingview.BURST + 1)
        ]

        assert codes[-1] == 429

    def test_an_oversized_body_is_refused(self, client, session):
        secret = configure(session)

        response = client.post(
            WEBHOOK, json={"secret": secret, "message": "x" * tradingview.MAX_BODY_BYTES}
        )

        assert response.status_code == 413


class TestTheSecret:
    def test_it_is_stored_only_as_a_hash(self, session):
        secret = tradingview.new_secret()

        assert tradingview.secret_matches(secret, tradingview.hash_secret(secret))
        assert secret not in tradingview.hash_secret(secret)

    def test_an_empty_hash_matches_nothing(self):
        assert not tradingview.secret_matches("", "")
        assert not tradingview.secret_matches(None, tradingview.hash_secret("x"))

    def test_making_one_needs_more_than_read(self, client):
        assert client.post("/api/v1/tradingview/secret").status_code in (401, 403)

    def test_the_state_never_contains_the_secret(self, client, session):
        secret = configure(session)

        body = client.get("/api/v1/tradingview").json()

        assert body["configured"] is True
        assert secret not in str(body)
