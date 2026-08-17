"""The kill switch, and every way a stored one can fail open.

`KillSwitch` was already engaged by default and already required attribution
to release. What it had no way to do was remember: every request built a fresh
one, so the API reported it engaged while `autotrade` traded, because nothing
that traded ever asked.

Every test here is the same question asked about a different kind of damage:
does this halt, or does it trade?
"""

from __future__ import annotations

import json

import pytest

from app.execution import killswitch_store as store
from app.execution.safety import KillSwitch


def released(by: str = "aziz") -> KillSwitch:
    switch = KillSwitch()
    switch.disengage(by=by)
    return switch


class TestNothingStoredHalts:
    def test_a_missing_file_is_engaged(self, tmp_path):
        switch = store.load(tmp_path / "absent.json")

        assert switch.engaged is True
        assert "halted until somebody deliberately allows it" in switch.reason

    def test_an_empty_directory_does_not_raise(self, tmp_path):
        """A switch that throws on read takes down the caller that was about
        to consult it - and it consults it to decide whether to trade."""
        assert store.load(tmp_path / "nested" / "deep" / "absent.json").engaged


class TestDamageHalts:
    @pytest.mark.parametrize(
        "body",
        [
            "{ truncated",
            "[]",
            '"a string"',
            "null",
            "123",
            '{"state": "maybe"}',
            '{"state": null}',
            "{}",
        ],
    )
    def test_anything_unexpected_is_engaged(self, tmp_path, body):
        path = tmp_path / "state.json"
        path.write_text(body, encoding="utf-8")

        assert store.load(path).engaged is True

    def test_a_directory_where_the_file_should_be_is_engaged(self, tmp_path):
        path = tmp_path / "state.json"
        path.mkdir()

        assert store.load(path).engaged is True

    def test_the_reason_says_it_could_not_be_read(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{ truncated", encoding="utf-8")

        assert "unreadable switch halts rather than allows" in store.load(path).reason


class TestOnlyAFullDeliberateReleaseTrades:
    def test_a_disengaged_file_round_trips(self, tmp_path):
        path = tmp_path / "state.json"
        store.save(released("aziz"), path)

        switch = store.load(path)

        assert switch.engaged is False
        assert switch.engaged_by == "aziz"
        assert "disengaged by aziz" in switch.reason

    def test_a_release_naming_nobody_halts(self, tmp_path):
        """The in-memory switch refuses this, and the file must not be a way
        around the rule."""
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"state": "disengaged", "by": "  "}), encoding="utf-8")

        switch = store.load(path)

        assert switch.engaged is True
        assert "names nobody" in switch.reason

    def test_a_release_with_no_by_field_at_all_halts(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"state": "disengaged"}), encoding="utf-8")

        assert store.load(path).engaged is True

    def test_saving_a_release_without_attribution_raises(self, tmp_path):
        loose = KillSwitch()
        loose.engaged = False
        loose.engaged_by = None

        with pytest.raises(ValueError, match="must record who disengaged it"):
            store.save(loose, tmp_path / "state.json")


class TestEngagingPersists:
    def test_an_engaged_switch_round_trips_with_its_reason(self, tmp_path):
        path = tmp_path / "state.json"
        switch = KillSwitch()
        switch.engage("daily loss limit hit", by="autotrade")

        store.save(switch, path)
        loaded = store.load(path)

        assert loaded.engaged is True
        assert loaded.reason == "daily loss limit hit"

    def test_engaging_over_a_release_halts_again(self, tmp_path):
        path = tmp_path / "state.json"
        store.save(released("aziz"), path)
        assert store.load(path).engaged is False

        store.save(KillSwitch(), path)

        assert store.load(path).engaged is True


class TestTheWriteIsAtomic:
    def test_the_file_is_replaced_not_appended(self, tmp_path):
        path = tmp_path / "state.json"
        store.save(released("aziz"), path)
        store.save(KillSwitch(), path)

        assert json.loads(path.read_text(encoding="utf-8"))["state"] == "engaged"

    def test_no_temporary_files_are_left_behind(self, tmp_path):
        path = tmp_path / "state.json"
        store.save(released("aziz"), path)

        assert [p.name for p in tmp_path.iterdir()] == ["state.json"]

    def test_a_parent_directory_is_created(self, tmp_path):
        path = tmp_path / "made" / "up" / "state.json"

        store.save(KillSwitch(), path)

        assert path.exists()
