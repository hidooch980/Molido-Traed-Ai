"""Agents loop housekeeping (t57u), one short pass per cycle, low CPU:
backtest gate for a new strategy/EA version, Telegram alerts (off until
configured) and the nightly report. Paper/shadow only; never places orders."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


def cycle(session: Session) -> dict[str, Any]:
    from app.services import (
        agent_account,
        agent_backtest_gate,
        agent_notify,
        agent_report,
        ea_config,
    )

    out: dict[str, Any] = {}
    steps: list[tuple[str, Any]] = [
        ("backtest_gate", lambda: agent_backtest_gate.run_strategy_gate(session)["verdict"]),
        ("ea_gate", lambda: (agent_backtest_gate.run_ea_gate(session, ea_config.ea_release())
                             or {}).get("verdict")),
        ("notify", lambda: agent_notify.cycle(
            session, risk_ctx=agent_account.risk_context(session=session))),
        ("nightly_report", lambda: bool(agent_report.maybe_run(session))),
    ]
    for name, step in steps:
        try:
            with session.begin_nested():
                out[name] = step()
        except Exception as exc:  # noqa: BLE001 - one step failing must not stop the rest
            out[name] = f"error: {type(exc).__name__}"
    return out


def main() -> int:
    from app.db.session import session_scope

    with session_scope() as session:
        print(cycle(session))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
