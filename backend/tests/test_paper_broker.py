"""The broker that answers like the real one and sends nothing.

The mandatory gate before a demo account is a full run on live data with no
money at risk. The mode existed and `autotrade` refused on it, so paper meant
"do nothing" rather than "do everything except send" - and everything except
send is where the work is.

These are about the two ways a paper adapter stops being useful: by not
looking enough like the real one to exercise the path, and by looking so much
like it that its fills get counted as real.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.execution.broker import BrokerAdapter
from app.execution.contracts import (
    Approval,
    OrderIntent,
    OrderSide,
    OrderState,
    OrderType,
)
from app.execution.paper_broker import PAPER_MARKER, LivePaperBroker

AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def intent(**over) -> OrderIntent:
    base = dict(
        symbol="EURUSD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        risk_r=0.002,
        entry=1.1580,
        stop=1.1530,
        target=1.1630,
        account_id="68345601",
        approvals=(
            Approval(source="strategy", approved=True, detail="test", at=AT),
            Approval(source="risk", approved=True, detail="test", at=AT),
        ),
        authorised_at=AT,
        metadata={"lots": 0.05},
    )
    base.update(over)
    return OrderIntent(**base)


class TestItAnswersLikeTheRealAdapter:
    """A paper mode that stops before the sizing and the gates exercises none
    of them, and the first time any of it runs is on real money."""

    def test_a_sized_order_fills(self):
        report = LivePaperBroker().submit(intent())

        assert report.state is OrderState.FILLED
        assert report.filled_quantity == 0.05

    def test_it_fills_at_the_requested_price(self):
        report = LivePaperBroker().submit(
            intent(entry=1.2345, stop=1.2295, target=1.2395)
        )

        assert report.average_price == 1.2345

    def test_a_zero_lot_order_is_refused_as_the_real_one_refuses_it(self):
        """A request that cannot succeed should not look like one that did."""
        report = LivePaperBroker().submit(intent(metadata={"lots": 0.0}))

        assert report.state is OrderState.REJECTED
        assert "no lots" in (report.reason or "")

    def test_it_does_not_return_unknown(self):
        """UNKNOWN would exercise the retry path every cycle and teach the
        journal that every order times out. The point is to exercise the path
        a working broker produces."""
        report = LivePaperBroker().submit(intent())

        assert report.state is not OrderState.UNKNOWN

    def test_the_client_order_id_is_the_intent_id(self):
        one = intent()

        assert LivePaperBroker().submit(one).client_order_id == str(one.intent_id)


class TestAPaperFillCannotPassForAReal:
    """A paper fill counted as real would land in realised P&L, in the hit
    rate, and in the evidence the edge registry is waiting on."""

    def test_the_ticket_says_what_it_is_on_sight(self):
        report = LivePaperBroker().submit(intent())

        assert report.broker_order_id.startswith(PAPER_MARKER)

    def test_the_raw_payload_names_the_broker(self):
        assert LivePaperBroker().submit(intent()).raw["broker"] == PAPER_MARKER

    def test_the_note_admits_the_overstatement(self):
        """Filling at the requested price overstates the result by exactly the
        spread, and saying so beats inventing a slippage number that would
        look measured."""
        note = LivePaperBroker().submit(intent()).raw["note"]

        assert "overstates" in note

    def test_two_tickets_do_not_collide(self):
        broker = LivePaperBroker()

        first = broker.submit(intent())
        second = broker.submit(intent(symbol="GBPUSD"))

        assert first.broker_order_id != second.broker_order_id


class TestItRemembersWithoutPersisting:
    """Deliberately in memory. A paper fill in the positions file would be
    indistinguishable from a real one to everything that reads it."""

    def test_it_keeps_what_it_saw_in_order(self):
        broker = LivePaperBroker()
        broker.submit(intent(symbol="EURUSD"))
        broker.submit(intent(symbol="GBPUSD"))

        assert [i.symbol for i in broker.submitted] == ["EURUSD", "GBPUSD"]

    def test_a_rejected_order_is_still_remembered(self):
        """It was still a decision the cycle made."""
        broker = LivePaperBroker()
        broker.submit(intent(metadata={"lots": 0.0}))

        assert len(broker.submitted) == 1

    def test_the_summary_counts_and_names(self):
        broker = LivePaperBroker()
        broker.submit(intent(symbol="EURUSD"))
        broker.submit(intent(symbol="GBPUSD"))

        assert broker.as_dict() == {
            "broker": PAPER_MARKER,
            "submitted": 2,
            "symbols": ["EURUSD", "GBPUSD"],
        }

    def test_a_fresh_broker_remembers_nothing(self):
        assert LivePaperBroker().submitted == []


class TestItIsAWholeAdapter:
    """`submit` alone is not the boundary. `BrokerAdapter` asks for four
    methods and calls `reconcile` the one that is not optional: an execution
    layer with no way to ask "what do you actually have?" cannot recover from
    its own uncertainty. An adapter that satisfies only part of the protocol
    types as the protocol nowhere, which is how this one ended up passed to a
    parameter annotated for a different class entirely."""

    def test_it_satisfies_the_protocol(self):
        adapter: BrokerAdapter = LivePaperBroker()

        assert adapter.name == PAPER_MARKER

    def test_status_returns_what_submit_answered(self):
        broker = LivePaperBroker()
        one = intent()

        report = broker.submit(one)

        assert broker.status(str(one.intent_id)) is report

    def test_status_of_an_unknown_order_is_unknown_not_rejected(self):
        """Not having a record is not evidence that nothing happened. Here it
        genuinely is, but an adapter whose UNKNOWN means something different
        from every other adapter's is worse than one that never says it."""
        report = LivePaperBroker().status("never-sent")

        assert report.state is OrderState.UNKNOWN
        assert "may never have arrived" in (report.reason or "")

    def test_cancelling_a_fill_returns_the_fill_not_a_cancellation(self):
        """Every report here is terminal on the instant it is made. CANCELLED
        would be a state that never happened going into the journal."""
        broker = LivePaperBroker()
        one = intent()
        filled = broker.submit(one)

        assert broker.cancel(str(one.intent_id)) is filled
        assert filled.state is OrderState.FILLED

    def test_cancelling_an_unknown_order_is_unknown(self):
        assert LivePaperBroker().cancel("never-sent").state is OrderState.UNKNOWN

    def test_reconcile_answers_per_account(self):
        broker = LivePaperBroker()
        broker.submit(intent(account_id="68345601"))
        broker.submit(intent(symbol="GBPUSD", account_id="99999999"))

        mine = broker.reconcile("68345601")

        assert len(mine) == 1
        assert mine[0].filled_quantity == 0.05

    def test_reconcile_knows_nothing_about_an_account_it_never_saw(self):
        assert LivePaperBroker().reconcile("68345601") == []
