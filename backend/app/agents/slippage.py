"""EX02: requested-vs-filled slippage math. Pure; no I/O, no execution imports.

A fill is only usable when both the requested price and the filled price are
present and finite. Missing data is unknown, never zero: treating an unmeasured
slippage as free is how a gate lets a bad fill through.

Adverse slippage is always a cost: for a BUY it is filled minus requested, for
a SELL it is requested minus filled. A negative number is a price improvement
and is recorded honestly, but estimates used for the cap use the p90 of the
adverse series so a few lucky fills cannot hide a heavy tail.

EX02 never recommends BUY or SELL, never approves an intent, and never
overrides a Risk Brain BLOCK. Over the cap it BLOCKs; without enough samples
it WAITs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

MIN_SAMPLES = 5
DEFAULT_CAP_POINTS = 30.0


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_side(side: Any) -> str | None:
    token = str(side or "").strip().upper()
    if token in {"BUY", "LONG"}:
        return "BUY"
    if token in {"SELL", "SHORT"}:
        return "SELL"
    return None


def adverse_price(side: str, requested: float, filled: float) -> float:
    """Positive costs the trader; negative is a price improvement."""
    if side == "BUY":
        return filled - requested
    return requested - filled


def parse_fill(raw: dict[str, Any]) -> dict[str, Any] | None:
    """A complete requested-vs-filled record, or None if it cannot be measured."""
    requested = _finite(raw.get("requested_price"))
    filled = _finite(raw.get("filled_price", raw.get("average_price", raw.get("fill"))))
    side = normalize_side(raw.get("side"))
    symbol = str(raw.get("symbol") or "").strip().upper()
    if requested is None or filled is None or requested <= 0 or filled <= 0:
        return None
    if side is None or not symbol:
        return None
    point = _finite(raw.get("point") or raw.get("tick_size"))
    if point is not None and point <= 0:
        point = None
    adverse = adverse_price(side, requested, filled)
    points = round(adverse / point, 6) if point is not None else None
    return {
        "symbol": symbol,
        "side": side,
        "requested_price": requested,
        "filled_price": filled,
        "adverse_price": adverse,
        "adverse_points": points,
        "point": point,
        "at": raw.get("at"),
        "source": str(raw.get("source") or "unknown"),
        "client_order_id": str(raw.get("client_order_id") or ""),
    }


def percentile(values: list[float], p: float) -> float:
    if not values:
        raise ValueError("percentile of an empty series is undefined")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    frac = k - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


@dataclass(frozen=True)
class SlippageStats:
    symbol: str
    sample_count: int
    mean_points: float | None
    median_points: float | None
    p90_points: float | None
    max_points: float | None
    share_over_cap: float | None
    cap_points: float
    point: float | None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "sample_count": self.sample_count,
            "mean_points": self.mean_points,
            "median_points": self.median_points,
            "p90_points": self.p90_points,
            "max_points": self.max_points,
            "share_over_cap": self.share_over_cap,
            "cap_points": self.cap_points,
            "point": self.point,
            "reason": self.reason,
        }


def summarize(
    fills: list[dict[str, Any]],
    *,
    symbol: str,
    cap_points: float = DEFAULT_CAP_POINTS,
    default_point: float | None = None,
) -> SlippageStats:
    parsed = [p for p in (parse_fill(f) for f in fills) if p and p["symbol"] == symbol.upper()]
    point = default_point
    if point is None or point <= 0:
        points = [p["point"] for p in parsed if p["point"]]
        point = points[-1] if points else None
    measured: list[float] = []
    for p in parsed:
        if p["adverse_points"] is not None:
            measured.append(p["adverse_points"])
        elif point:
            measured.append(p["adverse_price"] / point)
    if not parsed:
        return SlippageStats(
            symbol.upper(), 0, None, None, None, None, None, cap_points, point,
            "no requested-vs-filled samples; not treating slippage as zero",
        )
    if not measured:
        return SlippageStats(
            symbol.upper(), len(parsed), None, None, None, None, None, cap_points, None,
            "fills have no point size, so the cap cannot be priced",
        )
    over = sum(1 for v in measured if v > cap_points) / len(measured)
    return SlippageStats(
        symbol.upper(), len(measured),
        round(sum(measured) / len(measured), 6),
        round(percentile(measured, 0.5), 6),
        round(percentile(measured, 0.9), 6),
        round(max(measured), 6),
        round(over, 4), cap_points, point, "",
    )


@dataclass(frozen=True)
class SlippageDecision:
    recommendation: str
    analysis: str
    evidence: list[str] = field(default_factory=list)
    estimate_points: float | None = None
    sample_count: int = 0
    cap_points: float = DEFAULT_CAP_POINTS
    stats: SlippageStats | None = None

    @property
    def blocks(self) -> bool:
        return self.recommendation == "BLOCK"


def decide(
    fills: list[dict[str, Any]],
    *,
    symbol: str,
    cap_points: float = DEFAULT_CAP_POINTS,
    default_point: float | None = None,
    risk_verdict: str | None = None,
) -> SlippageDecision:
    """WAIT or BLOCK. Never BUY/SELL, never an approval, never undoes a BLOCK."""
    if (risk_verdict or "").upper() == "BLOCK":
        return SlippageDecision(
            "BLOCK",
            "Risk Brain already blocked this; EX02 cannot override it",
            ["risk_verdict=BLOCK"], None, 0, cap_points,
        )
    cap = _finite(cap_points)
    if cap is None or cap < 0:
        return SlippageDecision(
            "WAIT", "slippage cap is missing or invalid; refusing to guess one",
            ["cap unknown"], None, 0, DEFAULT_CAP_POINTS,
        )
    stats = summarize(fills, symbol=symbol, cap_points=cap, default_point=default_point)
    ev = [f"n={stats.sample_count}", f"cap={cap:g} points"]
    if stats.p90_points is not None:
        ev.append(f"p90={stats.p90_points:g} points")
    if stats.mean_points is not None:
        ev.append(f"mean={stats.mean_points:g} points")
    if stats.reason:
        return SlippageDecision("WAIT", stats.reason, ev, None, stats.sample_count, cap, stats)
    if stats.sample_count < MIN_SAMPLES:
        return SlippageDecision(
            "WAIT",
            f"only {stats.sample_count} measured fills (need {MIN_SAMPLES}); estimate withheld",
            ev, None, stats.sample_count, cap, stats,
        )
    estimate = stats.p90_points
    ev.append("estimate is p90 of adverse slippage in points")
    if estimate is not None and estimate > cap:
        return SlippageDecision(
            "BLOCK",
            f"estimated slippage {estimate:g} points exceeds cap {cap:g}",
            ev, estimate, stats.sample_count, cap, stats,
        )
    return SlippageDecision(
        "WAIT",
        f"estimated slippage {estimate:g} points is within cap {cap:g}; "
        "Risk Brain remains the authority to approve",
        ev, estimate, stats.sample_count, cap, stats,
    )


def live_fill_over_cap(fill: dict[str, Any], *, cap_points: float = DEFAULT_CAP_POINTS,
                       default_point: float | None = None) -> bool | None:
    """True if this one fill exceeded the cap, False if it did not, None if unknown."""
    parsed = parse_fill(fill)
    if parsed is None:
        return None
    points = parsed["adverse_points"]
    if points is None:
        point = default_point if default_point and default_point > 0 else parsed["point"]
        if not point:
            return None
        points = parsed["adverse_price"] / point
    cap = _finite(cap_points)
    if cap is None or cap < 0:
        return None
    return points > cap
