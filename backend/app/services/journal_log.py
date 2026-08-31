"""Store what the brain decided, and compare the two arms afterwards.

`app/brain/journal.py` decides what a decision is and refuses to score one it
cannot; this puts those decisions somewhere they survive a restart, and answers
the one question the whole forward measurement exists for: **did the rule beat
the coin flip on the same bars?**

Two arms in one table. A comparison is then a filter rather than a join between
two shapes that drift apart, and - more importantly - it is impossible to build
the rule's series while forgetting the control's, which is exactly the mistake
that produced a CONFIRMED on a result with no edge.

Nothing here invents a value. A decision with no probability is stored with
none, because 0.5 is a forecast the system never made and is indistinguishable
afterwards from one it did. An open entry has no outcome rather than a
placeholder outcome. Every count this module returns is a count of things that
actually happened.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.learning import control as control_module
from app.learning import readiness as readiness_module
from app.models.journal import (
    ARM_CONTROL,
    ARM_RULE,
    SOURCE_PUBLIC,
    STRATEGY_INCUMBENT,
    JournalEntry,
)

#: When the forward measurement begins. Entries before it are excluded from the
#: comparison and kept in the table.
#:
#: Everything recorded before this came from code with three bugs in it: the
#: cross-section's instant was the newest bar anywhere, which on a weekend is a
#: crypto bar; two frozen duplicates of live symbols were still being ranked;
#: and every series was read up to *now* rather than up to the instant, so a
#: Friday ranking carried Saturday prices.
#:
#: They are not deleted. They are the record of what the system did while it
#: was being debugged, and a table that quietly loses its own history is worse
#: evidence than one with a stated cut. But they are not measurements of
#: anything, and a series that proves or kills an edge cannot contain them.
#:
#: The date is the Monday the markets reopen after those fixes shipped. Written
#: here rather than passed in, so the window is a fact about the deployment
#: that a reader can check, not an argument somebody chose at reporting time.
MEASUREMENT_STARTS_AT = datetime(2026, 8, 17, 0, 0, tzinfo=UTC)

#: The timeframe the live rule decides on, and so the one the headline
#: measurement is taken over.
#:
#: The forward worker records on every timeframe in `forward_timeframes`, which
#: on this deployment is five of them. Reading them together was wrong twice
#: over: their R distributions are different regimes, and - because an M15 bar
#: and an H1 bar share a timestamp every hour - grouping instants by moment
#: alone merged decisions from different timeframes into one observation and
#: averaged across the join. `journal_entries` grew a `timeframe` column for
#: exactly this and neither reader had used it.
TRADED_TIMEFRAME = "H1"


@dataclass(frozen=True)
class Recorded:
    """What was written, and whether it was new."""

    entry_id: uuid.UUID | None
    arm: str
    new: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id) if self.entry_id else None,
            "arm": self.arm,
            "new": self.new,
        }


def record_decision(
    session: Session,
    *,
    symbol: str,
    decision: str,
    at: datetime,
    arm: str = ARM_RULE,
    price_source: str = SOURCE_PUBLIC,
    #: Defaulted so every caller that predates the fast timeframes keeps
    #: writing exactly what it wrote before, rather than silently landing in
    #: an unlabelled bucket.
    timeframe: str = "H1",
    strategy: str = STRATEGY_INCUMBENT,
    account_key: str | None = None,
    probability: float | None = None,
    before: dict[str, Any] | None = None,
    during: dict[str, Any] | None = None,
) -> Recorded:
    """Write one decision. Idempotent on (symbol, bar, arm).

    The loop republishes the same decision whenever one cycle overlaps the
    previous, and a duplicated entry inflates the very sample the measurement
    rests on - so the constraint decides, not the caller's care.
    """
    moment = at.astimezone(UTC)
    existing = session.scalar(
        select(JournalEntry).where(
            JournalEntry.symbol == symbol,
            JournalEntry.opened_at == moment,
            JournalEntry.arm == arm,
            JournalEntry.price_source == price_source,
            # Part of the identity, matching the unique key. Without it the
            # lookup finds the hourly entry at a shared timestamp and reports
            # the one-minute decision as an already-recorded duplicate.
            JournalEntry.timeframe == timeframe,
            # Two brains disagreeing about one bar are two rows, and the
            # lookup has to see it that way or the second brain's decision
            # reads as an already-recorded duplicate of the first's.
            JournalEntry.strategy == strategy,
        )
    )
    if existing is not None:
        return Recorded(entry_id=existing.id, arm=arm, new=False)

    entry = JournalEntry(
        symbol=symbol,
        decision=decision,
        account_key=account_key,
        opened_at=moment,
        probability=probability,
        arm=arm,
        price_source=price_source,
        timeframe=timeframe,
        strategy=strategy,
        before=before or {},
        during=during or {},
    )
    session.add(entry)
    session.flush()
    return Recorded(entry_id=entry.id, arm=arm, new=True)


def record_with_control(
    session: Session,
    *,
    symbol: str,
    decision: str,
    at: datetime,
    price: float,
    stop_distance: float,
    price_source: str = SOURCE_PUBLIC,
    timeframe: str = "H1",
    strategy: str = STRATEGY_INCUMBENT,
    account_key: str | None = None,
    probability: float | None = None,
    before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the decision and its control together, or neither.

    One call, because the two must never diverge. A rule series built over
    months beside a control series that was skipped on the days somebody was
    debugging is a comparison with a hole in it, and the hole is invisible
    afterwards.
    """
    rule = record_decision(
        session,
        symbol=symbol,
        decision=decision,
        at=at,
        arm=ARM_RULE,
        price_source=price_source,
        timeframe=timeframe,
        strategy=strategy,
        account_key=account_key,
        probability=probability,
        before=before,
    )

    entry = control_module.entry_for(
        symbol=symbol, at=at, price=price, stop_distance=stop_distance
    )
    if entry is None:
        # The control could not be formed, so the rule's row is marked as
        # having no partner rather than left looking like a matched pair. An
        # unmatched entry silently included in a comparison is a bias.
        return {
            "rule": rule.as_dict(),
            "control": None,
            "reason": (
                "the geometry was unusable, so no control was formed - this "
                "decision is excluded from the comparison rather than counted "
                "against a partner that does not exist"
            ),
        }

    control_row = record_decision(
        session,
        symbol=symbol,
        decision="long" if entry.side > 0 else "short",
        at=at,
        arm=ARM_CONTROL,
        price_source=price_source,
        timeframe=timeframe,
        # The control belongs to its rule's brain: it is the benchmark that
        # brain is measured against, and a control shared across brains would
        # be claimed by whichever recorded first.
        strategy=strategy,
        account_key=account_key,
        # The series is stamped on the control's reasoning as well as the
        # rule's. The control is a decision on a price series too, and one
        # whose row says which series it came from beside a partner whose row
        # does not is a pair that cannot be checked afterwards.
        #
        # The timeframe rides along for the same reason and a sharper one. The
        # control is the only benchmark the rule is measured against, so any
        # grouping applied to one has to reach the other: group the rule by
        # timeframe while its control carries none and every bucket compares
        # against an empty set - which does not read as an error, it reads as
        # a rule with no control, and the honest-looking answer is silence.
        before={
            **entry.as_dict(),
            "price_source": price_source,
            **(
                {"timeframe": (before or {}).get("timeframe")}
                if (before or {}).get("timeframe")
                else {}
            ),
        },
    )
    return {"rule": rule.as_dict(), "control": control_row.as_dict()}


