"""Risk, portfolio, challenge and stress over HTTP (spec §21-24, §30).

Four brains that have been built, tested and unreachable. Each answers a
different question about the same proposed trade, and each is a veto rather
than a vote, so exposing them separately is not a convenience — it is the only
way to see *which one* refused.

Every route here is a GET behind READ, and every one of them is a pure
function of what the caller supplies. That matters more than it sounds: these
endpoints take the account state as query parameters rather than reading one,
because there is no live account wired to this deployment. An endpoint that
invented an account would answer a different question in a convincing voice,
and the answer would look exactly like a real one.

Nothing here authorises anything. `authorises_execution` is stamped on every
response for the same reason it is stamped on the brains themselves: a caller
must not be able to mistake a risk verdict for permission.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import Principal, require
from app.brain import challenge as challenge_brain
from app.brain import portfolio as portfolio_brain
from app.brain import risk as risk_brain
from app.brain import rulebooks as rulebook_module
from app.brain import stress as stress_brain
from app.core.enums import Permission

router = APIRouter(prefix="/risk", tags=["risk"])

READ = Depends(require(Permission.READ))


def _account(
    equity: float, peak_equity: float | None, daily_pnl_r: float, open_positions: int
) -> risk_brain.AccountState:
    peak = peak_equity if peak_equity is not None else equity
    return risk_brain.AccountState(
        equity=equity,
        balance=equity,
        peak_equity=max(peak, equity),
        daily_pnl_r=daily_pnl_r,
        open_positions=open_positions,
        used_margin=0.0,
        free_margin=equity,
    )


@router.get("/limits")
def read_limits(_: Principal = READ) -> dict[str, Any]:
    """The hard and soft limits this deployment enforces.

    Hard limits are published because a limit nobody can see is a limit nobody
    can plan against. They are frozen in code, so this endpoint reports them
    and offers no way to change them.
    """
    hard = risk_brain.HardLimits()
    soft = risk_brain.SoftLimits()
    return {
        "hard": {
            "max_risk_per_trade_r": hard.max_risk_per_trade_r,
            "max_daily_loss_r": hard.max_daily_loss_r,
            "max_total_drawdown_pct": hard.max_total_drawdown_pct,
            "max_open_positions": hard.max_open_positions,
            "max_margin_utilisation": hard.max_margin_utilisation,
            "max_data_age_bars": hard.max_data_age_bars,
        },
        "soft": {
            "target_risk_per_trade_r": soft.target_risk_per_trade_r,
            "reduce_when_drawdown_pct": soft.reduce_when_drawdown_pct,
            "reduce_when_daily_loss_r": soft.reduce_when_daily_loss_r,
            "min_free_margin_ratio": soft.min_free_margin_ratio,
        },
        "portfolio": {
            "correlation_cluster": portfolio_brain.CORRELATION_CLUSTER,
            "max_total_risk_r": portfolio_brain.MAX_TOTAL_RISK_R,
            "max_currency_risk_r": portfolio_brain.MAX_CURRENCY_RISK_R,
            "max_cluster_risk_r": portfolio_brain.MAX_CLUSTER_RISK_R,
            "max_instrument_risk_r": portfolio_brain.MAX_INSTRUMENT_RISK_R,
        },
        "hard_limits_are_frozen": True,
        "note": "hard limits cannot be raised by any request; this endpoint reports them",
    }


@router.get("/authorise")
def read_authorisation(
    requested_risk_r: float = Query(default=1.0, gt=0),
    equity: float = Query(default=100_000.0, gt=0),
    peak_equity: float | None = Query(default=None, gt=0),
    daily_pnl_r: float = Query(default=0.0),
    open_positions: int = Query(default=0, ge=0),
    data_age_bars: float | None = Query(
        default=None, description="Feed age in bars. Omitted means unknown, which blocks."
    ),
    calibrated: bool = Query(default=False),
    training_eligible: bool = Query(default=False),
    safe_mode: bool = Query(default=False),
    _: Principal = READ,
) -> dict[str, Any]:
    """What the risk brain would permit for an account shaped like this.

    `data_age_bars` defaults to omitted, and omitted blocks. Not knowing how
    old the feed is is not evidence that it is fresh, and defaulting it to zero
    here would make the endpoint answer more permissively than the brain does.
    """
    decision = risk_brain.authorise(
        requested_risk_r=requested_risk_r,
        account=_account(equity, peak_equity, daily_pnl_r, open_positions),
        health=risk_brain.DataHealth(
            data_age_bars=data_age_bars,
            training_eligible=training_eligible,
            calibrated=calibrated,
            safe_mode=safe_mode,
        ),
    )
    return decision.as_dict()


@router.get("/portfolio")
def read_portfolio(
    symbol: str = Query(min_length=1),
    direction: str = Query(default="buy", pattern="^(buy|sell)$"),
    proposed_risk_r: float = Query(default=1.0, gt=0),
    open_symbols: str = Query(
        default="",
        description="Comma-separated open positions as SYMBOL:side:risk_r, e.g. "
        "GBPUSD:buy:1.0,AUDUSD:sell:0.5",
    ),
    base_currency: str | None = Query(default=None),
    quote_currency: str | None = Query(default=None),
    _: Principal = READ,
) -> dict[str, Any]:
    """What the open book can still absorb of this trade.

    Correlations are not accepted as a parameter. They are measured by phase 8
    from real bars, and letting a caller assert them would hand the one input
    that makes a book look diversified to whoever wants that answer.
    """
    positions: list[portfolio_brain.Position] = []
    for entry in (p.strip() for p in open_symbols.split(",") if p.strip()):
        parts = entry.split(":")
        if len(parts) != 3:
            continue
        name, side, risk = parts
        try:
            positions.append(
                portfolio_brain.Position(
                    symbol=name.upper(),
                    direction="sell" if side.lower().startswith("s") else "buy",
                    risk_r=float(risk),
                    base_currency=name[:3].upper() if len(name) >= 6 else None,
                    quote_currency=name[3:6].upper() if len(name) >= 6 else None,
                )
            )
        except ValueError:
            continue

    verdict = portfolio_brain.evaluate(
        symbol=symbol.upper(),
        direction=direction,
        proposed_risk_r=proposed_risk_r,
        positions=positions,
        base_currency=base_currency,
        quote_currency=quote_currency,
    )
    payload = verdict.as_dict()
    payload["positions_parsed"] = len(positions)
    return payload


@router.get("/stress")
def read_stress(
    trades: int = Query(default=0, ge=0),
    wins: int = Query(default=0, ge=0),
    average_win_r: float | None = Query(default=None, gt=0),
    average_loss_r: float | None = Query(default=None, gt=0),
    calibrated: bool = Query(default=False),
    r_value_pct: float = Query(default=0.002, gt=0, le=1.0),
    current_drawdown_pct: float = Query(default=0.0, ge=0, lt=1.0),
    _: Principal = READ,
) -> dict[str, Any]:
    """Four scenarios projected onto an account with this trade history.

    A history that cannot be constructed returns the refusal rather than a
    projection. Survival computed from an imagined win rate is the single most
    dangerous number this system could publish.
    """
    try:
        history = stress_brain.TradeHistory(
            trades=trades,
            wins=wins,
            average_win_r=average_win_r,
            average_loss_r=average_loss_r,
            calibrated=calibrated,
        )
    except Exception as exc:  # noqa: BLE001 - reported as the answer, not swallowed
        return {
            "available": False,
            "reason": str(exc),
            "note": "survival projected from an impossible history would be invented",
        }

    report = stress_brain.run_all(
        history=history,
        r_value_pct=r_value_pct,
        open_risk_r=[],
        current_drawdown_pct=current_drawdown_pct,
    )
    return report.as_dict()


@router.get("/rulebooks")
def read_rulebooks(_: Principal = READ) -> dict[str, Any]:
    """The transcribed provider rulebooks, with the provenance of each number.

    Published rather than kept internal because the numbers are the part most
    worth disagreeing with. Every entry carries the page it was read from, the
    date it was read, and `confirmed_by_holder: false` - a marketing page and
    one account's contract are not guaranteed to be the same document, and
    only the person who signed up can close that gap.
    """
    return {
        "rulebooks": [book.as_dict() for book in rulebook_module.RULEBOOKS],
        "providers": rulebook_module.providers(),
        "none_are_confirmed": True,
        "note": (
            "these are transcriptions of a published page, not a contract. "
            "Check them against your own account terms before trading against "
            "them, and re-check them: providers change their rules and a "
            "rulebook with an old date is a different firm's rulebook"
        ),
    }


@router.get("/challenge")
def read_challenge(
    starting_balance: float = Query(default=100_000.0, gt=0),
    current_equity: float = Query(default=100_000.0, gt=0),
    peak_equity: float | None = Query(default=None, gt=0),
    daily_starting_equity: float | None = Query(default=None, gt=0),
    days_traded: int = Query(default=0, ge=0),
    open_positions: int = Query(default=0, ge=0),
    profit_target_pct: float | None = Query(default=0.10, gt=0),
    max_daily_drawdown_pct: float | None = Query(default=0.05, gt=0),
    max_total_drawdown_pct: float | None = Query(default=0.10, gt=0),
    proposed_risk_r: float | None = Query(default=None, gt=0),
    currency_per_r: float | None = Query(
        default=None,
        gt=0,
        description=(
            "What one R is worth in account currency. Omitted blocks: without it "
            "a drawdown allowance in money cannot be turned into a risk figure."
        ),
    ),
    _: Principal = READ,
) -> dict[str, Any]:
    """A prop-firm rulebook checked against an account state.

    The defaults model a conventional two-phase challenge. They are defaults
    for a *demonstration*, not a rulebook anybody verified — a real provider's
    rules have to be entered and confirmed by whoever signed up for them, and
    the response says so.
    """
    from datetime import date

    # Every remaining rule is stated as NOT_IMPOSED rather than left unset.
    # Since the three-state split, an unset rule means "nobody entered this"
    # and blocks — correctly, for a real account. This endpoint is answering a
    # different question: what a *complete* conventional rulebook would say. So
    # it supplies a complete one, and `rulebook_source` below says whose.
    rules = challenge_brain.ChallengeRules(
        profit_target_pct=profit_target_pct or challenge_brain.NOT_IMPOSED,
        max_daily_drawdown_pct=max_daily_drawdown_pct or challenge_brain.NOT_IMPOSED,
        max_total_drawdown_pct=max_total_drawdown_pct or challenge_brain.NOT_IMPOSED,
        min_trading_days=challenge_brain.NOT_IMPOSED,
        max_trading_days=challenge_brain.NOT_IMPOSED,
        max_leverage=challenge_brain.NOT_IMPOSED,
        max_single_day_profit_share=challenge_brain.NOT_IMPOSED,
        news_trading_allowed=challenge_brain.NOT_IMPOSED,
        weekend_holding_allowed=challenge_brain.NOT_IMPOSED,
        max_concurrent_positions=challenge_brain.NOT_IMPOSED,
        allowance_basis=challenge_brain.AllowanceBasis.STARTING_BALANCE,
        total_drawdown_trailing=False,
    )
    state = challenge_brain.ChallengeState(
        starting_balance=starting_balance,
        current_equity=current_equity,
        peak_equity=max(peak_equity or current_equity, current_equity),
        daily_starting_equity=daily_starting_equity or current_equity,
        days_traded=days_traded,
        open_positions=open_positions,
        current_date=date.today(),
        current_balance=current_equity,
        currency_per_r=currency_per_r,
    )
    payload = challenge_brain.check(rules, state, proposed_risk_r).as_dict()
    payload["rulebook_source"] = (
        "a conventional two-phase example, not a provider's verified rules"
    )
    payload["unstated_rules_are"] = (
        "declared absent, not left unknown. A rule left unset blocks, because "
        "not knowing a provider's limit is not evidence that they have none - "
        "so a real account has to have its rulebook entered before this "
        "endpoint says anything useful about it"
    )
    return payload
