"""RESEARCH stubs for Weekly MAP and Valid Break-Even. No invented formula."""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.pro_btb.status import RuleStatus
from app.agents.v2.rules import KEY_LEVEL_BY_ID


@dataclass(frozen=True)
class ResearchStub:
    name: str
    available: bool
    rule_id: str
    status: RuleStatus
    reason: str
    sources_checked: tuple[str, ...]
    value: None = None  # always None until a definition is SPECIFIED

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "available": False,
            "value": None,
            "rule_id": self.rule_id,
            "status": self.status.value,
            "reason": self.reason,
            "sources_checked": list(self.sources_checked),
        }


WEEKLY_MAP_SOURCES = (
    "https://www.cmegroup.com/education/courses/technical-analysis/understanding-moving-averages",
    "https://www.tradingview.com/scripts/search/weekly/ (Weekly Map By BT / weekly OHLC scripts)",
    "public weekly-map write-ups (weekly H/L/open, not a MAP formula)",
)

VALID_BE_SOURCES = (
    "search for 'valid break-even' as a named key level (no canonical formula found)",
    "Al Brooks spike/channel base test (not a published Valid BE formula)",
    "Pro BTB four break-even zones are a separate engine and are not reused as a substitute",
)


def weekly_map_stub() -> ResearchStub:
    rule = KEY_LEVEL_BY_ID["WEEKLY_MAP_DEFINITION"]
    return ResearchStub(
        name="weekly_map",
        available=False,
        rule_id=rule.id,
        status=rule.status,
        reason=rule.notes or rule.source,
        sources_checked=WEEKLY_MAP_SOURCES,
    )


def valid_break_even_stub() -> ResearchStub:
    rule = KEY_LEVEL_BY_ID["VALID_BREAK_EVEN_DEFINITION"]
    return ResearchStub(
        name="valid_break_even",
        available=False,
        rule_id=rule.id,
        status=rule.status,
        reason=rule.notes or rule.source,
        sources_checked=VALID_BE_SOURCES,
    )
