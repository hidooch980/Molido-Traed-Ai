"""The weekly scorecard, and whether it reaches a person.

It existed and it went nowhere: `checkpoint.sh --scorecard` had run on cron
three times a week since 2026-09-06, writing to a log on a machine nobody
logs into. The daily digest goes to Telegram; the weekly one - the one that
changes a decision - did not.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.ops import weekly_digest

NOW = datetime(2026, 9, 8, tzinfo=UTC)


def card(strategy, *, effective, trials=None, per_instant=None, verdict="insufficient"):
    return {
        "strategy": strategy,
        "verdict": verdict,
        "effective_trials": effective,
        "trials": trials if trials is not None else effective,
        "trials_per_instant": per_instant,
    }


class TestWhatItSays:
    def test_it_says_there_is_no_edge_rather_than_saying_nothing(self):
        """A scorecard that only speaks when it has news trains everybody to
        read silence as good news."""
        text = weekly_digest.compose(
            {"any_edge": False, "with_edge": [], "cards": [card("a", effective=3)]},
            now=NOW,
        )

        assert "No brain has an edge on the forward record." in text

    def test_it_names_an_edge_when_there_is_one(self):
        text = weekly_digest.compose(
            {
                "any_edge": True,
                "with_edge": ["trend-following"],
                "cards": [card("trend-following", effective=60, verdict="edge")],
            },
            now=NOW,
        )

        assert "An edge is claimed for: trend-following" in text

    def test_the_brains_nearest_an_answer_come_first(self):
        text = weekly_digest.compose(
            {
                "any_edge": False,
                "with_edge": [],
                "cards": [
                    card("slow", effective=1),
                    card("fast", effective=40),
                    card("middling", effective=12),
                ],
            },
            now=NOW,
        )
        order = [text.index(name) for name in ("fast", "middling", "slow")]

        assert order == sorted(order)

    def test_a_crowded_brain_is_shown_as_crowded(self):
        """Sixty decisions at six instants is six pieces of evidence, and the
        message has to say so or the larger number is what gets remembered."""
        text = weekly_digest.compose(
            {
                "any_edge": False,
                "with_edge": [],
                "cards": [card("herd", effective=6, trials=60, per_instant=10.0)],
            },
            now=NOW,
        )

        assert "herd: 6 (60 decisions, 10.0 at a time)" in text

    def test_an_uncrowded_brain_is_not_cluttered_with_it(self):
        text = weekly_digest.compose(
            {
                "any_edge": False,
                "with_edge": [],
                "cards": [card("tidy", effective=9, trials=10, per_instant=1.1)],
            },
            now=NOW,
        )

        assert "tidy: 9\n" in text or text.rstrip().endswith("tidy: 9")
        assert "at a time" not in text

    def test_the_tail_is_summarised_rather_than_listed(self):
        """Eight tables is a message nobody reads by the third week."""
        cards = [card(f"brain{i}", effective=0 if i > 4 else 10 - i) for i in range(8)]
        text = weekly_digest.compose(
            {"any_edge": False, "with_edge": [], "cards": cards}, now=NOW
        )

        assert "and 4 more, 3 of them with nothing yet" in text

    def test_withdrawn_decisions_are_declared(self):
        text = weekly_digest.compose(
            {
                "any_edge": False,
                "with_edge": [],
                "cards": [card("a", effective=3)],
                "retracted_excluded": 8,
            },
            now=NOW,
        )

        assert "8 withdrawn decisions are excluded" in text

    def test_it_explains_what_an_instant_is_every_week(self):
        """The correction that matters most is the one a reader has to be
        reminded of, because the raw count is the intuitive one."""
        text = weekly_digest.compose(
            {"any_edge": False, "with_edge": [], "cards": []}, now=NOW
        )

        assert "one piece of evidence" in text


class TestSending:
    def test_a_dry_run_composes_without_sending(self, session, monkeypatch):
        sent: list[object] = []

        def refuse(*args, **kwargs):
            sent.append(args)
            raise AssertionError("a dry run must not reach the channel")

        from app.integrations import telegram

        monkeypatch.setattr(telegram, "send", refuse)
        monkeypatch.setattr(
            "app.db.session.session_scope",
            lambda: __import__("contextlib").nullcontext(session),
        )

        outcome = weekly_digest.send(dry_run=True, now=NOW)

        assert outcome["sent"] is False
        assert outcome["dry_run"] is True
        assert "MolidoTrade" in outcome["text"]
        assert sent == []
