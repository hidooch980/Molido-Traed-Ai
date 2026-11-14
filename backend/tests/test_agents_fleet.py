"""Stage 20: the remaining roles run in the shadow cycle; missing data is safe."""

from __future__ import annotations

import pytest

from app.agents import registry
from app.agents.analyzers.fleet import ANALYZERS as FLEET
from app.agents.analyzers.runner import ANALYZERS, run_timed
from app.agents.messages import Recommendation as Rec
from app.agents.model import ImplementationStatus
from app.core.enums import Timeframe
from app.services import agent_run
from tests.test_agents_analyzers import ctx_for, walk

FLEET_IDS = tuple(FLEET)


class TestFleetRuns:
    def test_every_role_is_implemented_and_wired(self):
        assert registry.status_counts()[ImplementationStatus.IMPLEMENTED] == 51
        missing = [r.id for r in registry.all_roles()
                   if r.id not in ANALYZERS and r.id != "BRAIN-01"]
        assert missing == []

    def test_run_timed_returns_health_for_all_51(self):
        messages, health = run_timed(ctx_for(walk(80)))
        assert set(health) == set(ANALYZERS) | {"BRAIN-01"}
        assert len(messages) == 51
        assert all(h["ok"] for h in health.values())
        assert {m.agent_id for m in messages} == set(health)

    def test_missing_inputs_are_wait_or_abstain_not_buy(self):
        messages, _ = run_timed(ctx_for(walk(80)))
        by = {m.agent_id: m for m in messages}
        for agent_id in ("EX01", "EX02", "EX04", "EX05", "RK01", "RK04"):
            assert by[agent_id].recommendation in (Rec.WAIT, Rec.ABSTAIN)
        # EX01 / EX05 must never look like a send.
        assert "will not send" in by["EX01"].analysis or "not send" in by["EX01"].analysis

    def test_rk01_blocks_on_kill_switch_and_daily_loss(self):
        ctx = ctx_for(walk(80), extras={"risk_context": {"kill_switch": True}})
        assert FLEET["RK01"](ctx).recommendation is Rec.BLOCK
        ctx = ctx_for(walk(80), extras={"risk_context": {"daily_pnl_pct": -4.5, "equity": 10_000}})
        assert FLEET["RK01"](ctx).recommendation is Rec.BLOCK

    def test_nobody_overrides_a_risk_brain_block(self):
        ctx = ctx_for(walk(80), extras={"risk_verdict": "BLOCK", "slippage_fills": [],
                                        "open_symbols": [], "challenge": {"status": "ok"}})
        for agent_id in ("RK01", "RK04", "RK05", "EX02", "EX05"):
            assert FLEET[agent_id](ctx).recommendation is Rec.BLOCK, agent_id

    @pytest.mark.parametrize("agent", FLEET_IDS)
    def test_no_lookahead(self, agent):
        bars = walk(300)
        cut = bars[200].open_time
        a = ANALYZERS[agent](ctx_for(bars[:200], as_of=cut))
        b = ANALYZERS[agent](ctx_for(bars, as_of=cut))
        assert (a.recommendation, a.analysis, a.evidence) == (
            b.recommendation, b.analysis, b.evidence)

    def test_run_symbol_health_covers_all_51(self, session, instrument, provider):
        from datetime import UTC, datetime, timedelta

        from tests.conftest import insert_bar

        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        price = 1.10
        for i in range(80, 0, -1):
            t = now - timedelta(hours=i)
            insert_bar(session, instrument.id, provider.id, event_time=t,
                       ingested_at=t + timedelta(hours=1), close=price, open_=price)
        out = agent_run.run_symbol(session, "EURUSD", Timeframe.H1, as_of=now, record=True)
        assert out["status"] == "ran"
        assert set(out["health"]) == set(ANALYZERS) | {"BRAIN-01"}
        assert all(h["ok"] for h in out["health"].values())
