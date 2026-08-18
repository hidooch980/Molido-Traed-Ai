"""Pausing one account without pausing the others.

The global kill switch is a fleet-wide halt and is deliberately blunt. This is
the other control: one account off while the rest carry on, because a terminal
is being reconnected, a challenge has been failed, or that broker is having a
bad afternoon.

Every test here is about the same question the kill switch tests ask, scoped
to one account: does an unexpected state carry on trading, or stop?
"""

from __future__ import annotations

import json

import pytest

from app.execution.account_switch import ACTIVE, PAUSED, listing, state, write


class TestAConfiguredAccountDefaultsToOn:
    """Unlike the global switch, which starts engaged because nobody has said
    trading is allowed yet. Adding an account to the bridge map is already a
    deliberate act by somebody with shell access."""

    def test_no_file_means_the_account_may_trade(self, tmp_path):
        allowed, why = state("main", tmp_path)

        assert allowed is True
        assert why == ""

    def test_a_missing_directory_is_not_an_error(self, tmp_path):
        assert state("main", tmp_path / "not" / "made" / "yet")[0] is True


class TestPausing:
    def test_a_paused_account_may_not_trade(self, tmp_path):
        write("main", active=False, by="aziz", directory=tmp_path)

        allowed, why = state("main", tmp_path)

        assert allowed is False
        assert "paused" in why

    def test_the_pause_names_who_and_why(self, tmp_path):
        write("main", active=False, by="aziz", reason="reconnecting", directory=tmp_path)

        _, why = state("main", tmp_path)

        assert "by aziz" in why
        assert "reconnecting" in why

    def test_resuming_lets_it_trade_again(self, tmp_path):
        write("main", active=False, by="aziz", directory=tmp_path)
        write("main", active=True, by="aziz", directory=tmp_path)

        assert state("main", tmp_path)[0] is True

    def test_pausing_one_account_leaves_another_alone(self, tmp_path):
        write("main", active=False, by="aziz", directory=tmp_path)

        assert state("challenge", tmp_path)[0] is True

    def test_a_change_must_be_attributable_in_both_directions(self, tmp_path):
        """The record of who stopped an account and who started it should be
        the same kind of record."""
        with pytest.raises(ValueError, match="attributable"):
            write("main", active=False, by="  ", directory=tmp_path)
        with pytest.raises(ValueError, match="attributable"):
            write("main", active=True, by="", directory=tmp_path)


class TestAnUnexpectedStatePauses:
    """The safe reading of a control nobody recognises is not 'carry on'."""

    @pytest.mark.parametrize(
        "body", ["{ truncated", "[]", "null", '"active"', '{"state": "maybe"}', "{}"]
    )
    def test_anything_unreadable_pauses(self, tmp_path, body):
        (tmp_path / "main.json").write_text(body, encoding="utf-8")

        assert state("main", tmp_path)[0] is False

    def test_a_directory_where_the_file_should_be_pauses(self, tmp_path):
        (tmp_path / "main.json").mkdir()

        assert state("main", tmp_path)[0] is False

    def test_the_reason_says_it_could_not_be_read(self, tmp_path):
        (tmp_path / "main.json").write_text("{ truncated", encoding="utf-8")

        assert "pauses rather than carries on" in state("main", tmp_path)[1]

    def test_it_never_raises(self, tmp_path):
        """A control that throws on the read path takes down the caller that
        was about to consult it."""
        (tmp_path / "main.json").write_text("\x00\xff not json", encoding="latin-1")

        assert state("main", tmp_path)[0] is False


class TestTheKeyCannotEscapeTheDirectory:
    def test_a_key_with_a_slash_stays_inside(self, tmp_path):
        written = write("../../etc/passwd", active=False, by="aziz", directory=tmp_path)

        assert written.parent == tmp_path

    def test_a_key_of_only_punctuation_still_gets_a_file(self, tmp_path):
        written = write("///", active=False, by="aziz", directory=tmp_path)

        assert written.name == "unnamed.json"


class TestTheWriteIsAtomic:
    def test_no_temporary_files_are_left(self, tmp_path):
        write("main", active=False, by="aziz", directory=tmp_path)

        assert [p.name for p in tmp_path.iterdir()] == ["main.json"]

    def test_the_file_is_replaced_not_appended(self, tmp_path):
        write("main", active=False, by="aziz", directory=tmp_path)
        write("main", active=True, by="aziz", directory=tmp_path)

        assert json.loads((tmp_path / "main.json").read_text())["state"] == ACTIVE


class TestTheListing:
    def test_it_reports_every_account_and_why(self, tmp_path):
        write("paused-one", active=False, by="aziz", reason="failed", directory=tmp_path)

        rows = listing(["paused-one", "running"], tmp_path)

        assert rows[0]["account"] == "paused-one"
        assert rows[0]["active"] is False
        assert "failed" in rows[0]["reason"]
        assert rows[1] == {"account": "running", "active": True, "reason": ""}

    def test_an_empty_fleet_lists_nothing_rather_than_failing(self, tmp_path):
        assert listing([], tmp_path) == []

    def test_the_states_are_the_two_words_the_file_uses(self):
        assert (ACTIVE, PAUSED) == ("active", "paused")
