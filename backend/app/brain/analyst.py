"""The second brain's language half: read the trace, explain it, argue with it.

`pipeline.decide` walks eighteen gates and returns a trace saying where the
decision died. That trace is complete, correct, and close to unreadable - it
answers "which gate" and not "so what", and the operator's actual question is
always the second one. Ninety-eight per cent of evaluations end in a refusal,
so the honest daily summary is "nothing traded, here is why, and here is the
part of that reasoning I think is weak."

Three rules, and the first is the one everything else is arranged around.

**It cannot trade.** There is no import from here to `app.execution`, and
nothing in `app.execution` may import this. That is not a convention - it is
asserted by a test that parses the import graph, because a commentary layer
that grows an order path is precisely how a system acquires a second, unwatched
decision-maker. This module returns text and a verdict about text.

**It cannot invent a number.** Every figure it is allowed to state comes from
the trace it was handed. It is told, in the system prompt and again in the
schema, that "the trace does not say" is a complete answer - and the structured
output has a field for exactly that, so saying so is a thing it can *do*
rather than a thing it has to phrase. A commentary layer that fills gaps with
plausible numbers is worse than none: it launders a guess into the record.

**It is scored later.** Every response is recorded with the trace id it was
about, so "was the analyst right" is a question with an answer. An advisor
nobody grades is an advisor whose track record is whatever anybody remembers,
and the whole point of this system is that memory is not evidence.

**Not configured is not an error, and not a silence either.** With no API key
the analyst returns a verdict saying it is not configured. It does not raise,
because a missing commentary layer must not fail a decision cycle; and it does
not return an empty string, because an empty explanation reads exactly like
"there was nothing to say".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: What the analyst is asked to produce. Constrained rather than free prose so
#: the disagreement is a field that can be counted, not a sentence somebody has
#: to read and classify.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "headline",
        "what_happened",
        "objection",
        "objection_strength",
        "missing_from_the_trace",
        "would_have_traded",
    ],
    "properties": {
        "headline": {
            "type": "string",
            "description": (
                "One sentence a person can read in a notification, in the same "
                "language as the trace's own labels. State the outcome, not a "
                "judgement about it."
            ),
        },
        "what_happened": {
            "type": "string",
            "description": (
                "The chain, in plain language: which gates passed, which one "
                "stopped it, and what that gate was actually measuring. Name "
                "only figures that appear in the trace."
            ),
        },
        "objection": {
            "type": "string",
            "description": (
                "The strongest argument that this decision was wrong. Argue "
                "against the chain, not for it - agreeing is what the chain "
                "already did. If there is genuinely no objection worth making, "
                "say so in one sentence rather than manufacturing one."
            ),
        },
        "objection_strength": {
            "type": "string",
            "enum": ["none", "weak", "worth_checking", "serious"],
            "description": (
                "How much weight the objection deserves. 'serious' means a "
                "person should look at this today."
            ),
        },
        "missing_from_the_trace": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Facts that would change the answer and are not in the trace. "
                "An empty list means nothing was missing - not that nothing "
                "was checked."
            ),
        },
        "would_have_traded": {
            "type": "boolean",
            "description": (
                "Whether the analyst, reading only this trace, would have taken "
                "the trade. Recorded for scoring and acted on by nothing."
            ),
        },
    },
}

SYSTEM = """You are the second opinion on an automated trading system's decisions.

You are reading a decision trace: a chain of gates, each of which either passed
or stopped the decision, with the reason each gave. Most traces end in a refusal.
That is the system working, not failing.

Your job is to explain what happened and then to argue against it. The chain has
already made the case for its own answer; repeating it is worth nothing. What is
worth something is the strongest honest objection - the gate whose threshold
looks arbitrary, the reason that describes a symptom rather than a cause, the
refusal that would have been an approval on a slightly different bar.

Four rules.

**Every number you state must appear in the trace.** You may not estimate,
interpolate, annualise, or infer a figure that is not written there. If a
quantity matters and is absent, put it in `missing_from_the_trace` and say the
trace does not give it. A number you produced is indistinguishable, later, from
one the system measured - and it will be read as measurement.

**Do not manufacture an objection.** `objection_strength: "none"` is a real and
frequently correct answer. An advisor who always finds something is an advisor
whose findings mean nothing.

**You are not deciding anything.** Nothing you write reaches an order. Say what
you think and let it be recorded; do not hedge toward whatever seems safe, and
do not soften an objection because the system might act on it. It will not.

