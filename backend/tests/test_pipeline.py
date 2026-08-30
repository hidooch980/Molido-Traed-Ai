"""Decision-pipeline tests — the chain, not the links.

Each module in the chain has its own suite proving it decides well. These
prove something different and previously untested: that the modules are
actually wired together, in order, and that a refusal anywhere ends the walk.

The brain's own judgement is stubbed for the downstream stages. That is
deliberate — the question here is whether a BUY proposal reaches the risk gate
and dies at the right one, not whether this particular market should be bought,
which `test_brain.py` already covers.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.brain import calibration as cal
from app.brain import cognitive
from app.brain import expected_value as ev
from app.brain import portfolio as pf
from app.brain import risk as risk_brain
from app.brain import stress as stress_brain
from app.core.enums import Decision, Timeframe
from app.execution import safety as sfy
from app.pipeline import decide as pipe
from tests.conftest import BASE_TIME, insert_bar


def after(hours: int):
    return BASE_TIME + timedelta(hours=hours)


def seed(session, instrument, provider, count=400, *, drift=0.0002, price=1.10):
    for i in range(count):
        close = price + i * drift
        insert_bar(
            session, instrument.id, provider.id,
            event_time=BASE_TIME + timedelta(hours=i),
            ingested_at=BASE_TIME, close=round(close, 8), open_=round(close - drift, 8),
        )


def calibrated(observed: float = 0.72) -> cal.CalibrationReport:
    return cal.CalibrationReport(
        calibrated=True, source="council", count=500, brier=0.17, calibration_error=0.03,
        buckets=[
            cal.Bucket(lower=0.0, upper=0.5, count=200, mean_forecast=0.3, observed_rate=0.28),
            cal.Bucket(lower=0.5, upper=1.0, count=300, mean_forecast=0.75, observed_rate=observed),
        ],
    )


def uncalibrated() -> cal.CalibrationReport:
    return cal.CalibrationReport(
        calibrated=False, source="council", count=9, reason="only 9 resolved forecasts"
    )


def healthy_account(**overrides) -> risk_brain.AccountState:
    defaults = dict(
        equity=100_000.0, balance=100_000.0, peak_equity=100_000.0, daily_pnl_r=0.0,
        open_positions=0, used_margin=5_000.0, free_margin=95_000.0,
    )
    defaults.update(overrides)
    return risk_brain.AccountState(**defaults)


def good_health(**overrides) -> risk_brain.DataHealth:
    defaults = dict(
        data_age_bars=0.5, training_eligible=True, calibrated=True,
        correlation_unknown=[], safe_mode=False,
    )
    defaults.update(overrides)
    return risk_brain.DataHealth(**defaults)


def measured_history(**overrides) -> stress_brain.TradeHistory:
    defaults = dict(
        trades=300, wins=170, average_win_r=1.6, average_loss_r=1.0, calibrated=True
    )
    defaults.update(overrides)
    return stress_brain.TradeHistory(**defaults)


def stub_brain(monkeypatch, decision=Decision.BUY, conviction=0.78, symbol="EURUSD"):
    """Replace the brain's judgement, keeping everything downstream real."""

    def fake_think(session, instrument_id, timeframe, as_of=None):
        return cognitive.Proposal(
            instrument_id=instrument_id,
            symbol=symbol,
            timeframe=timeframe,
            as_of=as_of,
            decision=decision,
            conviction=conviction,
            stages=["perception", "context", "council"],
        )

    monkeypatch.setattr(pipe.cognitive, "think", fake_think)


def run(session, instrument, **overrides):
    defaults = dict(
        account=healthy_account(),
        health=good_health(),
        calibration=calibrated(),
        history=measured_history(),
        account_id="acct-1",
        base_currency="EUR",
        quote_currency="USD",
        r_value_pct=0.002,
        as_of=after(400),
    )
    defaults.update(overrides)
    return pipe.decide(session, instrument.id, Timeframe.H1, **defaults)


# ==================================================================== levels
class TestLevels:
    def test_a_buy_stops_below_and_targets_above(self):
        levels = pipe.derive_levels(1.1000, 0.0010, Decision.BUY)

        assert levels.stop < levels.entry < levels.target
        assert levels.entry - levels.stop == pytest.approx(0.0015)
        assert levels.target - levels.entry == pytest.approx(0.0030)

    def test_a_sell_is_mirrored(self):
        levels = pipe.derive_levels(1.1000, 0.0010, Decision.SELL)

        assert levels.target < levels.entry < levels.stop

    def test_no_volatility_measurement_means_no_levels(self):
        """A stop at an arbitrary distance denominates every number after it."""
        assert pipe.derive_levels(1.1000, 0.0, Decision.BUY) is None

    def test_a_wait_has_no_levels(self):
        assert pipe.derive_levels(1.1000, 0.0010, Decision.WAIT) is None


