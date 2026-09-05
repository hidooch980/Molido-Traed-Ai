"""What gates training eligibility, and what merely costs score.

`recheck_findings` gave the quality gate an exit, and 38 of 150 datasets
still could not reach it: they were held by findings that can never close.
Twenty-seven of those were `duplicate_bar` alone.

`duplicate_bar` says a provider's *batch* carried one timestamp twice.
Storage keys bars by revision and de-duplicates, so the rows a reader is
served are correct either way - the finding is about the provider's transport
and says nothing about the data anybody reads. It is also the one finding
that can never be re-checked, because the batch is gone. As a gate it was a
check that could not be false and could not be closed, which is not a check.

So severity and blocking are now two questions instead of one read off the
other, and these tests hold that line in both directions: the transport
observation stops gating, and everything that is genuinely about the stored
data keeps gating.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.enums import DataQualityIssue
from app.services import data_quality
from app.services.data_quality import BLOCKING_ISSUES, RECHECKABLE, _is_blocking

AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class TestWhatBlocks:
    def test_duplicate_bar_costs_score_but_does_not_block(self):
        """The whole point. It is still an ERROR and still carries weight in
        the penalty - worth seeing, not worth blocking on."""
        assert DataQualityIssue.DUPLICATE_BAR not in BLOCKING_ISSUES

    def test_everything_about_the_stored_bars_still_blocks(self):
        """A bar whose high is below its low, a non-positive price, a
        timestamp out of order: each says the row itself is wrong."""
        for issue in (
            DataQualityIssue.INVALID_OHLC_RELATION,
            DataQualityIssue.NON_POSITIVE_PRICE,
            DataQualityIssue.INVALID_TIMESTAMP,
            DataQualityIssue.NON_MONOTONIC_TIMESTAMP,
        ):
            assert issue in BLOCKING_ISSUES, issue

    def test_two_feeds_disagreeing_still_blocks(self):
        """Which feed to believe is the operator's call, but a dataset whose
        price is contested is not one to train on."""
        assert DataQualityIssue.PROVIDER_CONFLICT in BLOCKING_ISSUES

    def test_a_silent_feed_still_blocks(self):
        assert DataQualityIssue.STALE_DATA in BLOCKING_ISSUES

    def test_an_unknown_issue_blocks(self):
        """A detector added without a decision here is a property nobody has
        judged, and the safe reading of 'nobody has judged it' is not 'it is
        fine'."""
        assert _is_blocking("something_nobody_has_classified") is True

    def test_every_blocking_issue_is_a_real_one(self):
        """A typo in the set would silently stop gating whatever it meant."""
        for issue in BLOCKING_ISSUES:
            assert DataQualityIssue(issue.value) is issue


class TestABlockedGateCanBeReopened:
    """Every issue that blocks must be answerable, or the gate has no exit
    again - which is the defect this whole line of work started from."""

    def test_each_blocking_issue_can_be_rechecked_or_is_named_as_permanent(self):
        # `invalid_timestamp` and `non_monotonic_timestamp` are excluded from
        # the re-check for a stated reason: stored timestamps are
        # timezone-aware and ordered by construction, so the check could only
        # ever pass, and a check that cannot fail is not evidence.
        permanent_by_construction = {
            DataQualityIssue.INVALID_TIMESTAMP,
            DataQualityIssue.NON_MONOTONIC_TIMESTAMP,
        }
        answerable = RECHECKABLE | {DataQualityIssue.STALE_DATA}

        unanswerable = BLOCKING_ISSUES - answerable - permanent_by_construction

        assert not unanswerable, (
            "these block the gate and nothing can ever close them: "
            f"{sorted(i.value for i in unanswerable)}"
        )


