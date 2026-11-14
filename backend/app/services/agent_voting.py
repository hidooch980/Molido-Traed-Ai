"""Wire weighted votes, scorecards and the monthly underperformer report.

Reads stored agent runs (shadow only). Never sends an order, never deletes a
role, never overrides the Risk Brain.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.agents import memory, voting
from app.agents.analyzers.bars import Candle
from app.agents.selfheal import Sample
from app.services import agent_health

REPORT_EVENT = "monthly_underperformers"
VOTE_KIND = "agent"


def _samples(session: Session, *, now: datetime | None = None,
             horizon_bars: int = 4) -> list[Sample]:
    samples, _pending = agent_health.resolved_samples(
        session, horizon_bars=horizon_bars, limit=500, now=now)
    return samples


def current_weights(session: Session, *, now: datetime | None = None,
                    samples: list[Sample] | None = None) -> dict[str, float]:
    return voting.rolling_weights(samples if samples is not None else _samples(session, now=now),
                                  now=now or datetime.now(UTC))


def scorecard(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    samples = _samples(session, now=now)
    weights = voting.rolling_weights(samples, now=now)
    return {
        "as_of": now.isoformat(),
        "horizon_bars": 4,
        "min_samples": voting.MIN_SAMPLES,
        "weight_bounds": [voting.W_MIN, voting.W_MAX],
        "half_life_days": voting.HALF_LIFE_DAYS,
        "agents": voting.scorecard(samples, weights, now=now),
        "note": "Shadow scorecard. Accuracy and hypothetical P&L are close-to-close "
                "before spread and costs; under "
                f"{voting.MIN_SAMPLES} calls is not evidence. Advisory only.",
    }


def underperformer_report(session: Session, *, now: datetime | None = None,
                          record: bool = False) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    samples = _samples(session, now=now)
    flagged = voting.underperformers(samples, now=now)
    report = {
        "as_of": now.isoformat(),
        "window_days": 30,
        "flagged": flagged,
        "proposals_only": True,
        "auto_delete": False,
        "note": "Proposals to disable or retrain. Nothing is removed or switched off "
                "automatically.",
    }
    if record:
        memory.remember(
            session, "BRAIN-01", "model_performance",
            f"monthly underperformer report: {len(flagged)} flagged",
            content={"event": REPORT_EVENT, **report},
        )
    return report


def latest_report(session: Session) -> dict[str, Any] | None:
    for row in memory.recall(session, agent_id="BRAIN-01", kind="model_performance", limit=50):
        content = row.content or {}
        if content.get("event") == REPORT_EVENT:
            return content
    return None


def maybe_monthly_report(session: Session, *, now: datetime | None = None) -> dict[str, Any] | None:
    now = now or datetime.now(UTC)
    last = latest_report(session)
    if last and last.get("as_of"):
        try:
            prev = datetime.fromisoformat(str(last["as_of"]))
            if prev.tzinfo is None:
                prev = prev.replace(tzinfo=UTC)
            if now - prev < timedelta(days=30):
                return None
        except ValueError:
            pass
    return underperformer_report(session, now=now, record=True)


def calls_from_health(health: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {a: str(h.get("recommendation") or "WAIT") for a, h in health.items()}


def vote_for_run(health: dict[str, dict[str, Any]], weights: dict[str, float],
                 bars: list[Candle] | tuple[Candle, ...] | None = None,
                 regime: dict[str, Any] | None = None) -> dict[str, Any]:
    detected = regime or (voting.detect_regime(bars or ()) if bars is not None
                          else {"regime": "unknown", "reason": "no bars"})
    result = voting.vote(calls_from_health(health), weights,
                         regime=str(detected.get("regime") or "unknown"))
    out = result.as_dict()
    out["regime_detail"] = detected
    return out


def votes_from_latest_runs(session: Session, *, now: datetime | None = None,
                           limit: int = 200) -> dict[str, dict[str, Any]]:
    """Latest recorded weighted vote per symbol, for the bridge config."""
    now = now or datetime.now(UTC)
    weights = current_weights(session, now=now)
    latest: dict[str, dict[str, Any]] = {}
    rows = [r for r in memory.recall(session, kind="agent", limit=min(500, limit))
            if (r.content or {}).get("event") == "run"]
    # recall is newest first
    for row in rows:
        symbol = (row.symbol or "").upper()
        if not symbol or symbol in latest:
            continue
        content = row.content or {}
        if content.get("vote"):
            latest[symbol] = {"symbol": symbol, "as_of": content.get("as_of"),
                              **content["vote"]}
            continue
        health = content.get("agents") or {}
        if not health:
            continue
        latest[symbol] = {"symbol": symbol, "as_of": content.get("as_of"),
                          **vote_for_run(health, weights)}
    return latest
