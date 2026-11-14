"""Run every analyzer for one symbol on stored data, with health (shadow only).

Inputs, each optional and stated when missing:
  bars     stored, point-in-time (agent_scan.candles)
  spread   bridge quote (ask - bid) from molido_symbols.json
  ticks    bridge tick file molido_ticks_<SYM>.csv, written only when the EA's
           remote tick_count > 0 (MOLIDO_EA_TICK_COUNT); SC02 falls back to bars
  events   high-impact calendar (MOLIDO_AGENT_CALENDAR)
  cot      CFTC positioning for SM10 (MOLIDO_AGENT_COT, default off: network)
Nothing here places, sizes or routes an order.
"""

from __future__ import annotations

import csv
import os
import pathlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory
from app.agents.analyzers.bars import make_context
from app.agents.analyzers.runner import run_timed
from app.core.enums import Timeframe
from app.models.instruments import Instrument
from app.services import agent_events, agent_scan

COT_FLAG = "MOLIDO_AGENT_COT"
MAX_TICK_FILE_AGE = timedelta(minutes=10)


def cot_enabled() -> bool:
    return os.getenv(COT_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def read_ticks(directory: pathlib.Path, symbol: str, now: datetime) -> list[dict[str, Any]] | None:
    """Ticks in UTC. MT5 stamps them in server time; the whole-hour offset is taken
    from the newest tick against `now` (ticks are seconds old when written)."""
    path = directory / f"molido_ticks_{symbol}.csv"
    try:
        if now.timestamp() - path.stat().st_mtime > MAX_TICK_FILE_AGE.total_seconds():
            return None
        with path.open(encoding="utf-8", errors="ignore") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return None
    raw = []
    for row in rows:
        try:
            raw.append((int(row["time_msc"]), float(row["bid"]), float(row["ask"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not raw:
        return None
    newest = datetime.fromtimestamp(max(r[0] for r in raw) / 1000, UTC)
    shift_h = round((newest - now).total_seconds() / 3600)
    if abs(shift_h) > 14:
        return None
    shift = timedelta(hours=shift_h)
    return [{"time": datetime.fromtimestamp(t / 1000, UTC) - shift, "bid": b, "ask": a}
            for t, b, a in raw]


def quote_spread(symbols_payload: dict[str, Any], symbol: str) -> float | None:
    for entry in symbols_payload.get("symbols", []):
        if entry.get("name") == symbol and entry.get("ask") and entry.get("bid"):
            spread = float(entry["ask"]) - float(entry["bid"])
            return spread if spread >= 0 else None
    return None


def cot_share(symbol: str, at: datetime, *, opener: Any = None) -> float | None:
    """CFTC tilt (-1..1, base minus quote) as SM10's 0..1 'net long share'."""
    if not cot_enabled():
        return None
    from app.services import positioning

    try:
        tilt = float(positioning.pair_tilt(symbol[:3], symbol[3:6], at, opener=opener)["tilt"])
    except Exception:  # noqa: BLE001 - unknown is WAIT, never a guess
        return None
    return max(0.0, min(1.0, 0.5 + tilt / 2))


def minutes_to_event(events: list[dict[str, Any]] | None, symbol: str,
                     at: datetime) -> float | None:
    if events is None:
        return None
    ccys = agent_events.currencies(symbol)
    ahead = [(e["time"] - at).total_seconds() / 60 for e in events
             if e["currency"] in ccys and e["time"] >= at - agent_events.WINDOW_AFTER]
    return min(ahead) if ahead else None


def run_symbol(session: Session, symbol: str, timeframe: Timeframe, *,
               as_of: datetime | None = None, bridge: Any = None,
               events: list[dict[str, Any]] | None = None, record: bool = False,
               skip: set[str] | None = None,
               context: dict[str, Any] | None = None) -> dict[str, Any]:
    as_of = (as_of or datetime.now(UTC)).astimezone(UTC)
    inst = session.scalars(select(Instrument).where(Instrument.symbol == symbol)).first()
    if inst is None:
        return {"symbol": symbol, "status": "unknown_symbol"}
    market = agent_scan.market_of(inst)
    if market is None:
        return {"symbol": symbol, "status": "skipped", "reason": "market not covered"}
    provider, bars = agent_scan.candles(session, inst, timeframe, as_of)
    inputs: dict[str, Any] = {"bars": len(bars), "provider_id": provider}
    spread = ticks = None
    if bridge is not None:
        try:
            spread = quote_spread(bridge.symbols(now=as_of), symbol)
        except Exception:  # noqa: BLE001
            spread = None
        ticks = read_ticks(bridge.directory, symbol, as_of)
    extras: dict[str, Any] = dict(context or {})
    if ticks:
        extras["ticks"] = ticks
    if events is not None:
        extras["events"] = events
    share = cot_share(symbol, as_of) if market.value == "forex" else None
    if share is not None:
        extras["cot_speculative_net_long_share"] = share
    inputs.update(spread=spread, ticks=len(ticks or []), calendar=events is not None,
                  cot=share is not None)
    ctx = make_context(symbol, market, timeframe.value, timeframe.delta, bars, as_of,
                       spread=spread, minutes_to_high_impact=minutes_to_event(events, symbol,
                                                                              as_of),
                       extras=extras)
    messages, health = run_timed(ctx, skip or set())
    from app.services import agent_voting

    weights = (context or {}).get("vote_weights")
    if not isinstance(weights, dict):
        try:
            weights = agent_voting.current_weights(session, now=as_of)
        except Exception:  # noqa: BLE001 - vote is advisory; a miss is WAIT
            weights = {}
    vote = agent_voting.vote_for_run(health, weights, bars=list(ctx.bars))
    out = {"symbol": symbol, "timeframe": timeframe.value, "as_of": as_of.isoformat(),
           "status": "ran", "mode": "shadow_only", "inputs": inputs,
           "messages": [m.model_dump(mode="json") for m in messages], "health": health,
           "regime": vote.get("regime_detail"), "vote": vote}
    if record:
        memory.remember(session, "BRAIN-01", "agent",
                        f"agent run {symbol} {timeframe.value}: "
                        f"{sum(1 for h in health.values() if not h['ok'])} errors",
                        content={"event": "run", "timeframe": timeframe.value,
                                 "as_of": as_of.isoformat(), "inputs": inputs,
                                 "agents": health, "regime": out["regime"],
                                 "vote": vote}, symbol=symbol)
    return out


RUN_FLAG = "MOLIDO_AGENT_RUN"
MAX_IDLE = 900


def _last_run_at(session: Session) -> datetime | None:
    for row in memory.recall(session, kind="agent", limit=40):
        if (row.content or {}).get("event") != "run":
            continue
        raw = (row.content or {}).get("as_of") or row.created_at
        if isinstance(raw, datetime):
            return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
        try:
            at = datetime.fromisoformat(str(raw))
        except ValueError:
            continue
        return at if at.tzinfo else at.replace(tzinfo=UTC)
    return None


def due(session: Session, *, now: datetime | None = None, bridge: Any = None,
        timeframe: Timeframe = Timeframe.H1, max_idle: int = MAX_IDLE) -> str | None:
    """Event-driven wake: new closed bar, large price move, or the idle cap."""
    from app.agents.guards import decide_trigger
    from app.models.instruments import Instrument
    from app.services import agent_symbols

    now = (now or datetime.now(UTC)).astimezone(UTC)
    last = _last_run_at(session)
    newest_close = last_price = last_close = last_range = None
    names = list(agent_symbols.universe(session).get("symbols") or [])[:8]
    for name in names:
        inst = session.scalars(select(Instrument).where(Instrument.symbol == name)).first()
        if inst is None:
            continue
        _, bars = agent_scan.candles(session, inst, timeframe, now, lookback=4)
        if not bars:
            continue
        closed = bars[-1].open_time + timeframe.delta
        if newest_close is None or closed > newest_close:
            newest_close = closed
            last_close = bars[-1].close
            last_range = bars[-1].high - bars[-1].low
    if bridge is not None:
        try:
            payload = bridge.symbols(now=now)
            for name in names:
                for entry in payload.get("symbols", []):
                    if entry.get("name") == name and entry.get("ask") and entry.get("bid"):
                        last_price = (float(entry["ask"]) + float(entry["bid"])) / 2
                        break
                if last_price is not None:
                    break
        except Exception:  # noqa: BLE001, S110
            pass
    return decide_trigger(last_run=last, now=now, newest_close=newest_close,
                          last_price=last_price, last_close=last_close,
                          last_range=last_range, max_interval=max_idle)


def run_enabled() -> bool:
    return os.getenv(RUN_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def run_cycle(session: Session, timeframe: Timeframe = Timeframe.H1, *,
              symbols: list[str] | None = None, bridge: Any = None,
              max_symbols: int = 30, learn: bool = True) -> dict[str, Any]:
    """One recorded pass over the symbol universe, feeding /agents/health and
    /agents/performance. Shadow only."""
    if symbols is None:
        from app.services import agent_symbols

        symbols = list(agent_symbols.universe(session).get("symbols") or [])
    from app.services import agent_learning

    events = agent_events.high_impact()
    skip = agent_learning.quarantined(session)
    from app.services import agent_slippage

    context = agent_slippage.cycle_context(session, bridge=bridge)
    try:
        from app.services import agent_voting

        context["vote_weights"] = agent_voting.current_weights(session)
    except Exception as exc:  # noqa: BLE001
        context["vote_weight_error"] = type(exc).__name__
    done = [run_symbol(session, s, timeframe, bridge=bridge, events=events, record=True,
                       skip=skip, context=context) for s in symbols[:max_symbols]]
    learning = agent_learning.learning_cycle(session) if learn else None
    from app.services import agent_brain_shadow

    shadow = None
    if agent_brain_shadow.enabled():
        weights = agent_learning.current(session)["weights"]
        shadow = agent_brain_shadow.cycle(session, [d for d in done if d["status"] == "ran"],
                                          weights)
        shadow["evaluation"] = agent_brain_shadow.evaluate(session)["status"]
    return {"timeframe": timeframe.value, "ran": sum(1 for d in done if d["status"] == "ran"),
            "skipped": [d["symbol"] for d in done if d["status"] != "ran"],
            "quarantined": sorted(skip), "learning": learning, "brain_shadow": shadow}


def main() -> int:
    if not run_enabled():
        print(f"{RUN_FLAG} is off; nothing done.")
        return 0
    from app.db.session import session_scope
    from app.services import agent_account

    with session_scope() as session:
        bridge = agent_account._provider(None, session)
        why = due(session, bridge=bridge)
        if why is None:
            print("skip: no new close or move")
            return 0
        print({"trigger": why, **run_cycle(session, bridge=bridge)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
