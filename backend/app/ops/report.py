"""The readiness report, machine-readable and human-readable, from runtime.

    docker exec -i molidotrade-api-1 python -m app.ops.report
    docker exec -i molidotrade-api-1 python -m app.ops.report --json

Every line is read from the running system at the moment the command runs:
the evidence notes, the disk, the tables, the kill switch file, the edge
registry. Nothing is remembered from a previous run and nothing is inferred
from the engine being on. A green line here was true when it printed.

The research system and this report share one principle, stated in
`app.ops.readiness`: the system must optimise for discovering whether the
deployment is safe, not for producing a passing report. A red line is a
finding, and a finding is the point.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.session import session_scope
from app.ops import posture as posture_module

ORDER = (
    "no_ungated_mutating_routes",
    "auth_required_if_execution_enabled",
    "kill_switch_defaults_engaged",
    "no_secrets_in_repository",
    "restore_drill_recent",
    "log_rotation",
    "operational_retention",
    "disk_headroom",
    "data_is_fresh",
    "audit_chain_intact",
    "at_least_one_calibrated_source",
    "slo_window_populated",
    "dry_run_while_simulated",
)


def render(posture: posture_module.Posture) -> str:
    settings = get_settings()
    report = posture.report
    decision = posture.decision
    by_name = {c.name: c for c in report.checks}
    lines = ["OPERATIONAL READINESS", ""]
    for name in ORDER:
        check = by_name.get(name)
        if check is None:
            lines.append(f"* {name}: UNKNOWN (not assessed)")
            continue
        verdict = "PASS" if check.passed else ("UNKNOWN" if "could not be determined" in check.detail else "FAIL")
        lines.append(f"* {name}: {verdict} - {check.detail}")
    if posture.reader_failures:
        lines.append("")
        lines.append("readers that failed: " + ", ".join(f"{k} ({v})" for k, v in posture.reader_failures.items()))

    from app.execution import autopilot

    mode, why, _ = autopilot.mode_now()
    lines += [
        "",
        "ENGINE STATE",
        f"LIVE = {'ON' if settings.enable_execution else 'OFF'}",
        f"AUTOPILOT = {'ON' if mode in (autopilot.LIVE, autopilot.PAPER) else 'OFF'} ({mode}: {why})",
        f"EXECUTION ENGINE = {'ON' if decision.engine.value == 'running' else 'OFF'}",
        f"KILL SWITCH = {decision.kill_switch.value.upper()}",
        "",
        "ORDER AUTHORIZATION",
        f"AUTHORIZED = {'YES' if decision.order_authorized else 'NO'}",
    ]
    if not decision.order_authorized:
        for reason in decision.blocking_reasons:
            lines.append(f"  - {reason}")
    if decision.advisories:
        lines.append("advisory:")
        for note in decision.advisories:
            lines.append(f"  - {note}")

    from app.learning import edge as edge_registry

    allowed, reason = edge_registry.live_trading_allowed()
    lines += [
        "",
        "PROVEN EDGE",
        f"registered proven edges: {len([e for e in edge_registry.PROVEN if e.verdict.proven])}",
        f"live trading allowed by the registry: {'YES' if allowed else 'NO'}",
        f"  {reason}",
        f"override in effect: {'YES (MOLIDO_TRADE_WITHOUT_PROVEN_EDGE)' if getattr(settings, 'trade_without_proven_edge', False) else 'NO'}",
        "",
        "REQUIRED NEXT ACTIONS",
    ]
    blockers = [c for c in report.blocking_failures] + [
        c for c in report.important_failures
    ]
    if not blockers and decision.order_authorized:
        lines.append("  none: every check passes and orders are authorised")
    for check in blockers:
        lines.append(f"  [{check.grade.value}] {check.name}: {check.detail}")
    for reason in decision.blocking_reasons:
        if not any(reason.startswith(c.name) for c in blockers):
            lines.append(f"  [order] {reason}")
    lines.append("")
    lines.append(f"checked at {posture.checked_at.isoformat()} from runtime evidence; nothing cached")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="operational readiness from runtime evidence")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    with session_scope() as session:
        posture = posture_module.gather(session, now=datetime.now(UTC))
    if args.json:
        sys.stdout.write(json.dumps(posture.as_dict(), indent=2, default=str) + "\n")
    else:
        sys.stdout.write(render(posture) + "\n")
    return 0 if posture.report.safe_to_trade else 1


if __name__ == "__main__":
    raise SystemExit(main())
