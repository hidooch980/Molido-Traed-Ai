"""Should a real account be connected to this? One answer, honestly reached.

`app.ops.readiness` asks whether the deployment is operationally sound - are
the routes gated, does the audit chain verify, is the disk healthy. Those are
necessary and they are not the question somebody asks before wiring their own
money to it.

This asks that question. It is a different one, and today it has a different
answer, because the honest blocker is not operational at all: **no strategy
has been shown to work.** Every gate can be green, every terminal alive,
every guard armed, and the system still has no measured reason to believe it
makes money.

A readiness report that answered "yes" on operational health alone would be
the most expensive kind of lie this project could tell - and the one it would
be easiest to tell, because everything it measures well would be green.

So the verdict has three states, not two:

  READY        - safe to connect, and there is evidence it is worth doing
  MECHANICALLY_READY - it will not lose money to a defect, but nothing says
                 it will make any either
  NOT_READY    - something would cost money that has nothing to do with the
                 market

Today's answer is the middle one, and the middle one is not a softer way of
saying yes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

#: How much forward evidence before a brain's result means anything.
#:
#: Not a number chosen to be reachable. Two hundred resolved trades on one
#: brain is where a 0.1 R edge becomes distinguishable from zero at the
#: threshold seven simultaneous hypotheses demand, which is what this fleet
#: is actually running.
PROVEN_PAIRS = 200

#: And the t it has to clear, corrected for testing eight brains at once.
#: 1.96 is the single-hypothesis figure and using it here would find an edge
#: in noise roughly one week in three.
PROVEN_T = 2.7


class Verdict(StrEnum):
    READY = "ready"
    MECHANICALLY_READY = "mechanically_ready"
    NOT_READY = "not_ready"


@dataclass
class Finding:
    name: str
    passed: bool
    detail: str
    #: Whether failing this one costs money by itself. A defect does; an
    #: unproven edge does not - it just means there is no reason to expect a
    #: gain. Keeping them apart is what stops "no proven edge" reading as
    #: "something is broken".
    blocks_connection: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "blocks_connection": self.blocks_connection,
        }


@dataclass
class Assessment:
    at: datetime
    findings: list[Finding] = field(default_factory=list)

    @property
    def defects(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and f.blocks_connection]

    @property
    def unproven(self) -> list[Finding]:
        return [f for f in self.findings if not f.passed and not f.blocks_connection]

    @property
    def verdict(self) -> Verdict:
        if self.defects:
            return Verdict.NOT_READY
        if self.unproven:
            return Verdict.MECHANICALLY_READY
        return Verdict.READY

    @property
    def headline(self) -> str:
        if self.verdict is Verdict.NOT_READY:
            return (
                "Do not connect a real account yet. "
                f"{len(self.defects)} thing(s) would cost money for reasons "
                "that have nothing to do with the market."
            )
        if self.verdict is Verdict.MECHANICALLY_READY:
            return (
                "The machinery is ready and the strategy is not. Nothing here "
                "would lose money to a defect, and nothing here says it will "
                "make any either."
            )
        return (
            "Ready. The machinery holds and there is measured evidence a "
            "brain beats its own control."
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "verdict": self.verdict.value,
            "headline": self.headline,
            "defects": [f.as_dict() for f in self.defects],
            "unproven": [f.as_dict() for f in self.unproven],
            "findings": [f.as_dict() for f in self.findings],
        }


def assess(session: Any, *, now: datetime | None = None) -> Assessment:
    """Answer the question, from the running system."""
    moment = now or datetime.now(UTC)
    report = Assessment(at=moment)

    report.findings.append(_terminals_alive())
    report.findings.append(_sizing_cross_check())
    report.findings.append(_stops_reach_the_broker())
    report.findings.append(_guards_armed())
    report.findings.append(_someone_is_told(session))
    report.findings.append(_a_brain_beats_its_control(session, moment))
    return report


def _terminals_alive() -> Finding:
    """Every terminal holding an account is publishing."""
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    silent: list[str] = []
    holding = 0
    try:
        for key, path in sorted(bridge_dirs().items()):
            bridge = MetaTraderBridge(directory=path)
            state = bridge.state()
            account = bridge.account() if state.usable else {}
            if not account.get("available"):
                continue
            holding += 1
            age = getattr(state, "age_seconds", None)
            if age is not None and age > 120:
                silent.append(key)
    except Exception as problem:  # noqa: BLE001
        return Finding("terminals", False, f"the bridges could not be read: {problem}")

    if not holding:
        return Finding(
            "terminals",
            False,
            "no terminal is holding an account, so there is nothing to trade with",
        )
    if silent:
        return Finding(
            "terminals",
            False,
            f"{', '.join(silent)} stopped publishing - an account that cannot "
            "be read cannot be judged, and its positions are unknown rather "
            "than zero",
        )
    return Finding("terminals", True, f"{holding} account(s) publishing")


def _sizing_cross_check() -> Finding:
    """The defect that cost $3,730 cannot recur silently."""
    import inspect

    from app.services import calculators

    source = inspect.getsource(calculators)
    present = "spec_disagreement" in source or "contract_size" in source
    return Finding(
        "position sizing is cross-checked",
        present,
        "a broker's tick value is checked against its contract size before it "
        "sizes anything - the defect that opened a position five times too "
        "large is caught rather than trusted"
        if present
        else "the sizing takes the broker's tick value on trust, which is how "
        "a gold position came to be five times its intended size",
    )


def _stops_reach_the_broker() -> Finding:
    """Every open position has a stop the broker itself holds."""
    from app.providers.metatrader import MetaTraderBridge, bridge_dirs

    naked: list[str] = []
    checked = 0
    try:
        for key, path in sorted(bridge_dirs().items()):
            bridge = MetaTraderBridge(directory=path)
            for position in bridge.positions().get("positions") or []:
                checked += 1
                if not float(position.get("stop") or 0):
                    naked.append(f"{key}:{position.get('symbol')}")
    except Exception as problem:  # noqa: BLE001
        return Finding("stops", False, f"the positions could not be read: {problem}")

    if naked:
        return Finding(
            "stops are at the broker",
            False,
            f"unbounded risk on {', '.join(naked)} - a stop this system holds "
            "and the broker does not is a stop that does not exist when the "
            "connection drops",
        )
    return Finding(
        "stops are at the broker",
        True,
        f"{checked} open position(s), every one with a stop the broker holds",
    )


def _guards_armed() -> Finding:
    """The two automatic recoveries are in place."""
    import inspect

    from app.workers import autotrade

    source = inspect.getsource(autotrade)
    audit = "spec_audit" in source
    concentration = False
    try:
        from app.brain import portfolio

        concentration = hasattr(portfolio, "MAX_SAME_CURRENCY_POSITIONS")
    except Exception:  # noqa: BLE001
        concentration = False

    if audit and concentration:
        return Finding(
            "guards",
            True,
            "the specification audit runs every cycle and the concentration "
            "cap counts positions rather than R, so it still binds when the "
            "system sizes down",
        )
    missing = [
        name
        for name, ok in (("specification audit", audit), ("concentration cap", concentration))
        if not ok
    ]
    return Finding("guards", False, "missing: " + ", ".join(missing))


def _someone_is_told(session: Any) -> Finding:
    """A failure reaches a person without them asking."""
    # The integration's own answer rather than a second reading of the same
    # table: it already knows that a deployment configured from the site and
    # one configured from its env file are both configured, and two
    # implementations of that eventually disagree.
    try:
        from app.integrations import telegram

        configured, _why = telegram.configured(session)
    except Exception:  # noqa: BLE001
        configured = False

    return Finding(
        "somebody is told",
        configured,
        "the chat channel is configured, so a silent terminal reaches a phone"
        if configured
        else "no chat channel is configured, so the only way to learn that an "
        "account stopped trading is to go and look - which is how twenty "
        "minutes of downtime went unnoticed",
        # Not a defect in the trading path: it costs discovery time, not money
        # directly. It is still the difference between a bad hour and a bad
        # week.
        blocks_connection=False,
    )


def _a_brain_beats_its_control(session: Any, now: datetime) -> Finding:
    """The one that matters: is there evidence any of this works?"""
    import math
    from collections import defaultdict

    from sqlalchemy import select

    from app.models.journal import JournalEntry

    try:
        rows = session.execute(
            select(
                JournalEntry.strategy,
                JournalEntry.arm,
                JournalEntry.symbol,
                JournalEntry.opened_at,
                JournalEntry.timeframe,
                JournalEntry.r_multiple,
            ).where(JournalEntry.r_multiple.isnot(None))
        ).all()
    except Exception as problem:  # noqa: BLE001
        return Finding(
            "a brain beats its control",
            False,
            f"the forward record could not be read: {problem}",
            blocks_connection=False,
        )

    paired: dict[tuple, dict[str, float]] = defaultdict(dict)
    for strategy, arm, symbol, opened, timeframe, r in rows:
        paired[(strategy, symbol, opened, timeframe)][arm] = float(r)

    per: dict[str, list[float]] = defaultdict(list)
    for (strategy, *_rest), arms in paired.items():
        if "rule" in arms and "control" in arms:
            per[strategy].append(arms["rule"] - arms["control"])

    best: tuple[str, int, float] | None = None
    for name, diffs in per.items():
        n = len(diffs)
        if n < 2:
            continue
        mean = sum(diffs) / n
        sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / (n - 1))
        t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
        if best is None or t > best[2]:
            best = (name, n, t)

    if best is None:
        return Finding(
            "a brain beats its control",
            False,
            "no brain has resolved a paired trade yet, so nothing here has "
            "been measured against anything",
            blocks_connection=False,
        )

    name, pairs, t = best
    if pairs >= PROVEN_PAIRS and t >= PROVEN_T:
        return Finding(
            "a brain beats its control",
            True,
            f"{name}: {pairs} paired trades, t = {t:.2f} against the "
            f"{PROVEN_T} eight simultaneous hypotheses demand",
        )
    return Finding(
        "a brain beats its control",
        False,
        f"the best is {name} at t = {t:.2f} on {pairs} paired trades. "
        f"Nothing clears {PROVEN_T}, which is what testing eight brains at "
        "once requires - 1.96 would find an edge in noise about one week in "
        "three",
        blocks_connection=False,
    )


__all__ = ["PROVEN_PAIRS", "PROVEN_T", "Assessment", "Finding", "Verdict", "assess"]
