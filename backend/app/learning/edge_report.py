"""The whole battery, against the stored series, in one command.

    docker exec -i molidotrade-collector-1 python -m app.learning.edge_report
    docker exec -i molidotrade-collector-1 python -m app.learning.edge_report --json
    docker exec -i molidotrade-collector-1 python -m app.learning.edge_report --leave-one-out

Reads bars, measures the rule against its control paired by instant, then
puts that measurement through every test in `app.learning.robustness` and
prints what did and did not hold.

**It cannot promote anything.** The registry in `app.learning.edge` decides
what is proven, this reports what is robust, and the two are printed side by
side precisely so the difference stays visible: robustness is a property of a
sample, proof needs pre-registration and evidence generated after the
hypothesis was written down. A rule can be robust on every slice of history
and still be NOT_PROVEN, and that is not a gap in the report.

**Offline.** It opens its own session, reads, and writes nothing. Running it
while the engine trades costs the database a few queries and the engine
nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from app.brain import crosssection
from app.core.enums import Timeframe
from app.learning import robustness as rb
from app.learning.measure import load_series, measure

#: How many instants one horizon spans, for the bootstrap's block length.
#: HORIZON is in bars and the rule fires on every bar it can rank, so on a
#: fully-covered series the two are the same number. Passed explicitly rather
#: than assumed, because a run over a sparse series has fewer instants per bar
#: and a block shorter than the real overlap gives an interval that is too
#: narrow in exactly the flattering direction.
def horizon_instants(instants: int, bars: int, horizon_bars: int) -> int:
    if bars <= 0 or instants <= 0:
        return max(1, horizon_bars)
    per_bar = instants / bars
    return max(1, min(instants, round(horizon_bars * per_bar)))


def run(
    session: Any,
    *,
    provider: str,
    timeframe: Timeframe,
    years: float,
    rule: Any = None,
    hypotheses_tested: int,
    with_leave_one_out: bool,
    draws: int,
) -> dict[str, Any]:
    end = datetime.now(UTC)
    start = end - timedelta(days=365 * years)
    series = load_series(
        session, provider_code=provider, timeframe=timeframe, start=start, end=end
    )
    if not series:
        return {"available": False, "reason": f"no {timeframe.value} bars from {provider}"}

    universe = frozenset(series) & set(crosssection.RANKED_UNIVERSE or series)
    if not universe:
        universe = frozenset(series)

    interval = timeframe.delta
    full = measure(
        series,
        bar_interval=interval,
        universe=frozenset(universe),
        rule=rule,
        keep_instants=True,
    )
    if full.instants == 0:
        return {"available": False, "reason": "no instant in the window could be ranked"}

    bars = max(len(b) for b in series.values())
    from app.workers.resolve import HORIZON

    block = horizon_instants(full.instants, bars, HORIZON)

    excluded: list[rb.Excluded] = []
    fragile: list[str] = []
    if with_leave_one_out:
        excluded, fragile = rb.leave_one_out(
            lambda remaining: measure(
                series, bar_interval=interval, universe=remaining, rule=rule
            ),
            universe=frozenset(universe),
            full_edge=full.edge_r,
        )

    report = rb.assess(
        full,
        horizon_instants=block,
        hypotheses_tested=hypotheses_tested,
        excluded=excluded,
        fragile_on=fragile,
        draws=draws,
    )

    from app.learning import edge as registry

    pending = {e.key: e for e in registry.PENDING_FORWARD}
    rejected = {e.key: e for e in registry.REJECTED}
    name = getattr(rule, "name", "cross-sectional-stretch")
    entry = pending.get(name) or rejected.get(name)

    return {
        "available": True,
        "rule": name,
        "provider": provider,
        "timeframe": timeframe.value,
        "window": full.as_dict()["window"],
        "universe": sorted(universe),
        "leave_one_out_ran": with_leave_one_out,
        "measurement": full.as_dict(),
        "robustness": report.as_dict(),
        "registry": {
            "listed_as": (
                "PENDING_FORWARD" if name in pending else "REJECTED" if name in rejected else "not registered"
            ),
            "verdict": entry.verdict.as_dict() if entry else None,
            "live_trading_allowed": registry.live_trading_allowed()[1],
        },
    }


def render(payload: dict[str, Any]) -> str:
    if not payload.get("available"):
        return f"no measurement: {payload.get('reason')}"
    m = payload["measurement"]
    r = payload["robustness"]
    lines = [
        "=" * 62,
        "MOLIDO EDGE ROBUSTNESS REPORT",
        "=" * 62,
        "",
        f"Rule:       {payload['rule']}",
        f"Series:     {payload['provider']} {payload['timeframe']}, "
        f"{len(payload['universe'])} instruments",
        f"Window:     {(m['window'] or ['?', '?'])[0]} to {(m['window'] or ['?', '?'])[1]}",
        "",
        "-" * 62,
        "MEASUREMENT (paired by instant)",
        "-" * 62,
        f"  instants {m['instants']}   trades {m['trades']}   "
        f"({m['trades_per_instant']} per instant)",
        f"  rule {m['rule_r']:+.4f} R   control {m['control_r']:+.4f} R   "
        f"edge {m['edge_r']:+.4f} R",
        f"  t {m['t']:.2f} clustered, {m['unclustered_t']:.2f} unclustered "
        f"(inflation {m['clustering_inflation']}x)",
        f"  geometry stop {m['geometry']['stop_multiple']} x ATR, "
        f"target {m['geometry']['target_multiple']} x stop, "
        f"horizon {m['geometry']['horizon_bars']} bars",
        "",
        "-" * 62,
        "ROBUSTNESS",
        "-" * 62,
        f"  required t {r['required_t']} for {r['hypotheses_tested']} hypothesis(es)",
        "",
        "  cost stress:",
    ]
    for level in r["cost_stress"]:
        lines.append(
            f"    {level['name']:<9} cost {level['cost_r']:.3f} R  "
            f"net {level['net_r']:+.4f} R  {'survives' if level['survives'] else 'FAILS'}"
        )
    if r["permutation"]:
        p = r["permutation"]
        lines += [
            "",
            f"  placebo: {p['at_least_as_extreme']} of {p['draws']} sign-flipped "
            f"draws reached {abs(p['observed_edge_r']):.4f} R, p = {p['p_value']}",
        ]
    if r["bootstrap"]:
        b = r["bootstrap"]
        lines += [
            f"  bootstrap: median {b['median_edge_r']:+.4f} R, 95% "
            f"[{b['ci_lower_r']:+.4f}, {b['ci_upper_r']:+.4f}] over blocks of "
            f"{b['block_instants']} instants"
            + ("" if b["excludes_zero"] else "  <- contains zero"),
        ]
    lines += ["", "  slices with enough data:"]
    thick = [s for s in r["slices"] if not s["thin"]]
    for s in thick:
        mark = " " if s["positive"] else "*"
        lines.append(
            f"   {mark}{s['name']:<20} n {s['instants']:<6} edge {s['edge_r']:+.4f} R  t {s['t']:.2f}"
        )
    if not thick:
        lines.append("    none - every slice is below the minimum")
    lines.append(f"    ({r['slices_thin']} slice(s) too thin to print)")

    if payload["leave_one_out_ran"]:
        lines += ["", "  leave one instrument out:"]
        for e in sorted(r["leave_one_out"], key=lambda x: x["edge_r"])[:8]:
            lines.append(
                f"    without {e['without']:<10} edge {e['edge_r']:+.4f} R  t {e['t']:.2f}"
            )
        if len(r["leave_one_out"]) > 8:
            lines.append(f"    ... {len(r['leave_one_out']) - 8} more, all higher")

    lines += [
        "",
        "-" * 62,
        "FINDINGS",
        "-" * 62,
    ]
    if r["findings"]:
        for finding in r["findings"]:
            lines.append(f"  - {finding}")
    else:
        lines.append("  none: it held on every test above")

    reg = payload["registry"]
    lines += [
        "",
        "-" * 62,
        "VERDICTS",
        "-" * 62,
        f"  robustness (this sample):  {r['verdict']}",
        f"  registry (proof):          {reg['listed_as']}",
    ]
    if reg["verdict"]:
        for failure in reg["verdict"]["failures"]:
            lines.append(f"    still fails: {failure}")
    lines += [
        "",
        f"  {r['note']}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default="metatrader")
    parser.add_argument("--timeframe", default="H1")
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--rule", default=None, help="a name from app.learning.rules")
    parser.add_argument(
        "--hypotheses",
        type=int,
        default=1,
        help="how many distinct hypotheses were tried to arrive at this one",
    )
    parser.add_argument("--leave-one-out", action="store_true")
    parser.add_argument("--draws", type=int, default=5000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rule = None
    if args.rule:
        from app.learning import rules

        rule = rules.get(args.rule)
        if rule is None:
            print(f"no rule named {args.rule}; known: {', '.join(rules.names())}", file=sys.stderr)
            return 2

    from app.db.session import session_scope

    with session_scope() as session:
        payload = run(
            session,
            provider=args.provider,
            timeframe=Timeframe(args.timeframe),
            years=args.years,
            rule=rule,
            hypotheses_tested=args.hypotheses,
            with_leave_one_out=args.leave_one_out,
            draws=args.draws,
        )

    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
    else:
        sys.stdout.write(render(payload) + "\n")
    return 0 if payload.get("available") else 1


if __name__ == "__main__":
    raise SystemExit(main())
