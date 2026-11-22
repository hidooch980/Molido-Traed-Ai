"""Pro BTB Intelligence — an independent, deterministic sub-module.

Shadow analysis only. The optional consumer adapter is off by default and
never overrides Risk Brain. Exact entry/stop/target definitions stay RESEARCH
until a verified source specifies them.
"""

from app.agents.pro_btb.adapter import (
    CONSUMERS,
    ENV_FLAG,
    ProBtbInput,
    is_enabled,
    merge_into_extras,
    read_only_input,
)
from app.agents.pro_btb.engine import ProBtbEngine
from app.agents.pro_btb.params import ProBtbParams
from app.agents.pro_btb.rules import RULE_BY_ID, RULES, placement_rules_ready, status_counts
from app.agents.pro_btb.status import RuleStatus
from app.agents.pro_btb.types import DecisionTrace, Direction, PipelineDecision, PriceRange

__all__ = [
    "CONSUMERS",
    "ENV_FLAG",
    "DecisionTrace",
    "Direction",
    "PipelineDecision",
    "PriceRange",
    "ProBtbEngine",
    "ProBtbInput",
    "ProBtbParams",
    "RULES",
    "RULE_BY_ID",
    "RuleStatus",
    "is_enabled",
    "merge_into_extras",
    "placement_rules_ready",
    "read_only_input",
    "status_counts",
]