# =============================================================== the walk
class TestTheChainStopsAndSaysWhere:
    def test_a_wait_proposal_stops_at_cognition(self, session, instrument, provider, monkeypatch):
        seed(session, instrument, provider)
        stub_brain(monkeypatch, decision=Decision.WAIT)

        trace = run(session, instrument)

        assert trace.stopped_at == "cognition"
        assert trace.reached_intent is False

    def test_the_real_brain_on_ordinary_bars_usually_stops_early(
        self, session, instrument, provider
    ):
        """Stopping is the normal outcome; a chain that always trades is broken."""
        seed(session, instrument, provider)

        trace = run(session, instrument)

        assert trace.reached_intent is False
        assert trace.stopped_at is not None

    def test_missing_volatility_stops_at_levels(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider, count=8)  # atr_14 cannot warm up
        stub_brain(monkeypatch)

        trace = run(session, instrument, as_of=after(8))

        assert trace.stopped_at == "levels"
        assert "ATR" in trace.stage("levels").detail

    def test_an_uncalibrated_score_stops_at_expected_value(
        self, session, instrument, provider, monkeypatch
    ):
        """Conviction is not probability, and the chain enforces that here."""
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument, calibration=uncalibrated())

        assert trace.stopped_at == "expected_value"
        assert "calibrat" in trace.stage("expected_value").detail.lower()

    def test_a_full_book_stops_at_the_portfolio(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)
        full = [pf.Position(f"SYM{i}", "buy", 1.0, f"C{i}", "USD") for i in range(6)]

        trace = run(session, instrument, open_positions=full)

        assert trace.stopped_at == "portfolio"

    def test_safe_mode_stops_at_risk(self, session, instrument, provider, monkeypatch):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument, health=good_health(safe_mode=True))

        assert trace.stopped_at == "risk"

    def test_stale_data_stops_at_risk(self, session, instrument, provider, monkeypatch):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument, health=good_health(data_age_bars=20.0))

        assert trace.stopped_at == "risk"

    def test_no_measured_history_stops_at_stress(
        self, session, instrument, provider, monkeypatch
    ):
        """An unprojected account is not a cleared one."""
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument, history=None)

        assert trace.stopped_at == "stress"
        assert "not a cleared one" in trace.stage("stress").detail

    def test_an_oversized_r_stops_at_stress(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument, r_value_pct=0.05)

        assert trace.stopped_at == "stress"


