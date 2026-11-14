"""Credibility from measured out-of-sample results, never from confidence.

Each resolved call is a record (member, direction, outcome R, out_of_sample).
In-sample records are stored but ignored. Credibility is a shrunk hit rate:
with few records it stays near the prior, so one lucky call earns nothing.
Weight = base weight x credibility factor in [0, 2]; a member below coin-flip
loses weight, one above gains it. `confidence` is not an input anywhere here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

PRIOR_STRENGTH = 20.0
MIN_RECORDS = 10


@dataclass(frozen=True)
class Record:
    member: str
    direction: str
    outcome_r: float
    out_of_sample: bool


@dataclass
class CredibilityBook:
    records: list[Record] = field(default_factory=list)

    def add(self, record: Record) -> None:
        self.records.append(record)

    def stats(self) -> dict[str, dict[str, float]]:
        wins: dict[str, int] = defaultdict(int)
        total: dict[str, int] = defaultdict(int)
        r_sum: dict[str, float] = defaultdict(float)
        for rec in self.records:
            if not rec.out_of_sample or rec.direction not in ("BUY", "SELL"):
                continue
            total[rec.member] += 1
            r_sum[rec.member] += rec.outcome_r
            if rec.outcome_r > 0:
                wins[rec.member] += 1
        return {
            m: {"n": total[m], "wins": wins[m], "avg_r": r_sum[m] / total[m],
                "credibility": self.credibility(m)}
            for m in total
        }

    def credibility(self, member: str) -> float:
        """Shrunk hit rate in [0, 1]; 0.5 when unmeasured."""
        rel = [r for r in self.records if r.member == member and r.out_of_sample
               and r.direction in ("BUY", "SELL")]
        wins = sum(1 for r in rel if r.outcome_r > 0)
        return (wins + 0.5 * PRIOR_STRENGTH) / (len(rel) + PRIOR_STRENGTH)

    def measured(self, member: str) -> bool:
        return sum(1 for r in self.records if r.member == member and r.out_of_sample) \
            >= MIN_RECORDS

    def factor(self, member: str) -> float:
        return max(0.0, min(2.0, 2.0 * self.credibility(member)))