def close(
    session: Session,
    entry_id: uuid.UUID,
    *,
    outcome: str,
    r_multiple: float | None = None,
    after: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> bool:
    """Resolve one entry. Returns whether it changed anything.

    An entry already closed is left alone rather than overwritten. A late
    duplicate resolution would rewrite a result that has already been counted.
    """
    entry = session.get(JournalEntry, entry_id)
    if entry is None or entry.closed_at is not None:
        return False

    entry.closed_at = (at or datetime.now(UTC)).astimezone(UTC)
    entry.outcome = outcome
    entry.r_multiple = r_multiple
    entry.after = after or {}
    session.flush()
    return True


def comparison(
    session: Session,
    *,
    since: datetime | None = None,
    price_source: str = SOURCE_PUBLIC,
    timeframe: str = TRADED_TIMEFRAME,
) -> control_module.Comparison:
    """The rule against the control, over resolved entries only.

    Open entries are excluded from both arms. Counting an open position as a
    loss because it has not closed yet would make every measurement pessimistic
    in exactly the periods the system was most active.

    `since` defaults to `MEASUREMENT_STARTS_AT` rather than to the beginning of
    the table. Everything before that was recorded by code with three known
    bugs in it, and a comparison that silently included them would be a
    comparison of the debugging period.
    """
    if since is None:
        since = MEASUREMENT_STARTS_AT

    def tally(arm: str) -> tuple[int, int]:
        query = select(
            func.count().filter(JournalEntry.r_multiple > 0),
            func.count().filter(JournalEntry.r_multiple <= 0),
        ).where(
            JournalEntry.arm == arm,
            JournalEntry.price_source == price_source,
            JournalEntry.timeframe == timeframe,
            JournalEntry.closed_at.is_not(None),
            JournalEntry.r_multiple.is_not(None),
        )
        if since is not None:
            query = query.where(JournalEntry.opened_at >= since)
        wins, losses = session.execute(query).one()
        return int(wins or 0), int(losses or 0)

    rule_wins, rule_losses = tally(ARM_RULE)
    control_wins, control_losses = tally(ARM_CONTROL)

    return control_module.Comparison(
        rule_wins=rule_wins,
        rule_losses=rule_losses,
        control_wins=control_wins,
        control_losses=control_losses,
    )


def paired_comparison(
    session: Session,
    *,
    since: datetime | None = None,
    price_source: str = SOURCE_PUBLIC,
    timeframe: str = TRADED_TIMEFRAME,
) -> control_module.PairedComparison:
    """The rule against its own control, bar by bar, then averaged per instant.

    `comparison` above tallies each arm separately, which is the weaker of the
    two readings available here and the one that disagrees with how the
    registered claim was measured. Both arms are written in one call on the
    same symbol and bar, so the pairing exists in the table and only the query
    had to be taught to use it.

    Only pairs where both arms closed are counted. A resolved rule entry whose
    control is still open is not evidence about the difference between them.
    """
    if since is None:
        since = MEASUREMENT_STARTS_AT

    query = select(
        JournalEntry.opened_at,
        JournalEntry.symbol,
        JournalEntry.arm,
        JournalEntry.r_multiple,
    ).where(
        JournalEntry.price_source == price_source,
        JournalEntry.timeframe == timeframe,
        JournalEntry.closed_at.is_not(None),
        JournalEntry.r_multiple.is_not(None),
        JournalEntry.arm.in_((ARM_RULE, ARM_CONTROL)),
    )
    if since is not None:
        query = query.where(JournalEntry.opened_at >= since)

    # (instant, symbol) -> {arm: R}. The symbol is part of the key because two
    # instruments ranked on the same bar are two decisions, not one.
    legs: dict[tuple[datetime, str], dict[str, float]] = {}
    for opened_at, symbol, arm, r_multiple in session.execute(query):
        legs.setdefault((opened_at, symbol), {})[str(arm)] = float(r_multiple)

    by_instant: dict[datetime, list[float]] = {}
    pairs = 0
    for (opened_at, _symbol), arms in legs.items():
        if ARM_RULE not in arms or ARM_CONTROL not in arms:
            continue
        pairs += 1
        by_instant.setdefault(opened_at, []).append(arms[ARM_RULE] - arms[ARM_CONTROL])

    differences = tuple(
        sum(values) / len(values) for _instant, values in sorted(by_instant.items())
    )
    return control_module.PairedComparison(differences=differences, pairs=pairs)


def _timeframe_breakdown(session: Session) -> dict[str, Any]:
    """Resolved instants per timeframe per series, so the headline's scope is
    visible beside it rather than implied by a constant."""
    rows = session.execute(
        select(
            JournalEntry.timeframe,
            JournalEntry.price_source,
            func.count(func.distinct(JournalEntry.opened_at)),
        )
        .where(
            JournalEntry.arm == ARM_RULE,
            JournalEntry.closed_at.is_not(None),
            JournalEntry.r_multiple.is_not(None),
            JournalEntry.opened_at >= MEASUREMENT_STARTS_AT,
        )
        .group_by(JournalEntry.timeframe, JournalEntry.price_source)
    ).all()
    out: dict[str, Any] = {}
    for tf, src, count in rows:
        out.setdefault(str(tf), {})[str(src)] = int(count or 0)
    return out


def paired_by_timeframe(
    session: Session, *, price_source: str = SOURCE_PUBLIC
) -> dict[str, Any]:
    """Every timeframe read separately, each beside the bar it has to clear.

    The bar is not the same for all of them and pretending otherwise is how
    today's mistake was made. `TRADED_TIMEFRAME` is the one the live rule
    decides on and was named before any of this data existed, so it is a
    single pre-registered question and 1.96 is its threshold. The others are
    looks taken because the data happened to be there, and four extra looks
    at noise produce a t of 2 often enough to matter - so they carry a
    Bonferroni bar widened by how many of them there are.

    Published per timeframe rather than as one verdict because the pooled
    reading hid a negative H1 behind three positive fast series, and a reader
    given one number could not have seen it.
    """
    from app.learning import scorecard as scorecard_module

    present = sorted(
        tf
        for tf in (
            session.execute(
                select(JournalEntry.timeframe)
                .where(
                    JournalEntry.arm == ARM_RULE,
                    JournalEntry.price_source == price_source,
                    JournalEntry.closed_at.is_not(None),
                    JournalEntry.opened_at >= MEASUREMENT_STARTS_AT,
                )
                .distinct()
            )
            .scalars()
            .all()
        )
    )
    exploratory = [tf for tf in present if tf != TRADED_TIMEFRAME]
    widened = scorecard_module._bonferroni_z(max(1, len(exploratory)))

    out: dict[str, Any] = {}
    for tf in present:
        paired = paired_comparison(session, price_source=price_source, timeframe=tf)
        pre_registered = tf == TRADED_TIMEFRAME
        required = 1.96 if pre_registered else widened
        entry = _paired_dict(paired)
        entry["required_t"] = round(required, 3)
        entry["pre_registered"] = pre_registered
        entry["verdict"] = paired.verdict(required=required)
        out[str(tf)] = entry
    return out


def _paired_dict(paired: control_module.PairedComparison) -> dict[str, Any]:
    """Rounded for publication, with the two counts kept apart.

    `instants` is the sample the t-statistic actually rests on; `pairs` is how
    many decisions went into it. They differ whenever more than one symbol is
    ranked on a bar, and a reader shown only the larger would think the
    measurement is better powered than it is.
    """
    mean = paired.mean_difference
    t = paired.t_statistic
    return {
        "instants": paired.instants,
        "pairs": paired.pairs,
        "mean_difference_r": round(mean, 5) if mean is not None else None,
        "t_statistic": round(t, 3) if t is not None else None,
        "required_t": 1.96,
        "verdict": paired.verdict(),
    }


def summary(session: Session) -> dict[str, Any]:
    """What the journal holds, on both price series.

    Two comparisons, because the two answer different questions. The public
    feed carries the universe the rule was tested on and is a market nobody can
    trade in; the broker carries the prices that actually fill. The gap between
    the two results is the measurement neither gives alone: how much of the edge
    the difference between quoted and filled prices eats.
    """
    from app.models.journal import SOURCE_BROKER

    totals = session.execute(
        select(
            JournalEntry.price_source,
            JournalEntry.arm,
            func.count(JournalEntry.id),
            func.count(JournalEntry.closed_at),
            func.min(JournalEntry.opened_at),
            func.max(JournalEntry.opened_at),
        ).group_by(JournalEntry.price_source, JournalEntry.arm)
    ).all()

    by_arm: dict[str, dict[str, Any]] = {}
    for source, arm, recorded, resolved, first, last in totals:
        by_arm.setdefault(source, {})[arm] = {
            "recorded": int(recorded or 0),
            "resolved": int(resolved or 0),
            # Stated rather than left to subtraction. "40 recorded, 12
            # resolved" reads as two unrelated numbers until the third is
            # spelled out.
            "still_open": int(recorded or 0) - int(resolved or 0),
            "first_at": first.isoformat() if first else None,
            "last_at": last.isoformat() if last else None,
        }

    public = comparison(session, price_source=SOURCE_PUBLIC)
    broker = comparison(session, price_source=SOURCE_BROKER)
    # Both readings are published, never one. The unpaired figures answer
    # "do these two hit rates differ"; the paired ones answer the question
    # the registered claim was measured against, on the same rows. Showing
    # only the stronger would flatter the rule, and showing only the weaker
    # would compare this forward window to a backtest computed differently.
    public_paired = paired_comparison(session, price_source=SOURCE_PUBLIC)
    broker_paired = paired_comparison(session, price_source=SOURCE_BROKER)

    slippage = None
    if public.edge is not None and broker.edge is not None:
        # What the gap between quoted and filled prices costs. Positive means
        # the edge survived the move to real prices; negative means it did not.
        slippage = round(broker.edge - public.edge, 4)

    return {
        "arms": by_arm,
        "comparison": public.as_dict(),
        "by_source": {
            SOURCE_PUBLIC: public.as_dict(),
            SOURCE_BROKER: broker.as_dict(),
        },
        "paired_by_source": {
            SOURCE_PUBLIC: _paired_dict(public_paired),
            SOURCE_BROKER: _paired_dict(broker_paired),
        },
        "by_timeframe": _timeframe_breakdown(session),
        "paired_by_timeframe": paired_by_timeframe(session),
        "why_a_wider_bar": (
            "H1 is the timeframe the live rule decides on and was named "
            "before this data existed, so it is one pre-registered question "
            "and its bar is 1.96. The faster series are looks taken because "
            "the data was there; four extra looks at noise turn up a t near "
            "two often enough to matter, so theirs is widened for how many "
            "were taken. Reading an exploratory t against the pre-registered "
            "bar is how a pooled positive number came to be reported from a "
            "series whose traded timeframe was negative"
        ),
        "why_one_timeframe": (
            "the worker records on every timeframe in `forward_timeframes`, "
            "and the headline is H1 alone because that is the one the live "
            "rule decides on. Read together they are different regimes "
            "averaged into one number, and an M15 bar shares a timestamp with "
            "an H1 bar every hour - so grouping by moment alone merged two "
            "decisions from two timeframes into one observation"
        ),
        "why_paired": (
            "both arms are written in one call on the same symbol and bar, so "
            "the market's own move is common to them and subtracting it "
            "removes variance the unpaired test carries as noise. It is also "
            "the statistic the registered claim was measured with, and a "
            "forward result computed the other way compares methods as much "
            "as periods"
        ),
        "edge_lost_to_real_prices": slippage,
        "why_two_series": (
            "the broker's prices and the public feed's differ by 33-39% of the "
            "stop distance on every major pair, measured over 490 shared hourly "
            "bars, and the edge being looked for is 0.021 R. The public series "
            "has the universe the rule was tested on and is a market nobody can "
            "trade in; the broker series has the prices that actually fill"
        ),
        # Stated, so nobody has to guess which entries the numbers above cover.
        "measurement_starts_at": MEASUREMENT_STARTS_AT.isoformat(),
        "why_it_starts_there": (
            "everything recorded before that came from code with three bugs: "
            "the cross-section's instant was the newest bar anywhere, which on "
            "a weekend is a crypto bar; two frozen duplicates of live symbols "
            "were still ranked; and every series was read up to now rather than "
            "up to the instant, so a Friday ranking carried Saturday prices. "
            "Those entries are kept and excluded"
        ),
        "note": (
            "the comparison counts resolved entries only. An open position "
            "counted as a loss would make every measurement pessimistic in "
            "exactly the periods the system was most active"
        ),
    }


#: How long the measurement must have been running before a rate is published.
#:
#: Three instants in the first two hours is 180 a week, and a projected date
#: built on it would be confident and meaningless. A week is the shortest
#: window that contains a weekend - the thing that most changes the rate.
MIN_OBSERVATION = timedelta(days=7)

#: Instants before the forward spread is used instead of the historical one.
#:
#: A spread from a handful of instants is itself noisy, and the sample size
#: depends on its square - so an early low reading would shorten the projected
#: wait on nothing, in the flattering direction. Thirty is where the sample
#: standard deviation stops swinging wildly, and below it the projection keeps
#: saying openly that it is using the historical figure.
MIN_INSTANTS_FOR_SPREAD = 30



def readiness_of(
    session: Session,
    *,
    price_source: str = SOURCE_PUBLIC,
    timeframe: str = TRADED_TIMEFRAME,
    now: datetime | None = None,
) -> readiness_module.Readiness:
    """How far this series is from being able to answer the question.

    Counts instants, not decisions. The rule takes both tails of one
    cross-section at one moment, so the eight rows written at one instant are
    one piece of evidence about one market move. Counting rows would report
    eight times the progress that exists, and the historical measurement has
    already shown what that does to a significance figure.
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)

    instants, decisions = session.execute(
        select(
            func.count(func.distinct(JournalEntry.opened_at)),
            func.count(JournalEntry.id),
        ).where(
            JournalEntry.arm == ARM_RULE,
            JournalEntry.price_source == price_source,
            # One timeframe, for the reason `TRADED_TIMEFRAME` gives: without
            # it this counted an M1 instant and an H1 instant as two draws on
            # the same question, and counted them as one whenever they landed
            # on the same timestamp.
            JournalEntry.timeframe == timeframe,
            JournalEntry.closed_at.is_not(None),
            JournalEntry.r_multiple.is_not(None),
            JournalEntry.opened_at >= MEASUREMENT_STARTS_AT,
        )
    ).one()

    # Measured over the period this series was actually recording, which is
    # not the same as the period since the measurement window opened.
    #
    # `MEASUREMENT_STARTS_AT` is the date bad entries stop being counted; it
    # is not the date recording began. On this deployment the H1 series
    # starts nine days after it, so dividing by the whole window divided a
    # real numerator by an idle denominator and understated the rate several
    # times over - which then travelled straight into the projected date, the
    # one number this function exists to publish.
    first_at = session.execute(
        select(func.min(JournalEntry.opened_at)).where(
            JournalEntry.arm == ARM_RULE,
            JournalEntry.price_source == price_source,
            JournalEntry.timeframe == timeframe,
            JournalEntry.opened_at >= MEASUREMENT_STARTS_AT,
        )
    ).scalar()
    recording_since = max(first_at, MEASUREMENT_STARTS_AT) if first_at else None

    elapsed = moment - recording_since if recording_since else timedelta(0)
    rate: float | None = None
    if elapsed >= MIN_OBSERVATION and instants:
        rate = int(instants) / (elapsed.total_seconds() / 604800.0)

    # Sized against the spread this series actually shows, once there is
    # enough of it to measure one. The projection has always been computed
    # from the historical spread because until the arms were paired there was
    # no forward spread to compute - not because the historical one was
    # thought to be the right number.
    paired = paired_comparison(
        session, price_source=price_source, timeframe=timeframe
    )
    measured_spread: float | None = None
    if paired.instants >= MIN_INSTANTS_FOR_SPREAD:
        measured_spread = paired.observed_spread

    return readiness_module.assess(
        instants_resolved=int(instants or 0),
        decisions_resolved=int(decisions or 0),
        instants_per_week=rate,
        today=moment.date(),
        spread=measured_spread,
        open_requirements=_open_requirements(),
        met_requirements=_met_requirements(),
    )


def _open_requirements() -> tuple[str, ...]:
    """What still stands between the current state and a connected account.

    Read from the edge registry rather than restated here. A second copy of
    these conditions is a second thing to update, and the one nobody updates
    becomes a claim the system makes about itself that is no longer true.
    """
    from app.learning import edge as edge_module

    if edge_module.PROVEN:
        return ()

    open_now: list[str] = []
    for claim in edge_module.PENDING_FORWARD:
        verdict = edge_module.assess(claim.evidence, pre_registered=claim.pre_registered)
        open_now.extend(verdict.failures)
    return tuple(open_now)


def _met_requirements() -> tuple[str, ...]:
    from app.learning import edge as edge_module

    met: list[str] = []
    for claim in edge_module.PENDING_FORWARD:
        verdict = edge_module.assess(claim.evidence, pre_registered=claim.pre_registered)
        met.extend(verdict.passes)
    return tuple(met)