class TestTheTraceIsTheDeliverable:
    def test_every_stage_reached_is_recorded_including_the_failure(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument, health=good_health(safe_mode=True))
        names = [s.name for s in trace.stages]

        assert names == ["cognition", "levels", "expected_value", "portfolio", "risk"]
        assert trace.stages[-1].passed is False

    def test_nothing_is_recorded_after_the_stop(
        self, session, instrument, provider, monkeypatch
    ):
        """The first block ends the walk — no gate downstream can reopen it."""
        seed(session, instrument, provider)
        stub_brain(monkeypatch, decision=Decision.WAIT)

        trace = run(session, instrument)

        assert [s.name for s in trace.stages] == ["cognition"]

    def test_the_policy_constants_are_published_not_hidden(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch, decision=Decision.WAIT)

        payload = run(session, instrument).as_dict()

        assert payload["policy"]["stop_atr_multiple"] == pipe.STOP_ATR_MULTIPLE
        assert payload["policy"]["target_reward_risk"] == pipe.TARGET_REWARD_RISK

    def test_the_trace_never_claims_execution_authority(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        assert run(session, instrument).as_dict()["authorises_execution"] is False


# ============================================================== the full walk
class TestReachingAnIntent:
    def test_a_clean_chain_produces_an_intent(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument)

        assert trace.stopped_at is None
        assert trace.reached_intent is True
        assert trace.intent.risk_r > 0

    def test_the_intent_carries_all_four_approvals(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        intent = run(session, instrument).intent
        sources = {a.source for a in intent.approvals}

        assert sources == set(sfy.REQUIRED_APPROVALS)
        assert all(a.approved for a in intent.approvals)

    def test_the_intent_clears_the_execution_checklist(
        self, session, instrument, provider, monkeypatch
    ):
        """The join that proves the two halves fit: the pipeline's output is
        exactly what the execution gate expects, approvals and freshness
        included. If this ever fails, one half changed shape without the other."""
        seed(session, instrument, provider)
        stub_brain(monkeypatch)
        intent = run(session, instrument).intent
        switch = sfy.KillSwitch()
        switch.disengage(by="test")

        result = sfy.preflight(
            intent,
            policy=sfy.ExecutionPolicy(enabled=True, dry_run=False, require_auth=True),
            kill_switch=switch,
            now=intent.authorised_at,
        )

        assert result.cleared is True, result.blocks

    def test_the_intent_is_still_refused_by_the_default_policy(
        self, session, instrument, provider, monkeypatch
    ):
        """Reaching an intent is not permission. Every deployment default refuses."""
        seed(session, instrument, provider)
        stub_brain(monkeypatch)
        intent = run(session, instrument).intent

        result = sfy.preflight(
            intent, policy=sfy.ExecutionPolicy(), kill_switch=sfy.KillSwitch(),
            now=intent.authorised_at,
        )

        assert result.cleared is False

    def test_a_sell_proposal_produces_a_sell_intent_with_mirrored_levels(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch, decision=Decision.SELL)

        intent = run(session, instrument).intent

        assert intent.side.value == "sell"
        assert intent.target < intent.entry < intent.stop

    def test_an_absent_rulebook_is_recorded_not_skipped(
        self, session, instrument, provider, monkeypatch
    ):
        """Rules that were not checked are not rules that were satisfied."""
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument)

        assert "not checked" in trace.stage("challenge").detail

    def test_the_permitted_size_never_exceeds_what_risk_allowed(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument)
        risk_stage = trace.stage("risk")

        assert trace.permitted_risk_r <= risk_stage.payload["permitted_risk_r"]

    def test_costs_can_close_the_gate_that_a_free_market_leaves_open(
        self, session, instrument, provider, monkeypatch
    ):
        """The EV stage is not decorative: real costs change the answer."""
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        expensive = run(
            session, instrument,
            costs=ev.CostModel(spread=0.004, commission=0.0, swap=0.0, slippage=0.0),
        )

        assert expensive.stopped_at == "expected_value"


# ===================================================================== carry
class TestTheInterestOnHoldingIt:
    """The rate differential reaching an actual decision.

    Every trace this system has produced carried "EV is optimistic by the
    unmeasured costs: spread, commission, swap, slippage", because `costs` was
    never supplied by any caller. Swap is the one of those four the platform
    can now measure without a broker: two central banks publish their rates,
    and the difference is what a position is charged or paid every night it
    stays open.

    The caller passes the difference rather than the pipeline fetching it -
    a chain that reads "now" cannot be replayed, which is the rule the whole
    signature is built around.
    """

    def test_a_supplied_differential_measures_the_swap(
        self, session, instrument, provider, monkeypatch
    ):
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument, rate_differential=-1.375)
        stage = trace.stage("expected_value")

        assert stage is not None
        assert stage.payload["costs"] is not None
        assert "swap" not in stage.payload["unmeasured_costs"]

    def test_without_one_the_swap_stays_unmeasured(
        self, session, instrument, provider, monkeypatch
    ):
        """Unknown rather than zero. Holding a position is not free."""
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        trace = run(session, instrument)
        stage = trace.stage("expected_value")

        assert stage is not None
        assert "swap" in stage.payload["unmeasured_costs"]

    def test_a_brokers_own_swap_is_not_replaced_by_the_estimate(
        self, session, instrument, provider, monkeypatch
    ):
        """What a broker charges is the differential plus their markup.

        Their number is what will actually appear on the statement, so an
        estimate must never overwrite it - it can only fill its absence.
        """
        seed(session, instrument, provider)
        stub_brain(monkeypatch)

        supplied = ev.CostModel(spread=0.0002, swap=0.0009)
        trace = run(
            session, instrument, costs=supplied, rate_differential=-1.375
        )
        stage = trace.stage("expected_value")

        assert stage is not None
        # 0.0002 spread plus the broker's own 0.0009 swap, kept as given.
        assert stage.payload["costs"] == pytest.approx(0.0011)

    def test_the_direction_decides_the_sign(
        self, session, instrument, provider, monkeypatch
    ):
        """The same pair, the same differential, opposite sides.

        One is paid to exist and the other is charged for it, so the cost of
        the long must come out below the cost of the short. A model that took
        the magnitude would report them identical.
        """
        seed(session, instrument, provider)

        stub_brain(monkeypatch, decision=Decision.BUY)
        long_side = run(session, instrument, rate_differential=4.0)

        stub_brain(monkeypatch, decision=Decision.SELL)
        short_side = run(session, instrument, rate_differential=4.0)

        long_cost = long_side.stage("expected_value").payload["costs"]
        short_cost = short_side.stage("expected_value").payload["costs"]
        assert long_cost < short_cost
