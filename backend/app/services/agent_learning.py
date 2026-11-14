"""Shadow learning and self-healing for the agent layer (stage 17).

Every version of the agent ensemble weights is an append-only memory entry
(kind "model_performance", event "ensemble_weights") with the evidence that
justified it and the version it replaced, so any change can be rolled back.
Applied automatically only here, in the shadow agent ensemble; nothing in this
module writes to the production brains, the council used by execution, the
MLP, account flags, or orders. Weight changes for those stay proposals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents import memory, selfheal
from app.agents.analyzers.runner import ANALYZERS
from app.models.agent_memory import AgentMemoryEntry
from app.services import agent_health

EVENT = "ensemble_weights"


def _versions(session: Session, limit: int = 200) -> list[AgentMemoryEntry]:
    rows = session.scalars(select(AgentMemoryEntry)
                           .where(AgentMemoryEntry.kind == "model_performance")
                           .order_by(AgentMemoryEntry.created_at.desc()).limit(limit))
    return [r for r in rows if (r.content or {}).get("event") == EVENT]


def current(session: Session) -> dict[str, Any]:
    rows = _versions(session, 1)
    if not rows:
        return {"version": 0, "weights": {}, "validated_hit": None, "applied_at": None}
    c = rows[0].content
    at = rows[0].created_at
    return {**c, "applied_at": (at if at.tzinfo else at.replace(tzinfo=UTC)).isoformat()}


def _write(session: Session, version: int, weights: dict[str, float], reason: str,
           evidence: dict[str, Any], previous: int, validated_hit: float | None) -> None:
    memory.remember(session, "BRAIN-01", "model_performance",
                    f"agent ensemble weights v{version}: {reason}",
                    content={"event": EVENT, "version": version, "weights": weights,
                             "reason": reason, "evidence": evidence, "previous": previous,
                             "validated_hit": validated_hit, "scope": "shadow agent ensemble",
                             "rollback": f"re-apply version {previous}"})


def recent_health(session: Session, n: int = 10) -> list[dict[str, dict[str, Any]]]:
    rows = memory.recall(session, kind="agent", limit=n * 3)
    return [r.content.get("agents") or {} for r in rows
            if (r.content or {}).get("event") == "run"][:n]


def quarantined(session: Session) -> set[str]:
    return selfheal.quarantined(recent_health(session), list(ANALYZERS))


def rollback_to(session: Session, version: int, reason: str) -> dict[str, Any]:
    target = next((r.content for r in _versions(session) if r.content["version"] == version),
                  None)
    if target is None and version != 0:
        raise KeyError(version)
    cur = current(session)
    weights = target["weights"] if target else {}
    hit = target.get("validated_hit") if target else None
    _write(session, cur["version"] + 1, weights, f"rollback to v{version}: {reason}",
           {"rolled_back_from": cur["version"]}, cur["version"], hit)
    return current(session)


def learning_cycle(session: Session, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    report: dict[str, Any] = {"as_of": now.isoformat(), "actions": [], "issues": []}
    health = agent_health.health(session, now=now)
    for a in health["agents"]:
        if a["status"] in ("degraded", "stale"):
            report["issues"].append({"agent": a["id"], "issue": a["status"],
                                     "detail": a.get("last_error") or a.get("last_run_at")})
    q = quarantined(session)
    for agent in sorted(q):
        report["actions"].append({"action": "quarantine", "agent": agent,
                                  "until": f"{selfheal.COOLDOWN_RUNS} skipped runs, then retry"})
    perf = agent_health.performance(session, now=now)
    for p in perf["agents"]:
        if p["enough_data"] and p["hit_rate"] is not None and p["hit_rate"] < 0.45:
            report["issues"].append({"agent": p["id"], "issue": "degraded_accuracy",
                                     "detail": f"hit rate {p['hit_rate']:.0%} on {p['calls']}"})

    samples, _ = agent_health.resolved_samples(session, now=now)
    cur = current(session)
    if cur["version"] and cur.get("applied_at"):
        applied_at = datetime.fromisoformat(cur["applied_at"])
        after = [s for s in samples if s.as_of >= applied_at]
        prev = next((r.content for r in _versions(session)
                     if r.content["version"] == cur.get("previous")), None)
        prev_hit = cur.get("evidence", {}).get("current_hit")
        back, hit, n = selfheal.should_roll_back(after, cur["weights"], prev_hit)
        if back:
            rollback_to(session, prev["version"] if prev else 0,
                        f"forward hit {hit:.0%} on {n} < previous {prev_hit:.0%}")
            report["actions"].append({"action": "rollback", "from": cur["version"],
                                      "to": prev["version"] if prev else 0})
            return report
    if len(samples) >= 3 * selfheal.MIN_TEST_CALLS:
        v = selfheal.validate(samples, cur["weights"])
        evidence = {k: v[k] for k in ("current_hit", "current_n", "candidate_hit",
                                      "candidate_n", "train", "test")}
        if v["accept"]:
            _write(session, cur["version"] + 1, v["candidate"],
                   "validated on chronological hold-out", evidence, cur["version"],
                   v["candidate_hit"])
            report["actions"].append({"action": "apply_weights", "version": cur["version"] + 1,
                                      **evidence})
        else:
            report["validation"] = {**evidence, "accepted": False}
    else:
        report["validation"] = {"accepted": False, "reason": f"{len(samples)} resolved runs; "
                                f"need {3 * selfheal.MIN_TEST_CALLS}"}
    for issue in report["issues"]:
        if issue["issue"] == "degraded":
            memory.record_failure(session, "data_error", f"{issue['agent']} errors: "
                                  f"{issue['detail']}", agent_id=issue["agent"])
    return report


def status(session: Session) -> dict[str, Any]:
    return {"current": current(session),
            "history": [{"version": r.content["version"], "reason": r.content["reason"],
                         "validated_hit": r.content.get("validated_hit"),
                         "previous": r.content.get("previous"),
                         "at": r.created_at.isoformat()} for r in _versions(session, 50)],
            "quarantined": sorted(quarantined(session)),
            "scope": "shadow agent ensemble only; production brains, council, MLP and "
                     "execution are not changed by this loop"}
