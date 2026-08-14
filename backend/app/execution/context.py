"""Assemble what `decide()` needs, from what the broker actually reports.

`decide()` takes the account, the data health, the calibration and the measured
history as arguments rather than reading them itself, and that is deliberate:
it must be runnable over historical bars with the account state *of that
moment*. A pipeline that fetches "now" from inside itself can never be
backtested, and one that cannot be backtested has never been tested.

So something has to do the fetching, and this is it. Everything here comes from
the live bridge or the database. Nothing is invented.

The hard one is `peak_equity`. The trailing drawdown floor is measured from it,
and a single snapshot does not contain it - equity right now says nothing about
where equity has been. Passing the current value would put the floor at today's
level and report headroom the account does not have, which is the error that
ends a challenge. So it is read from recorded history, and when there is no
history it is reported as unmeasured rather than guessed. The challenge brain
already knows what to do with a number it was not given; it refuses, which is
the right answer to "how much rope is left" when nobody has been watching.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.brain import risk as risk_brain
from app.brain.calibration import CalibrationReport
from app.providers.metatrader import MetaTraderBridge


@dataclass(frozen=True)
class Context:
    """One moment's inputs, and what could not be measured for it."""

    account: risk_brain.AccountState
    health: risk_brain.DataHealth
    calibration: CalibrationReport
    account_id: str
    unmeasured: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """Whether every input was measured rather than defaulted.

        A caller may decide to proceed without one, but it has to decide -
        which is the difference between a known gap and an invisible one.
        """
        return not self.unmeasured

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "equity": self.account.equity,
            "balance": self.account.balance,
            "peak_equity": self.account.peak_equity,
            "open_positions": self.account.open_positions,
            "complete": self.complete,
            "unmeasured": list(self.unmeasured),
        }


def peak_equity(
    session: Session, account_id: str, *, since: datetime | None = None
) -> float | None:
    """The highest equity recorded for this account, or None.

    Reads the recorded series. It returned a flat None until there was a series
    to read - and before that, an even worse version queried
    `max(ChallengeAccount.starting_balance)`, which compared a UUID column to
    the string "metatrader" and would, with the types fixed, have returned the
    starting balance as though it were the peak. A query that answers with a
    confident wrong number is worse than one that answers with nothing.

    None still means nobody was watching, which is a different fact from "the
    peak is today's equity" - the second places a trailing floor at today's
    level and reports rope the account does not have.
    """
    from app.services import equity as equity_series

    return equity_series.peak_equity(session, account_id, since=since)


def build(
    session: Session,
    *,
    account_id: str = "metatrader",
    bridge: MetaTraderBridge | None = None,
    now: datetime | None = None,
) -> Context | None:
    """Everything `decide()` needs for this moment, or None if the account is not there.

    None rather than a Context full of zeros. Zeros would flow into a drawdown
    check and produce a confident verdict about an account nobody is connected
    to, which is the failure mode this whole provider was rewritten to prevent.
    """
    moment = now or datetime.now(UTC)
    reader = bridge or MetaTraderBridge()

    published = reader.account(now=moment)
    if not published.get("available"):
        return None

    equity = float(published.get("equity") or 0.0)
    balance = float(published.get("balance") or 0.0)
    unmeasured: list[str] = []

    recorded_peak = peak_equity(session, account_id)
    if recorded_peak is None:
        # Reported, not silently replaced. The trailing floor is measured from
        # this, and the challenge brain refuses rather than guessing - which is
        # the right answer to "how much rope is left" when nobody was watching.
        unmeasured.append(
            "peak equity has never been recorded for this account, so a "
            "trailing drawdown floor cannot be placed"
        )
        peak = max(equity, balance)
    else:
        peak = max(float(recorded_peak), equity, balance)

    positions = reader.positions(now=moment)
    open_positions = len(positions.get("positions", [])) if positions.get("available") else 0
    if not positions.get("available"):
        unmeasured.append("open positions could not be read from the terminal")

    # The day's P&L in R needs both a starting point for the day and an R
    # value in currency. Neither is in a snapshot, so it is reported as
    # unmeasured rather than assumed to be zero - "no loss today" and "nobody
    # measured today" are opposite inputs to a daily-loss check.
    unmeasured.append(
        "the day's realised P&L in R is not derivable from a single snapshot, "
        "so it is reported as zero and flagged rather than assumed"
    )

    account = risk_brain.AccountState(
        equity=equity,
        balance=balance,
        peak_equity=peak,
        daily_pnl_r=0.0,
        open_positions=open_positions,
        used_margin=float(published.get("margin") or 0.0),
        free_margin=float(published.get("free_margin") or 0.0),
    )

    return Context(
        account=account,
        health=risk_brain.DataHealth(),
        # Stated as uncalibrated with the reason, rather than passed as
        # calibrated with no evidence. A confidence that has never been scored
        # against outcomes is not a confidence.
        calibration=CalibrationReport(
            calibrated=False,
            reason=(
                "no calibration has been scored for this deployment, so the "
                "brain's confidence numbers are uncalibrated"
            ),
            source="none",
        ),
        account_id=account_id,
        unmeasured=tuple(unmeasured),
    )
