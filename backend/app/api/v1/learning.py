"""Learning-lab endpoints (spec §31-36).

Five modules that decide whether a model is allowed to keep its job, and none
of them had a way to be asked. They are grouped here because they answer one
question between them — *is there evidence this works?* — and separating them
across five routers would let a caller read the flattering half.

Two things shape every route below.

**Nothing here has a live sample yet.** No forecasts have been resolved for
this deployment, so the honest answers are refusals with reasons rather than
numbers. Endpoints that manufactured a demonstration sample would publish a
hit rate this system has not earned, and it would look identical to one it had.
Where a caller supplies a sample, it is scored; where they do not, the answer
says what is missing.

**The scorecard is the point of the group.** A hit rate is not evidence: the
interval decides, the breakeven comes from the realised payoff rather than the
intended one, and the threshold widens for how many things were tested at once.
Callers get all three, because a bare percentage is exactly the number somebody
quotes back while asking for a bigger position.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.core.enums import Permission
from app.db.session import get_db
from app.learning import drift as drift_module
from app.learning import lab as lab_module
from app.learning import registry as registry_module
from app.learning import scorecard as scorecard_module

router = APIRouter(prefix="/learning", tags=["learning"])

READ = Depends(require(Permission.READ))


@router.get("/thresholds")
def read_thresholds(_: Principal = READ) -> dict[str, Any]:
    """Every line this layer judges against, with the reason for each.

    Published because a threshold nobody can see is one nobody can argue with,
    and these are the numbers that decide whether a model is called good.
    """
    return {
        "scorecard": {
            "min_trials": scorecard_module.MIN_TRIALS,
            "confidence_z": scorecard_module.Z,
            "why": (
                "below the minimum a strategy has a sample rather than a result; "
                "the interval decides, never the point estimate"
            ),
        },
        "registry": {
            "min_evaluation_sample": registry_module.MIN_EVALUATION_SAMPLE,
            "min_overlap": registry_module.MIN_OVERLAP,
            "promotion_sigma": registry_module.PROMOTION_SIGMA,
            "why": (
                "two models scored on different weeks were scored on different "
                "markets; the overlap is what makes the comparison one comparison"
            ),
        },
        "drift": {
            "psi_shifted": drift_module.PSI_SHIFTED,
            "psi_broken": drift_module.PSI_BROKEN,
            "min_sample": drift_module.MIN_DRIFT_SAMPLE,
            "why": (
                "feature drift needs no outcomes and is the early warning; "
                "concept drift needs matured outcomes and is the expensive one"
            ),
        },
        "note": "these are policy choices, published so they can be disputed",
    }


@router.get("/scorecard")
def read_scorecard(
    wins: int = Query(default=0, ge=0),
    losses: int = Query(default=0, ge=0),
    average_win_r: float = Query(default=2.0, gt=0),
    average_loss_r: float = Query(default=1.0, gt=0),
    unresolved: int = Query(default=0, ge=0),
    comparisons: int = Query(
        default=1, ge=1, description="How many strategies were tested at once."
    ),
    _: Principal = READ,
) -> dict[str, Any]:
    """Judge a result against the hit rate its own payoff demands.

    Takes counts rather than reading a live sample, because there is no live
    sample. That makes this a calculator an operator can check their own
    reasoning against — including the two corrections people skip: breakeven
    from the realised payoff, and a threshold widened for multiple looks.
    """
    trials = (
        [scorecard_module.Trial("supplied", average_win_r) for _ in range(wins)]
        + [scorecard_module.Trial("supplied", -average_loss_r) for _ in range(losses)]
        + [scorecard_module.Trial("supplied", None) for _ in range(unresolved)]
    )
    card = scorecard_module.score(
        trials, strategy="supplied", comparisons=comparisons
    )
    payload = card.as_dict()
    payload["uncorrected_comparison"] = (
        scorecard_module.score(trials, strategy="supplied", comparisons=1).verdict
        if comparisons > 1
        else None
    )
    return payload


@router.get("/breakeven")
def read_breakeven(
    reward_risk: float = Query(gt=0, description="Realised reward:risk, not the target."),
    _: Principal = READ,
) -> dict[str, Any]:
    """The hit rate a payoff needs just to stand still."""
    required = scorecard_module.breakeven_hit_rate(reward_risk)
    return {
        "reward_risk": reward_risk,
        "required_hit_rate": round(required, 6) if required else None,
        "note": (
            "use the payoff that happened, not the one intended — a strategy "
            "built to 2R that returns 1.3R needs 43%, not 33%"
        ),
    }


@router.get("/walk-forward")
def read_walk_forward(
    samples: int = Query(default=400, ge=1, le=100_000),
    folds: int = Query(default=3, ge=1, le=20),
    embargo_hours: int = Query(default=6, ge=0),
    maturity_hours: int = Query(default=4, ge=0),
    _: Principal = READ,
) -> dict[str, Any]:
    """Plan a leak-free walk-forward split over evenly spaced samples.

    The plan is what matters, not the data: it shows how many training samples
    each fold loses to purging and to the embargo, which is the cost of not
    leaking and is usually larger than people expect.
    """
    start = datetime(2024, 1, 1, tzinfo=UTC)
    generated = [
        lab_module.Sample(
            sample_id=f"s{i:05d}",
            event_time=start + timedelta(hours=i),
            outcome_ready_at=start + timedelta(hours=i + maturity_hours),
        )
        for i in range(samples)
    ]
    try:
        plan = lab_module.walk_forward(
            generated, folds=folds, embargo=timedelta(hours=embargo_hours)
        )
    except Exception as exc:  # noqa: BLE001 - the refusal is the answer
        return {
            "available": False,
            "reason": str(exc),
            "note": "a fold that cannot be built clean is not a fold",
        }

    # Verified rather than asserted: the builder that made a mistake would
    # record it consistently, so the check re-derives from the samples.
    lab_module.assert_no_leakage(plan, generated)
    payload = plan.as_dict()
    payload["available"] = True
    payload["leakage_verified"] = True
    return payload


@router.get("/drift")
def read_drift(
    _: Principal = READ,
) -> dict[str, Any]:
    """What this deployment can currently say about drift.

    Nothing, and the reason is the useful part: feature drift needs a reference
    window this deployment has not established, and concept drift needs matured
    outcomes it has not produced. Reporting "stable" here would be the most
    reassuring possible lie.
    """
    return {
        "feature_drift": drift_module.population_stability([], []).as_dict(),
        "concept_drift": drift_module.concept_drift([], []).as_dict(),
        "note": (
            "both refuse for lack of a sample; a drift monitor that reports "
            "stable before it has data reports stable forever"
        ),
    }


@router.get("/registry")
def read_registry(_: Principal = READ) -> dict[str, Any]:
    """Model versions and their stages.

    Empty, and the response says so rather than returning an empty list that
    reads as "nothing is wrong". No model has been registered for this
    deployment, which is why the chain refuses at the expected-value gate.
    """
    empty = registry_module.ModelRegistry()
    payload = empty.as_dict()
    payload["champion"] = None
    payload["reason"] = (
        "no model version has been registered for this deployment, so nothing "
        "has a calibrated probability and every expected value refuses"
    )
    payload["promotion_requires"] = {
        "min_sample": registry_module.MIN_EVALUATION_SAMPLE,
        "min_overlap": registry_module.MIN_OVERLAP,
        "sigma": registry_module.PROMOTION_SIGMA,
        "and": "promotion out of shadow only — a champion has to have been wrong "
        "somewhere it cost nothing first",
    }
    return payload


@router.get("/research")
def read_research(_: Principal = READ) -> dict[str, Any]:
    """Where the search for an edge actually stands.

    The one page in this system whose job is to say "nothing yet" clearly. Every
    other page reports what the system knows; this one reports what it has
    failed to establish, which is the more useful fact when a person is deciding
    whether to trust it with money.

    Nothing here is computed on request. The claims are registered, the numbers
    are the ones they were registered with, and the verdicts are recomputed from
    those numbers so a reader can check the arithmetic rather than trust it.
    """
    from app.learning import control as control_module
    from app.learning import edge as edge_registry

    proven = [e.as_dict() for e in edge_registry.PROVEN if e.verdict.proven]
    rejected = [e.as_dict() for e in edge_registry.REJECTED]
    allowed, why = edge_registry.live_trading_allowed()

    empty = control_module.Comparison(
        rule_wins=0, rule_losses=0, control_wins=0, control_losses=0
    )

    return {
        "live_trading_allowed": allowed,
        "reason": why,
        "proven": proven,
        # Kept and published. "We tried nothing" and "we tried this and it did
        # not clear the bar" are different facts, and hiding the second invites
        # the same rule being proposed again next month as a new idea.
        "rejected": rejected,
        "requirements": [
            "pre-registered: the hypothesis, geometry, data slice and threshold "
            "written down before the held-out data is read",
            "beats a random control on the same bars, not breakeven - the "
            "control is what no information scores on that data",
            "significant after correcting for how many candidates were tried",
            "net of a spread the broker actually charges: an edge smaller than "
            "the spread is not a small edge, it is a loss",
            "confirmed on data generated after registration, not only on a "
            "held-out slice of history",
        ],
        "sample_needed": {
            "for_a_2pp_edge": empty.trials_needed(for_edge=0.02),
            "for_a_1pp_edge": empty.trials_needed(for_edge=0.01),
            "for_a_half_pp_edge": empty.trials_needed(for_edge=0.005),
            "note": "per arm, at z = 1.96",
        },
        "note": (
            "the forward measurement started when the live loop did. Until it "
            "has the sample above, the honest answer to 'does this work' is "
            "that nobody knows - including this system"
        ),
    }


@router.get("/readiness")
def read_readiness(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """When the forward measurement will be able to answer the question.

    The question people actually ask is "when can I connect a real account",
    and the honest form is not a countdown to yes - it is when there will be
    enough evidence to answer at all. The rule may fail, and on the evidence so
    far that is the likelier outcome: re-run unchanged on eleven years of daily
    bars it scored -0.0015 R against its control at t = -0.12.

    Both series, because they accumulate at different rates: the public feed
    ranks forty-nine instruments and the broker twenty-eight, so their tails
    differ in size and one will reach a usable sample before the other.
    """
    from app.models.journal import SOURCE_BROKER, SOURCE_PUBLIC
    from app.services import journal_log

    return {
        "by_source": {
            source: journal_log.readiness_of(session, price_source=source).as_dict()
            for source in (SOURCE_PUBLIC, SOURCE_BROKER)
        },
        "and_then_what": (
            "a sample that clears the bar is necessary and not sufficient. A "
            "funded account is refused separately by "
            "MOLIDO_ALLOW_REAL_MONEY_ORDERS, which is off deliberately, so "
            "reaching the date opens the question rather than the account"
        ),
    }


@router.get("/journal")
def read_journal(
    _: Principal = READ,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    """Every decision recorded, and what the two arms say so far.

    The rule and the random control are counted from the same table over the
    same bars, so the headline is the difference between them rather than the
    rule's hit rate on its own. A rule that beats breakeven while matching a
    coin flip has beaten nothing, and this project has already published one
    CONFIRMED that missed exactly that.
    """
    from app.services import journal_log

    return journal_log.summary(session)
