"""Per-agent identity prompts, built from the registry so they cannot drift."""

from __future__ import annotations

from app.agents import registry

OUTPUT_CONTRACT = (
    "Reply with one JSON object only: "
    '{"recommendation": "BUY"|"SELL"|"WAIT"|"ABSTAIN", "confidence": 0..1, '
    '"analysis": str, "evidence": [str], "risk": str}. '
    "Use only the facts given in the input. If they are insufficient, answer ABSTAIN. "
    "Never invent prices, sizes, stops or account data. You cannot place, size or "
    "authorise orders; the independent risk brain decides, and you cannot override it."
)


def system_prompt(agent_id: str) -> str:
    role = registry.get(agent_id)
    if role is None:
        raise KeyError(agent_id)
    duties = "; ".join(role.responsibilities)
    limits = " ".join(role.all_restrictions)
    return (
        f"You are {role.id} ({role.name_en}), part of the Molido Trade AI advisory council. "
        f"Duties: {duties}. Restrictions: {limits} {OUTPUT_CONTRACT}"
    )
