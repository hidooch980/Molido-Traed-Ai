"""Why a position is the size it is, written on the order.

A gold position closed at -$3,730.76 and the account's other ten positions
were each a twenty-fifth of the configured risk. Both questions - why so
large, and why so small - had to be answered by re-deriving the whole chain
from source against a live account, because the order record held lots, a
fill and a ticket, and nothing about the decision that produced them.

The chain on 2026-09-03, on the 196,000 account, was:

    configured                 0.75%   $1,476
    daily loss -2.17 R          x0.5
    no calibrated probability   x0.5
    no dataset has passed yet   x0.5
                              = 12.5%  $184.50
    conviction                 x0.32
                                       ~$59  = 0.04 R

Every one of those steps is deliberate and documented in the code that
applies it. None of them was visible in the row.
"""

from __future__ import annotations

from app.brain import risk as risk_brain


class TestTheReductionNamesItsRealCause:
    def test_an_unevaluated_dataset_does_not_report_as_a_failed_one(self):
        """`training_eligible` defaults to False meaning *not established*,
        and the cycle never sets it, so this fires on every order of every
        day. "dataset failed the quality gate" sent a reader looking for the
        dataset that failed and the gate that failed it. Neither exists."""
        decision = risk_brain.authorise(
            requested_risk_r=0.0075,
            # The 196,000 account as it stood on 2026-09-03, with the
            # position count lowered so the 10-position ceiling - a hard
            # limit that exits before any reduction is considered - does not
            # hide the reductions this test is about.
            account=risk_brain.AccountState(
                equity=196_788.0,
                balance=197_035.0,
                peak_equity=200_701.0,
                daily_pnl_r=-2.17,
                open_positions=2,
                used_margin=975.0,
                free_margin=195_700.0,
            ),
            health=risk_brain.DataHealth(data_age_bars=0.0),
        )

        joined = " | ".join(decision.reductions)
        assert "no dataset has passed the quality gate yet" in joined
        assert "failed the quality gate" not in joined

    def test_the_pessimistic_defaults_cost_a_quarter_of_the_size(self):
        """Two halvings, both permanent until the deployment earns its way
        out of them. This is the brain's considered answer to being unsure,
        not a defect - but it is four times, and it should be legible."""
        # Flat and unbruised, so only the two model-uncertainty reductions
        # can fire and the factor of four is theirs alone.
        account = risk_brain.AccountState(
            equity=100_000.0,
            balance=100_000.0,
            peak_equity=100_000.0,
            daily_pnl_r=0.0,
            open_positions=0,
            used_margin=0.0,
            free_margin=100_000.0,
        )

        unsure = risk_brain.authorise(
            requested_risk_r=0.0075,
            account=account,
            health=risk_brain.DataHealth(data_age_bars=0.0),
        )
        established = risk_brain.authorise(
            requested_risk_r=0.0075,
            account=account,
            health=risk_brain.DataHealth(
                data_age_bars=0.0, calibrated=True, training_eligible=True
            ),
        )

        assert established.permitted_risk_r == 4 * unsure.permitted_risk_r


class TestTheOrderRecordsWhy:
    def test_the_sizing_chain_is_written_onto_the_order(self):
        """Not a behaviour test - a presence test. The question this answers
        is asked of a row in the database months later, by somebody who
        cannot re-run the cycle that produced it."""
        import inspect

        from app.workers import autotrade

        source = inspect.getsource(autotrade)
        block = source[source.index('"sizing": {') :]

        for field in (
            "configured_risk_r",
            "after_risk_brain_r",
            "after_portfolio_r",
            "after_conviction_r",
            "conviction_multiplier",
            "reductions",
            "money_at_risk",
        ):
            assert field in block[:900], f"the order record does not carry {field}"

    def test_it_records_the_brains_own_words_rather_than_a_summary(self):
        """A number without its reason is a number somebody will re-derive."""
        import inspect

        from app.workers import autotrade

        source = inspect.getsource(autotrade)

        assert "list(verdict.reductions or [])" in source