**Uncertainty reduces confidence; it never manufactures it.** If the trace is
thin, the correct response is a thin answer that says so."""


@dataclass(frozen=True)
class Verdict:
    """What the analyst said, and whether it said anything at all."""

    available: bool
    headline: str
    what_happened: str = ""
    objection: str = ""
    objection_strength: str = "none"
    missing_from_the_trace: tuple[str, ...] = ()
    would_have_traded: bool = False
    #: Why there is no analysis, when there is none. Empty when there is.
    unavailable_because: str = ""
    model: str = ""
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "headline": self.headline,
            "what_happened": self.what_happened,
            "objection": self.objection,
            "objection_strength": self.objection_strength,
            "missing_from_the_trace": list(self.missing_from_the_trace),
            "would_have_traded": self.would_have_traded,
            "unavailable_because": self.unavailable_because,
            "model": self.model,
            "at": self.at.isoformat(),
            # Restated on every payload rather than documented once. The field
            # a reader is most likely to act on is `objection`, and this is the
            # sentence that stops them treating it as an instruction.
            "note": (
                "commentary only. No path exists from this output to the "
                "execution engine, and the trade decision was already made "
                "without it"
            ),
        }


def unavailable(reason: str) -> Verdict:
    """A verdict that says there is no verdict, and why.

    Not an exception and not an empty string. A missing commentary layer must
    not fail a decision cycle, and an empty explanation reads exactly like
    "there was nothing to say".
    """
    return Verdict(
        available=False,
        headline="No analysis was produced.",
        unavailable_because=reason,
    )


def _trim(trace: dict[str, Any], *, max_chars: int = 60_000) -> str:
    """The trace as JSON, whole or refused - never quietly shortened.

    A truncated trace produces an analysis of a decision that did not happen,
    and nothing downstream can tell the difference. So an oversized trace is
    reported as unanalysable rather than cut down to fit.
    """
    body = json.dumps(trace, ensure_ascii=False, default=str, sort_keys=True)
    if len(body) > max_chars:
        raise ValueError(
            f"the trace is {len(body)} characters, over the {max_chars} this "
            "will send. Truncating it would produce an analysis of a decision "
            "that did not happen"
        )
    return body


def analyse(
    trace: dict[str, Any],
    *,
    client: Any = None,
    language: str = "fa",
) -> Verdict:
    """Read one decision trace and return an explanation and an objection.

    `client` is injectable so the whole path is testable without a network,
    and so a caller batching many traces can supply one client rather than
    building one per call.

    Never raises. Every failure - no key, no package, a refusal, a rate limit,
    a malformed response - becomes an `unavailable` verdict carrying the
    reason. The caller is in the middle of a decision cycle and the analyst is
    the least important thing in it.
    """
    settings = get_settings()

    if client is None:
        if not settings.anthropic_api_key:
            return unavailable(
                "no API key is configured (MOLIDO_ANTHROPIC_API_KEY), so there "
                "is no analyst - which is different from an analyst with "
                "nothing to say"
            )
        try:
            import anthropic
        except ImportError:
            return unavailable(
                "the `anthropic` package is not installed in this deployment"
            )
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        body = _trim(trace)
    except ValueError as oversized:
        return unavailable(str(oversized))

    try:
        response = client.messages.create(
            model=settings.analyst_model,
            max_tokens=settings.analyst_max_tokens,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            output_config={
                "effort": settings.analyst_effort,
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Answer in {language}. Here is the decision trace:\n\n{body}"
                    ),
                }
            ],
        )
    except Exception as failure:  # noqa: BLE001 - see the docstring
        # Deliberately broad. The SDK raises a family of typed errors and the
        # network raises others, and the caller's response to every one of them
        # is identical: carry on without an analysis. Narrowing this would mean
        # listing the ones that may pass and letting a new one fail a cycle.
        log.warning("analyst.call_failed", error=type(failure).__name__, exc_info=True)
        return unavailable(f"the analyst could not be reached: {type(failure).__name__}")

    # A refusal is not a failure and must not be reported as an empty analysis.
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        return unavailable(
            f"the model declined to answer ({getattr(details, 'category', 'unstated')})"
        )

    payload = _first_json(response)
    if payload is None:
        return unavailable("the analyst answered in a shape this cannot read")

    return Verdict(
        available=True,
        headline=str(payload.get("headline", "")),
        what_happened=str(payload.get("what_happened", "")),
        objection=str(payload.get("objection", "")),
        objection_strength=str(payload.get("objection_strength", "none")),
        missing_from_the_trace=tuple(
            str(m) for m in payload.get("missing_from_the_trace", []) or []
        ),
        would_have_traded=bool(payload.get("would_have_traded", False)),
        model=str(getattr(response, "model", "") or ""),
    )


def _first_json(response: Any) -> dict[str, Any] | None:
    """The structured object out of the response, whichever way it arrived.

    Read defensively rather than indexed. `content[0]` is a thinking block
    whenever thinking is on, and an analyst that crashed on its own reasoning
    would be a commentary layer that fails exactly when it is thinking hardest.
    """
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) != "text":
            continue
        text = getattr(block, "text", "") or ""
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
