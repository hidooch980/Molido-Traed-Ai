"""Which of three things an order is: simulated, rehearsed, or real.

`readiness` reported `dry_run_while_simulated` as failing on every deployment,
because the route hard-coded `broker_is_simulated=True` while the only thing
that sends orders builds a `MetaTraderBroker`. The check was right about the
inputs it was given and the inputs were made up. Nothing here changes what
executes; it names, from the objects that actually execute, which mode the
deployment is in.

Three modes, and they are not a ladder:

- **SIMULATED** - the broker adapter is a paper broker. Fills are invented by
  this process. They must be labelled as such everywhere they land, and they
  are (`LivePaperBroker.PAPER_MARKER`); this module's job is to make the
  deployment *say* so.
- **DRY_RUN** - a real broker adapter, with the dry-run flag on. Every order
  stops at the adapter's door and is reported, not sent.
- **LIVE** - a real broker adapter, dry run off. Orders reach the terminal.

The inconsistency the check exists to catch is a paper broker with dry run
*off*: fills that nobody sent recorded as though somebody had. That is a real
state this deployment can be in - autopilot in `paper` mode does exactly it,
on purpose, and labels every fill - so it is reported as SIMULATED with the
label check attached rather than treated as a contradiction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ExecutionMode(StrEnum):
    SIMULATED = "simulated"
    DRY_RUN = "dry_run"
    LIVE = "live"


#: Adapter names that invent their fills. Matched on the adapter's declared
#: `name`, which every adapter carries, rather than on its class, so a test
#: double that says it is paper is treated as paper.
SIMULATED_ADAPTERS = frozenset({"paper"})


@dataclass(frozen=True)
class ModeReport:
    mode: ExecutionMode
    adapter: str
    dry_run: bool
    #: True when a simulated adapter labels its fills. Read from the adapter
    #: rather than assumed: an unlabelled simulated fill is the failure.
    fills_labelled: bool
    reason: str

    @property
    def simulated(self) -> bool:
        return self.mode is ExecutionMode.SIMULATED

    @property
    def consistent(self) -> bool:
        """Whether a simulated deployment can be mistaken for a live one.

        Consistent when the broker is real (dry run or not - both are honest
        states), or when it is simulated and every fill it produces says so.
        """
        if not self.simulated:
            return True
        return self.fills_labelled

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode.value,
            "adapter": self.adapter,
            "dry_run": self.dry_run,
            "simulated": self.simulated,
            "fills_labelled": self.fills_labelled,
            "consistent": self.consistent,
            "reason": self.reason,
        }


def classify(adapter: Any, *, dry_run: bool) -> ModeReport:
    """Name the mode from the adapter that will actually be handed the order."""
    name = str(getattr(adapter, "name", "") or type(adapter).__name__).lower()
    if name in SIMULATED_ADAPTERS:
        import sys

        module = sys.modules.get(type(adapter).__module__)
        marker = (
            getattr(adapter, "PAPER_MARKER", None)
            or getattr(type(adapter), "PAPER_MARKER", None)
            or getattr(module, "PAPER_MARKER", None)
        )
        labelled = bool(marker)
        return ModeReport(
            mode=ExecutionMode.SIMULATED,
            adapter=name,
            dry_run=dry_run,
            fills_labelled=labelled,
            reason=(
                "the broker adapter invents its fills"
                + (" and labels each one" if labelled else " and does NOT label them")
            ),
        )
    if dry_run:
        return ModeReport(
            mode=ExecutionMode.DRY_RUN,
            adapter=name,
            dry_run=True,
            fills_labelled=True,
            reason="a real broker adapter with dry run on: orders are reported, not sent",
        )
    return ModeReport(
        mode=ExecutionMode.LIVE,
        adapter=name,
        dry_run=False,
        fills_labelled=True,
        reason="a real broker adapter with dry run off: orders reach the terminal",
    )


__all__ = ["ExecutionMode", "ModeReport", "SIMULATED_ADAPTERS", "classify"]
