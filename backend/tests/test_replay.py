"""Replay and what-if tests (phases 41-42).

The determinism test is the important one here and it is not really about
replay: it is the only direct evidence that the pipeline reads through the
point-in-time layer rather than around it. A decision that cannot be reproduced
invalidates every backtest the same code path produced.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.enums import Decision, Timeframe
from app.core.errors import ValidationFailedError
from app.pipeline import replay as rp
from tests.conftest import BASE_TIME
from tests.test_pipeline import (
    after,
    calibrated,
    good_health,
    healthy_account,
    measured_history,
    seed,
    stub_brain,
    uncalibrated,
)


def inputs(**overrides):
    defaults = dict(
        account=healthy_account(),
        health=good_health(),
        calibration=calibrated(),
        history=measured_history(),
        account_id="acct-1",
        base_currency="EUR",
        quote_currency="USD",
        r_value_pct=0.002,
    )
    defaults.update(overrides)
    return defaults


def record(session, instrument, monkeypatch, *, decision=Decision.BUY, **overrides):
    stub_brain(monkeypatch, decision=decision)
    store = rp.TraceStore()
    from app.pipeline.decide import decide

    payload = inputs(**overrides)
    trace = decide(session, instrument.id, Timeframe.H1, as_of=after(400), **payload)
    return store, store.record(trace, instrument_id=instrument.id, inputs=payload)


# ============================================================== determinism
class TestTheSameInstantGivesTheSameAnswer:
    def test_two_runs_at_one_as_of_agree(self, session, instrument, provider, monkeypatch):
        """If this fails, something is reading the present."""
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        result = rp.verify_determinism(
            session, instrument.id, Timeframe.H1, after(400), inputs(), runs=3
        )

        assert result.matched is True
        assert result.differences == []

    def test_a_stored_decision_replays_identically(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch)

        result = rp.replay(session, stored)

        assert result.matched is True

    def test_replay_reproduces_a_refusal_too(self, session, instrument, provider, monkeypatch):
        """A refusal is a decision, and it has to reproduce as exactly as a trade."""
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch, calibration=uncalibrated())

        result = rp.replay(session, stored)

        assert result.matched is True
        assert result.original_stopped_at == "expected_value"

    def test_a_bar_ingested_later_does_not_leak_into_the_replay(
        self, session, instrument, provider, monkeypatch
    ):
        """The point of the whole point-in-time layer, stated as a test.

        A revision that arrives after the decision must not change what the
        decision sees when it is re-run, or every backtest built on this path
        is reading corrections it could not have had.
        """
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch)

        from tests.conftest import insert_bar

        insert_bar(
            session, instrument.id, provider.id,
            event_time=BASE_TIME + timedelta(hours=399),
            ingested_at=BASE_TIME + timedelta(days=90),  # learned long afterwards
            close=1.5000, revision=2,
        )

        assert rp.replay(session, stored).matched is True

    def test_a_single_run_cannot_prove_determinism(self, session, instrument, provider):
        with pytest.raises(ValidationFailedError):
            rp.verify_determinism(
                session, instrument.id, Timeframe.H1, after(400), inputs(), runs=1
            )


# =================================================================== store
class TestTheStore:
    def test_a_recorded_decision_can_be_fetched(self, session, instrument, provider, monkeypatch):
        seed(session, instrument, provider)
        store, stored = record(session, instrument, monkeypatch)

        assert store.get(stored.trace_id) is stored
        assert store.get(uuid.uuid4()) is None

    def test_the_store_says_where_decisions_die(
        self, session, instrument, provider, monkeypatch
    ):
        """'Nothing traded this week' becomes a sentence somebody can act on."""
        seed(session, instrument, provider)
        store, _ = record(session, instrument, monkeypatch)
        from app.pipeline.decide import decide

        for calibration in (uncalibrated(), uncalibrated()):
            trace = decide(
                session, instrument.id, Timeframe.H1, as_of=after(400),
                **inputs(calibration=calibration),
            )
            store.record(trace, instrument_id=instrument.id, inputs=inputs())

        counts = store.stopped_at_counts()

        assert counts["expected_value"] == 2
        assert sum(counts.values()) == 3

    def test_traces_come_back_in_time_order(self, session, instrument, provider, monkeypatch):
        seed(session, instrument, provider)
        store, _ = record(session, instrument, monkeypatch)
        from app.pipeline.decide import decide

        for hours in (350, 380):
            trace = decide(
                session, instrument.id, Timeframe.H1, as_of=after(hours), **inputs()
            )
            store.record(trace, instrument_id=instrument.id, inputs=inputs())

        stamps = [s.as_of for s in store.all()]
        assert stamps == sorted(stamps)


# ================================================================= what-if
class TestWhatIf:
    def test_a_smaller_account_changes_the_answer(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch)

        result = rp.what_if(
            session, stored, health=good_health(safe_mode=True)
        )

        assert result.verdict_changed is True
        assert result.alternative_stopped_at == "risk"

    def test_it_re_runs_the_gates_rather_than_re_scoring(
        self, session, instrument, provider, monkeypatch
    ):
        """An analysis that disagrees with what the system would do is worse
        than none, so the alternative walks the same chain."""
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch, calibration=uncalibrated())

        result = rp.what_if(session, stored, calibration=calibrated())

        assert stored.trace.stopped_at == "expected_value"
        assert result.alternative_stopped_at != "expected_value"

    def test_changing_the_levels_carries_a_caveat(
        self, session, instrument, provider, monkeypatch
    ):
        """Nothing in the data says how the market treats a stop never placed."""
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch)

        result = rp.what_if(session, stored, r_value_pct=0.02)

        assert any("recorded bars" in c for c in result.caveats)

    def test_an_alternative_that_trades_where_the_original_did_not_is_flagged(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch, calibration=uncalibrated())

        result = rp.what_if(session, stored, calibration=calibrated())

        assert any("no realised outcome" in c for c in result.caveats)

    def test_the_payload_always_states_what_it_cannot_know(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch)

        payload = rp.what_if(session, stored, account=healthy_account(equity=1_000.0)).as_dict()

        assert "not in the data" in payload["note"]

    def test_a_what_if_with_nothing_changed_is_refused(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch)

        with pytest.raises(ValidationFailedError) as exc:
            rp.what_if(session, stored)

        assert "replay" in str(exc.value)

    def test_an_input_the_original_never_had_is_refused(
        self, session, instrument, provider, monkeypatch
    ):
        """That would be a different question, not a variation on this one."""
        seed(session, instrument, provider)
        _, stored = record(session, instrument, monkeypatch)

        with pytest.raises(ValidationFailedError):
            rp.what_if(session, stored, challenge_rules=object())
