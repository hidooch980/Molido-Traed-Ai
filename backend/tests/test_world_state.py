"""World state tests (phase 12)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.enums import Timeframe
from app.services import world_state
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


class TestAssembly:
    def test_every_block_reports_its_own_availability(self, session, instrument, provider):
        """A null field and a missing measurement must be distinguishable."""
        state = world_state.build(session, instrument.id, Timeframe.H1, after(10))

        for name, block in state.blocks.items():
            assert isinstance(block.available, bool), name
            if not block.available:
                assert block.reason, f"{name} is unavailable without saying why"

    def test_missing_data_does_not_produce_zeros(self, session, instrument, provider):
        state = world_state.build(session, instrument.id, Timeframe.H1, after(10))
        payload = state.as_dict()

        assert payload["price"]["available"] is False
        assert "close" not in payload["price"]

    def test_populated_state_fills_the_blocks(self, session, instrument, provider):
        seed(session, instrument, provider, 400)

        state = world_state.build(session, instrument.id, Timeframe.H1, after(400))

        assert state.blocks["price"].available is True
        assert state.blocks["session"].available is True
        assert state.blocks["features"].available is True
        assert state.blocks["memory"].available is True

    def test_one_failing_block_does_not_sink_the_rest(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider, 400)
        monkeypatch.setattr(
            world_state, "_memory_block",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        state = world_state.build(session, instrument.id, Timeframe.H1, after(400))

        assert state.blocks["memory"].available is False
        assert "boom" in state.blocks["memory"].reason
        assert state.blocks["price"].available is True

    def test_unavailable_facets_are_named(self, session, instrument):
        payload = world_state.build(session, instrument.id, Timeframe.H1, after(10)).as_dict()

        assert "macro" in payload["unavailable"]
        assert "sentiment" in payload["unavailable"]
        assert "regime" in payload["unavailable"]

    def test_freshness_flags_stale_data(self, session, instrument, provider):
        seed(session, instrument, provider, 100)

        fresh = world_state.build(session, instrument.id, Timeframe.H1, after(101))
        stale = world_state.build(session, instrument.id, Timeframe.H1, after(400))

        assert fresh.blocks["freshness"].data["stale"] is False
        assert stale.blocks["freshness"].data["stale"] is True

    def test_state_cannot_see_past_its_cutoff(self, session, instrument, provider):
        seed(session, instrument, provider, 400)

        state = world_state.build(session, instrument.id, Timeframe.H1, after(200))
        price = state.blocks["price"].data

        assert datetime.fromisoformat(price["event_time"]) < after(200)

    def test_payload_is_serialisable(self, session, instrument, provider):
        import json

        seed(session, instrument, provider, 300)
        state = world_state.build(session, instrument.id, Timeframe.H1, after(300))

        assert json.dumps(state.as_dict())

    def test_naive_as_of_defaults_to_now_not_a_crash(self, session, instrument, provider):
        state = world_state.build(session, instrument.id, Timeframe.H1)

        assert state.as_of.tzinfo is not None
