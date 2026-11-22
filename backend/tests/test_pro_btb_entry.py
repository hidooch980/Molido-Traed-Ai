"""Independent tests for stage 6: BTB entry (bull and bear; WAIT unless specified)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from app.agents.pro_btb.engine import ProBtbEngine, select_breakout_leg
from app.agents.pro_btb.rules import RULE_BY_ID
from app.agents.pro_btb.stages.bo_candle import validate_bo_candle
from app.agents.pro_btb.stages.confirmation import confirm_setup
from app.agents.pro_btb.stages.entry import propose_entry
from app.agents.pro_btb.stages.retest import assess_retest
from app.agents.pro_btb.status import RuleStatus
from app.agents.pro_btb.types import Direction
from tests.pro_btb_bars import bear_bars, bull_bars, chop_bars


def _confirmed(bars):
    leg = select_breakout_leg(bars)
    bo = validate_bo_candle(bars, leg)
    retest = assess_retest(bars, bo)
    return leg, confirm_setup(leg, bo, retest)


class TestEntry:
    def test_rejected_confirmation_stays_wait(self):
        entry = propose_entry(_confirmed(chop_bars())[1], Direction.NONE)
        assert entry.action == "WAIT"
        assert entry.entry is None and entry.stop_loss is None and entry.take_profit is None
        assert entry.risk_reward is None and entry.invalidation is None

    def test_bull_fixture_waits_because_placement_rules_are_research(self):
        leg, conf = _confirmed(bull_bars())
        assert conf.accepted
        entry = propose_entry(conf, leg.direction)
        assert leg.direction is Direction.BULL
        assert entry.action == "WAIT"
        assert "not SPECIFIED" in entry.reason
        assert entry.entry is entry.stop_loss is entry.take_profit is None
        assert entry.risk_reward is None and entry.invalidation is None

    def test_bear_fixture_also_waits(self):
        leg, conf = _confirmed(bear_bars())
        assert conf.accepted and leg.direction is Direction.BEAR
        entry = propose_entry(conf, leg.direction)
        assert entry.action == "WAIT"
        assert entry.risk_reward is None

    def test_engine_trace_is_wait_with_logged_reason(self):
        as_of = datetime(2026, 11, 4, tzinfo=UTC)
        for bars, direction in ((bull_bars(), Direction.BULL), (bear_bars(), Direction.BEAR)):
            trace = ProBtbEngine().run(bars, as_of=as_of, symbol="XAUUSD", timeframe="H1")
            assert trace.direction is direction
            assert trace.confirmation_accepted
            assert trace.entry_action == "WAIT"
            assert trace.risk_reward is None
            assert trace.as_dict()["entry_action"] == "WAIT"

    def test_specified_catalog_may_emit_prices_and_rr(self):
        _, conf = _confirmed(bull_bars())
        promoted = dict(RULE_BY_ID)
        for rid in ("DEF_ENTRY_PRICE", "DEF_STOP_LOSS", "DEF_TAKE_PROFIT"):
            promoted[rid] = replace(promoted[rid], status=RuleStatus.SPECIFIED)
        entry = propose_entry(
            conf, Direction.BULL, catalog=promoted,
            entry=2030.0, stop_loss=2020.0, take_profit=2050.0, invalidation=2019.0,
        )
        assert entry.action == "BUY"
        assert entry.entry == 2030.0 and entry.stop_loss == 2020.0 and entry.take_profit == 2050.0
        assert entry.risk_reward == 2.0
        assert entry.invalidation == 2019.0

        # The official catalog is unchanged: the same call without a promoted
        # catalog must still WAIT and must not emit those prices.
        blocked = propose_entry(
            conf, Direction.BULL,
            entry=2030.0, stop_loss=2020.0, take_profit=2050.0, invalidation=2019.0,
        )
        assert blocked.action == "WAIT"
        assert blocked.entry is None
