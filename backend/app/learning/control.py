"""A random entry recorded beside every real one, so the real one has a ruler.

This module exists because of a specific mistake, made in this project, on the
day the live system was switched on.

A pre-registered hypothesis was tested on held-out data and the script printed
CONFIRMED. It was wrong. The rule scored 50.84% against a 50.00% breakeven,
which looks like an edge - and the random control run on the same bars scored
50.32%. Over half the apparent edge belonged to no information at all. Without
the control there would have been nothing to notice, and the number would have
been believed.

The live system now records a decision every cycle. In three months there will
be a hit rate, and without a control beside it the same question returns
unanswerable: is 51% good? Against what? A benchmark invented afterwards is a
benchmark chosen to make the answer come out a particular way, which is the
thing pre-registration exists to prevent.

So the control is recorded from the first cycle, on the same bars, at the same
moments, with the same geometry. Three properties make it worth trusting:

**Same bar, same stop, same target.** Only the direction differs. A control
that entered at different times or sized differently would be measuring the
timing or the sizing rather than the direction, and the direction is what the
brain claims to know.

**Seeded per instrument and per moment.** The same bar always produces the same
control side, so a re-run of a period reproduces exactly. A control reseeded
from the clock would give a different answer every time it was recomputed, and
a benchmark that moves is not one.

**Recorded whether or not the brain acted.** The control's job is to say what
no information scores over the whole period, and dropping the bars the brain
skipped would silently restrict it to the bars the brain happened to like.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

#: Fixed, and part of the record. Changing it changes every control side ever
#: derived, which would silently rewrite the benchmark the live results are
#: measured against.
SEED = "molido-control-v1"


@dataclass(frozen=True)
class ControlEntry:
    """What a coin flip would have done on this bar."""

    symbol: str
    at: datetime
    side: int  # +1 long, -1 short
    entry: float
    stop: float
    target: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "at": self.at.isoformat(),
            "side": "long" if self.side > 0 else "short",
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
        }


def side_for(symbol: str, at: datetime) -> int:
    """The control's direction for one bar. Deterministic.

    Derived from a hash of the seed, the symbol and the instant rather than
    from a random number generator, so the same bar always yields the same
    side no matter when or how often it is recomputed. A benchmark that gives a
    different answer on a re-run is not a benchmark.
    """
    key = f"{SEED}:{symbol}:{at.isoformat()}".encode()
    digest = hashlib.sha256(key).digest()
    # One bit. Not a modulo of a larger number, which would bias the split when
    # the range does not divide evenly - a control that is 50.4% long is a
    # control with its own edge.
    return 1 if digest[0] & 1 else -1


def entry_for(
    *,
    symbol: str,
    at: datetime,
    price: float,
    stop_distance: float,
    target_multiple: float = 1.0,
) -> ControlEntry | None:
    """A control entry mirroring the real one's geometry.

    Returns None when the geometry is unusable, rather than substituting a
    default. A control with a stop distance of zero is not a coin flip; it is a
    trade that resolves instantly and would flatter or ruin the benchmark
    depending on which way the tick fell.
    """
    if price <= 0 or stop_distance <= 0:
        return None

    side = side_for(symbol, at)
    return ControlEntry(
        symbol=symbol,
        at=at,
        side=side,
        entry=price,
        stop=price - stop_distance * side,
        target=price + stop_distance * target_multiple * side,
    )


@dataclass(frozen=True)
class Comparison:
    """The rule against the control, and whether the difference is real."""

    rule_wins: int
    rule_losses: int
    control_wins: int
    control_losses: int

    @property
    def rule_trials(self) -> int:
        return self.rule_wins + self.rule_losses

    @property
    def control_trials(self) -> int:
        return self.control_wins + self.control_losses

    @property
    def rule_hit(self) -> float | None:
        return self.rule_wins / self.rule_trials if self.rule_trials else None

    @property
    def control_hit(self) -> float | None:
        return self.control_wins / self.control_trials if self.control_trials else None

    @property
    def edge(self) -> float | None:
        """The rule's hit rate over the control's. The number that matters.

        Not the rule's hit rate over 0.5. That comparison printed CONFIRMED on
        a result whose edge over the control was 0.0052 at z = 1.10.
        """
        if self.rule_hit is None or self.control_hit is None:
            return None
        return self.rule_hit - self.control_hit

    @property
    def z_score(self) -> float | None:
        if not self.rule_trials or not self.control_trials:
            return None
        p1, p2 = self.rule_hit, self.control_hit
        if p1 is None or p2 is None:
            return None
        variance = (
            p1 * (1 - p1) / self.rule_trials + p2 * (1 - p2) / self.control_trials
        )
        if variance <= 0:
            return None
        return (p1 - p2) / variance**0.5

    def trials_needed(self, *, for_edge: float = 0.02) -> int:
        """Roughly how many trials it would take to detect an edge this size.

        Published so the wait is a number rather than a feeling. At two
        percentage points and z = 1.96 the answer is about 4,800 per arm; at
        half a point it is about 77,000, which on a handful of daily decisions
        is longer than anybody will wait - and knowing that in advance is worth
        more than discovering it in a year.
        """
        if for_edge <= 0:
            return 0
        # n per arm for two proportions near 0.5 at z=1.96, power 0.5.
        return int((1.96**2 * 2 * 0.25) / (for_edge**2)) + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": {
                "trials": self.rule_trials,
                "wins": self.rule_wins,
                "hit_rate": round(self.rule_hit, 4) if self.rule_hit is not None else None,
            },
            "control": {
                "trials": self.control_trials,
                "wins": self.control_wins,
                "hit_rate": round(self.control_hit, 4)
                if self.control_hit is not None
                else None,
            },
            "edge_over_control": round(self.edge, 4) if self.edge is not None else None,
            "z_score": round(self.z_score, 2) if self.z_score is not None else None,
            "significant": bool(self.z_score is not None and abs(self.z_score) >= 1.96),
            "trials_needed_for_2pp": self.trials_needed(for_edge=0.02),
            "note": (
                "the edge is measured against the control, never against 50%. "
                "A rule that beats breakeven while not beating a coin flip on "
                "the same bars has beaten nothing"
            ),
        }
