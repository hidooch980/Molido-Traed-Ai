"""Single official status for every Pro BTB rule.

A rule has exactly one status. RESEARCH never promotes until a verified source
names the definition. Specified process rules may rise to IMPLEMENTED or
TESTED after they are coded and covered by tests. VERIFIED is reserved for
independent confirmation against an additional trusted source; nothing here
claims that status.
"""

from __future__ import annotations

from enum import StrEnum


class RuleStatus(StrEnum):
    RESEARCH = "RESEARCH"
    SPECIFIED = "SPECIFIED"
    IMPLEMENTED = "IMPLEMENTED"
    TESTED = "TESTED"
    VERIFIED = "VERIFIED"
