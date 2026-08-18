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

import uuid

from datetime import UTC, datetime

from app.execution.contracts import (
    Approval,
    OrderIntent,
    OrderSide,
    OrderState,
    OrderType,
)
from app.execution.paper_broker import PAPER_MARKER, PaperBroker


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
        report = PaperBroker().submit(intent())

        assert report.state is OrderState.FILLED
        assert report.filled_quantity == 0.05

    def test_it_fills_at_the_requested_price(self):
        report = PaperBroker().submit(
            intent(entry=1.2345, stop=1.2295, target=1.2395)
        )

        assert report.average_price == 1.2345

    def test_a_zero_lot_order_is_refused_as_the_real_one_refuses_it(self):
        """A request that cannot succeed should not look like one that did."""
        report = PaperBroker().submit(intent(metadata={"lots": 0.0}))

        assert report.state is OrderState.REJECTED
        assert "no lots" in (report.reason or "")

    def test_it_does_not_return_unknown(self):
        """UNKNOWN would exercise the retry path every cycle and teach the
        journal that every order times out. The point is to exercise the path
        a working broker produces."""
        report = PaperBroker().submit(intent())

        assert report.state is not OrderState.UNKNOWN

    def test_the_client_order_id_is_the_intent_id(self):
        one = intent()

        assert PaperBroker().submit(one).client_order_id == str(one.intent_id)


class TestAPaperFillCannotPassForAReal:
    """A paper fill counted as real would land in realised P&L, in the hit
    rate, and in the evidence the edge registry is waiting on."""

    def test_the_ticket_says_what_it_is_on_sight(self):
        report = PaperBroker().submit(intent())

        assert report.broker_order_id.startswith(PAPER_MARKER)

    def test_the_raw_payload_names_the_broker(self):
        assert PaperBroker().submit(intent()).raw["broker"] == PAPER_MARKER

    def test_the_note_admits_the_overstatement(self):
        """Filling at the requested price overstates the result by exactly the
        spread, and saying so beats inventing a slippage number that would
        look measured."""
        note = PaperBroker().submit(intent()).raw["note"]

        assert "overstates" in note

    def test_two_tickets_do_not_collide(self):
        broker = PaperBroker()

        first = broker.submit(intent())
        second = broker.submit(intent(symbol="GBPUSD"))

        assert first.broker_order_id != second.broker_order_id


class TestItRemembersWithoutPersisting:
    """Deliberately in memory. A paper fill in the positions file would be
    indistinguishable from a real one to everything that reads it."""

    def test_it_keeps_what_it_saw_in_order(self):
        broker = PaperBroker()
        broker.submit(intent(symbol="EURUSD"))
        broker.submit(intent(symbol="GBPUSD"))

        assert [i.symbol for i in broker.submitted] == ["EURUSD", "GBPUSD"]

    def test_a_rejected_order_is_still_remembered(self):
        """It was still a decision the cycle made."""
        broker = PaperBroker()
        broker.submit(intent(metadata={"lots": 0.0}))

        assert len(broker.submitted) == 1

    def test_the_summary_counts_and_names(self):
        broker = PaperBroker()
        broker.submit(intent(symbol="EURUSD"))
        broker.submit(intent(symbol="GBPUSD"))

        assert broker.as_dict() == {
            "broker": PAPER_MARKER,
            "submitted": 2,
            "symbols": ["EURUSD", "GBPUSD"],
        }

    def test_a_fresh_broker_remembers_nothing(self):
        assert PaperBroker().submitted == []
