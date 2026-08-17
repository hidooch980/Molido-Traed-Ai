"""One terminal per account, and the one lookup that must never guess.

The bridge files carry no account identity - `molido_positions.json` is just
positions. The directory *is* the account. Every test here is about the same
failure: a lookup that answers with the wrong terminal, which every file
involved would then make look correct.
"""

from __future__ import annotations

import pathlib

import pytest

from app.core.errors import ProviderError
from app.providers.metatrader import (
    DEFAULT_ACCOUNT_KEY,
    DEFAULT_BRIDGE_DIR,
    bridge_dir_for,
    bridge_dirs,
)

TWO = "main=/bridge/one,challenge=/bridge/two"


class TestTheSingleTerminalKeepsWorking:
    """This deployment has run one terminal since the beginning. Adding the
    map must not require configuring what already works."""

    def test_unset_is_the_one_terminal_that_exists(self):
        assert bridge_dirs("") == {DEFAULT_ACCOUNT_KEY: DEFAULT_BRIDGE_DIR}

    def test_blank_and_whitespace_are_both_unset(self):
        assert bridge_dirs("   ") == bridge_dirs("")

    def test_no_key_is_needed_when_there_is_only_one(self):
        assert bridge_dir_for(None, "") == DEFAULT_BRIDGE_DIR


class TestParsing:
    def test_two_accounts_are_kept_apart(self):
        assert bridge_dirs(TWO) == {
            "main": pathlib.Path("/bridge/one"),
            "challenge": pathlib.Path("/bridge/two"),
        }

    def test_spacing_does_not_change_meaning(self):
        assert bridge_dirs(" main = /bridge/one , challenge = /bridge/two ") == bridge_dirs(TWO)

    def test_a_trailing_comma_is_not_an_account(self):
        assert list(bridge_dirs("main=/bridge/one,")) == ["main"]


class TestMalformedRaisesRatherThanSkipping:
    """A dropped account reads downstream as 'that terminal is not
    publishing' - a real condition this codebase reports honestly, and it
    would be reported about an account that is running fine."""

    @pytest.mark.parametrize("raw", ["main", "=/bridge/one", "main=", "main=/a,broken"])
    def test_an_entry_that_is_not_key_equals_path_raises(self, raw):
        with pytest.raises(ProviderError, match="not `key=/path`"):
            bridge_dirs(raw)

    def test_a_repeated_account_raises_rather_than_letting_the_last_win(self):
        with pytest.raises(ProviderError, match="twice"):
            bridge_dirs("main=/bridge/one,main=/bridge/two")


class TestTheLookupNeverFallsBack:
    """The property the whole module exists for. A default here routes one
    account's orders to another account's terminal. An exception stops a wrong
    trade; a fallback places one."""

    def test_an_unknown_account_raises(self):
        with pytest.raises(ProviderError, match="Refusing to fall back"):
            bridge_dir_for("ghost", TWO)

    def test_the_error_names_what_it_does_know(self):
        with pytest.raises(ProviderError, match="challenge, main"):
            bridge_dir_for("ghost", TWO)

    def test_it_does_not_quietly_pick_the_first_of_several(self):
        with pytest.raises(ProviderError, match="would guess whose money"):
            bridge_dir_for(None, TWO)

    def test_each_configured_account_gets_its_own_directory(self):
        assert bridge_dir_for("main", TWO) != bridge_dir_for("challenge", TWO)
