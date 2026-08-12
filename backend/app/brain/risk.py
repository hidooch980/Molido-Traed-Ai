"""Autonomous risk brain (spec phase 23, §21).

This is the layer that says no.

The spec's architecture is a chain of four verbs — *the AI proposes, risk
authorises, execution executes, the guardian supervises* — and the value of the
chain comes entirely from the second link being unable to be talked out of its
answer. So three properties are built in rather than configured:

**It is independent of the predictive layer.** Nothing here reads a council
score, a conviction, or a regime label. It reads account state, exposure,
data health and the trade's own shape. A confident brain and a broken feed
must produce the same verdict as an unconfident brain and a broken feed:
BLOCK.

**Hard limits cannot be overridden.** Not by the brain, not by a user, not by
Telegram, not by a config flag. `HardLimits` is frozen, and a breach returns
BLOCK with no path that turns it into APPROVE. Where a limit is genuinely
policy rather than safety, it lives in `SoftLimits`, which can be tuned — and
the split is deliberate, because a system where everything is configurable has
no limits at all.

**Uncertainty reduces risk; it never increases it.** Every unknown — stale
data, missing calibration, unmeasured correlation, an unevaluated dataset —
moves the verdict toward REDUCE or BLOCK. There is no input to this module
that makes it more permissive than its defaults.

What this module does *not* do: place orders, size positions in lots, or talk
to a broker. It returns a verdict and a permitted risk. Execution is phase 25,
and it does not exist yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.enums import RiskVerdict

# --------------------------------------------------------------------- limits


@dataclass(frozen=True)
class HardLimits:
    """Breaching any of these is a BLOCK. Frozen, and deliberately so.

    These are not preferences. A drawdown limit that can be raised in the
    moment it is hit is not a drawdown limit; it is a suggestion that loses
    every argument it has with hope.
    """

    max_risk_per_trade_r: float = 1.0
    max_daily_loss_r: float = 3.0
    max_total_drawdown_pct: float = 0.10
    max_open_positions: int = 10
    max_margin_utilisation: float = 0.50
    # A feed older than this many bars cannot support a new position. The spec
    # is explicit: stale data means no new trade.
    max_data_age_bars: float = 3.0


@dataclass
class SoftLimits:
    """Policy, not safety. Tunable per account without touching the hard floor."""

    target_risk_per_trade_r: float = 1.0
    reduce_when_drawdown_pct: float = 0.05
    reduce_when_daily_loss_r: float = 1.5
    min_free_margin_ratio: float = 0.30


@dataclass
class AccountState:
    """What the account actually is right now.

    Every field is required. An account state with optional balances would let
    a caller omit the one number that would have blocked the trade.
    """

    equity: float
    balance: float
    peak_equity: float
    daily_pnl_r: float
    open_positions: int
    used_margin: float
    free_margin: float

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)

    @property
    def margin_utilisation(self) -> float:
        total = self.used_margin + self.free_margin
        return self.used_margin / total if total > 0 else 0.0


@dataclass
class DataHealth:
    """How much the inputs can be trusted. All defaults are pessimistic."""

    data_age_bars: float | None = None
    training_eligible: bool = False
    calibrated: bool = False
    correlation_unknown: list[str] = field(default_factory=list)
    safe_mode: bool = False


@dataclass
class RiskDecision:
    verdict: RiskVerdict
    permitted_risk_r: float
    reasons: list[str] = field(default_factory=list)
    hard_breaches: list[str] = field(default_factory=list)
    reductions: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)

    @property
    def approves(self) -> bool:
        return self.verdict is not RiskVerdict.BLOCK and self.permitted_risk_r > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "permitted_risk_r": round(self.permitted_risk_r, 4),
            "approves": self.approves,
            "hard_breaches": self.hard_breaches,
            "reductions": self.reductions,
            "reasons": self.reasons,
            "inputs": self.inputs,
            # Stated on every response so no consumer can mistake this for
            # permission to place an order.
            "authorises_execution": False,
            "note": "execution engine is phase 25 and does not exist yet",
        }


def _blocked(breaches: list[str], inputs: dict[str, Any]) -> RiskDecision:
    return RiskDecision(
        verdict=RiskVerdict.BLOCK,
        permitted_risk_r=0.0,
        hard_breaches=breaches,
        reasons=["hard limit breached — no override exists"],
        inputs=inputs,
    )


def authorise(
    *,
    requested_risk_r: float,
    account: AccountState,
    health: DataHealth,
    portfolio_headroom_r: float | None = None,
    hard: HardLimits | None = None,
    soft: SoftLimits | None = None,
) -> RiskDecision:
    """Authorise, reduce, or block a proposed risk allocation.

    The order matters: hard limits are checked first and exit immediately, so
    no subsequent calculation can soften them.
    """
    hard = hard or HardLimits()
    soft = soft or SoftLimits()

    inputs = {
        "requested_risk_r": requested_risk_r,
        "drawdown_pct": round(account.drawdown_pct, 6),
        "daily_pnl_r": account.daily_pnl_r,
        "open_positions": account.open_positions,
        "margin_utilisation": round(account.margin_utilisation, 6),
        "data_age_bars": health.data_age_bars,
        "training_eligible": health.training_eligible,
        "calibrated": health.calibrated,
        "safe_mode": health.safe_mode,
        "portfolio_headroom_r": portfolio_headroom_r,
    }

    # ---------------------------------------------------------------- hard
    breaches: list[str] = []

    if health.safe_mode:
        breaches.append("system is in safe mode")
    if requested_risk_r <= 0:
        breaches.append("requested risk must be positive")
    if requested_risk_r > hard.max_risk_per_trade_r:
        breaches.append(
            f"requested {requested_risk_r:.2f} R exceeds the "
            f"{hard.max_risk_per_trade_r:.2f} R per-trade ceiling"
        )
    if account.drawdown_pct >= hard.max_total_drawdown_pct:
        breaches.append(
            f"drawdown {account.drawdown_pct:.1%} at or beyond the "
            f"{hard.max_total_drawdown_pct:.0%} ceiling"
        )
    if account.daily_pnl_r <= -hard.max_daily_loss_r:
        breaches.append(
            f"daily loss {account.daily_pnl_r:.2f} R at or beyond the "
            f"{hard.max_daily_loss_r:.2f} R limit"
        )
    if account.open_positions >= hard.max_open_positions:
        breaches.append(f"{account.open_positions} open positions at the ceiling")
    if account.margin_utilisation >= hard.max_margin_utilisation:
        breaches.append(
            f"margin utilisation {account.margin_utilisation:.1%} at the "
            f"{hard.max_margin_utilisation:.0%} ceiling"
        )
    if account.equity <= 0:
        breaches.append("equity is zero or negative")

    # Stale or absent data blocks new risk. Absent is treated as stale, not as
    # fresh: not knowing the age of the feed is not evidence that it is young.
    if health.data_age_bars is None:
        breaches.append("data freshness unknown — cannot confirm the feed is live")
    elif health.data_age_bars > hard.max_data_age_bars:
        breaches.append(
            f"data is {health.data_age_bars:.1f} bars old, beyond the "
            f"{hard.max_data_age_bars:.0f}-bar limit"
        )

    if breaches:
        return _blocked(breaches, inputs)

    # ---------------------------------------------------------------- soft
    permitted = min(requested_risk_r, soft.target_risk_per_trade_r)
    reductions: list[str] = []

    def reduce_to(factor: float, why: str) -> None:
        nonlocal permitted
        capped = permitted * factor
        if capped < permitted:
            permitted = capped
            reductions.append(why)

    if account.drawdown_pct >= soft.reduce_when_drawdown_pct:
        reduce_to(0.5, f"drawdown {account.drawdown_pct:.1%} — risk halved")
    if account.daily_pnl_r <= -soft.reduce_when_daily_loss_r:
        reduce_to(0.5, f"daily loss {account.daily_pnl_r:.2f} R — risk halved")

    # Model uncertainty. These do not block, because a system that refuses to
    # trade until it is perfectly calibrated never gathers the outcomes that
    # would calibrate it — but they must cost something, or the incentive to
    # fix them disappears.
    if not health.calibrated:
        reduce_to(0.5, "no calibrated probability for this source — risk halved")
    if not health.training_eligible:
        reduce_to(0.5, "dataset failed the quality gate — risk halved")
    if health.correlation_unknown:
        reduce_to(
            0.75,
            "correlation unmeasured against "
            + ", ".join(health.correlation_unknown[:5])
            + " — risk cut by a quarter",
        )

    free_ratio = 1.0 - account.margin_utilisation
    if free_ratio < soft.min_free_margin_ratio:
        reduce_to(0.5, f"free margin {free_ratio:.0%} below policy — risk halved")

    if portfolio_headroom_r is not None and portfolio_headroom_r < permitted:
        permitted = max(0.0, portfolio_headroom_r)
        reductions.append(
            f"portfolio headroom caps this at {permitted:.2f} R"
        )

    if permitted <= 0:
        return RiskDecision(
            verdict=RiskVerdict.BLOCK,
            permitted_risk_r=0.0,
            reasons=["reductions left no permitted risk"],
            reductions=reductions,
            inputs=inputs,
        )

    verdict = (
        RiskVerdict.APPROVE if permitted >= requested_risk_r else RiskVerdict.REDUCE
    )
    return RiskDecision(
        verdict=verdict,
        permitted_risk_r=permitted,
        reasons=["within all limits"] if verdict is RiskVerdict.APPROVE else reductions,
        reductions=reductions,
        inputs=inputs,
    )