class TestTheConflictRecheck:
    """`compare_providers` already read bars back out of storage, so the
    question 'do these feeds still disagree' was always answerable - it was
    excluded on the assumption it needed more than the window it names.

    Run against real stored bars rather than a patched detector: a test that
    mocks the thing it is testing asserts its own mock.
    """

    @staticmethod
    def two_feeds(session, *, close_a, close_b, revision_b=1):
        from app.core.enums import Timeframe
        from app.models.instruments import Instrument, Provider
        from app.models.market_data import Bar

        one = Provider(code="feed-a", name="A")
        two = Provider(code="feed-b", name="B")
        instrument = Instrument(
            symbol="EURUSD",
            asset_class="forex",
            base_currency="EUR",
            quote_currency="USD",
            timezone="UTC",
        )
        session.add_all([one, two, instrument])
        session.flush()

        def bar(provider, close, revision):
            session.add(
                Bar(
                    instrument_id=instrument.id,
                    provider_id=provider.id,
                    timeframe=Timeframe.H1,
                    event_time=AT,
                    revision=revision,
                    open=close,
                    high=close,
                    low=close,
                    close=close,
                    volume=1.0,
                    ingested_at=AT,
                )
            )

        bar(one, close_a, 1)
        bar(two, close_b, revision_b)
        session.flush()
        return instrument

    def test_feeds_that_still_disagree_keep_the_finding_open(self, session):
        from app.core.enums import Timeframe

        instrument = self.two_feeds(session, close_a=1.1000, close_b=1.2000)

        assert (
            data_quality._conflicts_at(session, instrument.id, Timeframe.H1, AT) is True
        )

    def test_a_feed_that_corrected_itself_closes_it(self, session):
        """The disagreeing feed filed a newer revision that agrees. Only the
        newest revision per provider is compared, because that is the bar a
        reader is served."""
        from app.core.enums import Timeframe
        from app.models.instruments import Provider
        from app.models.market_data import Bar

        instrument = self.two_feeds(session, close_a=1.1000, close_b=1.2000)
        two = session.query(Provider).filter(Provider.code == "feed-b").one()
        session.add(
            Bar(
                instrument_id=instrument.id,
                provider_id=two.id,
                timeframe=Timeframe.H1,
                event_time=AT,
                revision=2,
                open=1.1000,
                high=1.1000,
                low=1.1000,
                close=1.1000,
                volume=1.0,
                ingested_at=AT,
            )
        )
        session.flush()

        assert (
            data_quality._conflicts_at(session, instrument.id, Timeframe.H1, AT)
            is False
        )

    def test_one_feed_cannot_disagree_with_itself(self, session):
        """None rather than False. A conflict that vanished because a feed
        was deleted has not been resolved, it has been forgotten, and the two
        need to look different to whoever reads the table."""
        from app.core.enums import Timeframe
        from app.models.instruments import Instrument, Provider
        from app.models.market_data import Bar

        only = Provider(code="feed-a", name="A")
        instrument = Instrument(
            symbol="EURUSD",
            asset_class="forex",
            base_currency="EUR",
            quote_currency="USD",
            timezone="UTC",
        )
        session.add_all([only, instrument])
        session.flush()
        session.add(
            Bar(
                instrument_id=instrument.id,
                provider_id=only.id,
                timeframe=Timeframe.H1,
                event_time=AT,
                revision=1,
                open=1.1,
                high=1.1,
                low=1.1,
                close=1.1,
                volume=1.0,
                ingested_at=AT,
            )
        )
        session.flush()

        assert (
            data_quality._conflicts_at(session, instrument.id, Timeframe.H1, AT) is None
        )

    def test_recheck_closes_a_resolved_conflict_end_to_end(self, session):
        """Through `recheck_findings`, which is what actually runs."""
        from app.core.enums import DataQualityIssue as Issue
        from app.core.enums import Severity as Sev
        from app.core.enums import Timeframe
        from app.models.ingestion import DataQualityFinding
        from app.models.instruments import Provider

        instrument = self.two_feeds(session, close_a=1.1000, close_b=1.1000)
        one = session.query(Provider).filter(Provider.code == "feed-a").one()
        session.add(
            DataQualityFinding(
                instrument_id=instrument.id,
                provider_id=one.id,
                timeframe=Timeframe.H1,
                issue=Issue.PROVIDER_CONFLICT,
                severity=Sev.ERROR,
                window_start=AT,
                window_end=AT,
                detected_at=AT,
                affected_rows=1,
            )
        )
        session.flush()

        closed = data_quality.recheck_findings(
            session,
            instrument_id=instrument.id,
            provider_id=one.id,
            timeframe=Timeframe.H1,
        )

        assert closed == 1


class TestSeverityIsStillRecorded:
    def test_the_weights_are_untouched(self):
        """Separating the gate from the severity must not quietly re-weight
        the quality score - that is a different number with different
        consumers."""
        import inspect

        source = inspect.getsource(data_quality._persisted_finding_stats)

        assert "Severity.ERROR: 4.0" in source
        assert "Severity.CRITICAL: 20.0" in source

    def test_a_non_blocking_finding_still_costs_penalty(self):
        import inspect

        source = inspect.getsource(data_quality._persisted_finding_stats)
        penalty_line = next(
            line for line in source.splitlines() if "penalty +=" in line
        )

        # The penalty is charged before the blocking question is asked, so a
        # duplicate_bar still lowers the score it always lowered.
        assert "weights[severity]" in penalty_line
        assert "_is_blocking" not in penalty_line


class TestSeverityUnchangedForDuplicates:
    def test_duplicate_bar_is_still_reported_as_an_error(self):
        """The severity recorded is what was believed at the time and stays
        that way - 3,477 stored rows are not rewritten. Only the gate's
        reading of them changed."""
        import inspect

        source = inspect.getsource(data_quality)
        block = source[source.index("DataQualityIssue.DUPLICATE_BAR") :][:200]

        assert "Severity.ERROR" in block
