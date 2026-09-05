"""How far this system is from being allowed to size a full trade.

The risk brain halves the permitted risk twice over - once for
`calibrated: false` and once for `training_eligible: false` - so every order
this deployment sends is a quarter of the size it was asked for. Both flags
default to pessimistic and the cycle never sets them, which was read for a
long time as caution. It was not caution. It was unreachable: calibration
needs a confidence paired with an outcome, and until `app.workers.forward`
began recording `before["strength"]`, no decision in this record carried a
number to be judged on. The penalty could never be worked off, because the
evidence that would lift it was the one thing nothing was writing down.

This reports the distance to it, and nothing else. **It does not change how
anything is sized.** Turning the flag on is a decision to quadruple live risk
and it belongs to whoever owns the money, not to a report - and on today's
evidence, where no brain beats its own control at the threshold eight
simultaneous hypotheses demand, the honest answer to "should risk go up" is
still no.

What it can say is what "not yet" costs and how far away "yet" is.
"""

from __future__ import annotations

from typing import Any

from app.brain import calibration

#: Entries recorded before the strength was kept. They are counted and excluded,
#: never defaulted: a decision with no confidence attached is not a decision
#: made at 0.5, and feeding a made-up middle into a reliability curve would
#: manufacture the evidence this report exists to wait for.
UNSCORED = "recorded before the signal strength was kept"


def assess(session: Any, *, days: int = 365) -> dict[str, Any]:
    """Per brain: how many scored outcomes exist, and what they say so far."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.models.journal import ARM_RULE, JournalEntry

    since = datetime.now(UTC) - timedelta(days=days)
    rows = session.execute(
        select(
            JournalEntry.strategy,
            JournalEntry.outcome,
            JournalEntry.before,
        ).where(
            JournalEntry.arm == ARM_RULE,
            JournalEntry.outcome.isnot(None),
            JournalEntry.opened_at >= since,
        )
    ).all()

    forecasts: dict[str, list[calibration.Forecast]] = {}
    unscored: dict[str, int] = {}
    for strategy, outcome, before in rows:
        name = str(strategy or "unknown")
        payload = before if isinstance(before, dict) else {}
        score = payload.get("strength")
        if score is None:
            unscored[name] = unscored.get(name, 0) + 1
            continue
        try:
            value = float(score)
        except (TypeError, ValueError):
            unscored[name] = unscored.get(name, 0) + 1
            continue
        forecasts.setdefault(name, []).append(
            calibration.Forecast(
                # Clamped rather than dropped. A score outside 0..1 is a bug
                # in whatever produced it and worth surviving to be seen in
                # the bucket counts, not a reason to lose the outcome.
                score=min(max(value, 0.0), 1.0),
                outcome=outcome == "win",
                source=name,
            )
        )

    per: list[dict[str, Any]] = []
    for name in sorted(set(forecasts) | set(unscored)):
        scored = forecasts.get(name, [])
        report = calibration.evaluate(scored, source=name) if scored else None
        per.append(
            {
                "strategy": name,
                "scored": len(scored),
                "unscored": unscored.get(name, 0),
                "needs": max(calibration.MIN_FORECASTS - len(scored), 0),
                "calibrated": bool(report and report.calibrated),
                "report": report.as_dict() if report else None,
                "why_not": None
                if report is None
                else (None if report.calibrated else report.reason),
            }
        )

    best = max((p["scored"] for p in per), default=0)
    return {
        "days": days,
        "min_forecasts": calibration.MIN_FORECASTS,
        "per_strategy": per,
        "any_calibrated": any(p["calibrated"] for p in per),
        "closest_gap": max(calibration.MIN_FORECASTS - best, 0),
        "unscored_note": UNSCORED,
        "note": (
            "Nothing here changes how a trade is sized. The risk brain halves "
            "for `calibrated: false` and halves again for `training_eligible: "
            "false`, so orders go out at a quarter size; lifting either is a "
            "decision to quadruple live risk, and no brain has yet beaten its "
            "own control at the threshold eight simultaneous hypotheses "
            "demand."
        ),
    }


__all__ = ["UNSCORED", "assess"]
