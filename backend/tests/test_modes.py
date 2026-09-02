"""Which of three things an order is, named from the adapter that gets it."""

from __future__ import annotations

from app.execution import modes
from app.execution.metatrader_broker import MetaTraderBroker
from app.execution.paper_broker import LivePaperBroker


class TestClassification:
    def test_a_paper_adapter_is_simulated_and_labelled(self):
        report = modes.classify(LivePaperBroker(), dry_run=False)

        assert report.mode is modes.ExecutionMode.SIMULATED
        assert report.fills_labelled is True
        assert report.consistent is True

    def test_a_real_adapter_with_dry_run_is_dry_run(self):
        report = modes.classify(MetaTraderBroker(), dry_run=True)

        assert report.mode is modes.ExecutionMode.DRY_RUN
        assert report.consistent is True

    def test_a_real_adapter_without_dry_run_is_live(self):
        report = modes.classify(MetaTraderBroker(), dry_run=False)

        assert report.mode is modes.ExecutionMode.LIVE
        assert report.simulated is False

    def test_an_unlabelled_simulated_adapter_is_the_inconsistency(self):
        class Quiet:
            name = "paper"

        report = modes.classify(Quiet(), dry_run=False)

        assert report.simulated
        assert report.fills_labelled is False
        assert report.consistent is False
        assert "does NOT label" in report.reason

    def test_the_dictionary_carries_the_verdict(self):
        payload = modes.classify(LivePaperBroker(), dry_run=False).as_dict()
        assert payload["mode"] == "simulated" and payload["consistent"] is True
