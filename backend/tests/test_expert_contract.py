"""The expert and the endpoint are one contract written in two languages.

Nothing here compiles MQL5. What it checks is the half of the agreement that
can be checked from Python: that the field names the expert sends are the field
names the endpoint reads, and that the properties the expert's own comments
promise are actually in its source.

That is worth a test file because the failure mode is silent. A renamed field
does not raise anywhere - the endpoint fills a default, writes it, and the
platform reports a terminal that is publishing perfectly and saying nothing.
"""

from __future__ import annotations

import pathlib

import pytest

EXPERT = (
    pathlib.Path(__file__).resolve().parents[2] / "infra" / "mql5" / "MolidoBridge.mq5"
)


@pytest.fixture(scope="module")
def source() -> str:
    assert EXPERT.exists(), f"the expert should live at {EXPERT}"
    return EXPERT.read_text(encoding="utf-8", errors="replace")


class TestTheFieldsMatch:
    @pytest.mark.parametrize(
        "field", ["account_key", "account", "positions", "connected", "login"]
    )
    def test_the_expert_sends_what_the_endpoint_reads(self, source, field):
        """Every field on the publish model, present in the expert's body.

        A rename on either side is invisible at runtime: the endpoint fills a
        default and writes it, and the platform reports a terminal publishing
        happily into a directory that says nothing.
        """
        assert f'\\"{field}\\"' in source

    def test_the_endpoint_declares_the_same_fields(self):
        from app.api.v1.bridge_ingest import BridgePublish

        assert set(BridgePublish.model_fields) == {
            "account_key",
            "account",
            "symbols",
            "positions",
            "connected",
            "login",
        }


class TestTheKeyIsNotLeaked:
    def test_the_api_key_is_never_printed(self, source):
        """The Experts tab is shoulder-surfable and gets pasted into forums."""
        for line in source.splitlines():
            if "Print(" in line:
                assert "PublishApiKey" not in line

    def test_the_api_key_is_never_written_to_a_file(self, source):
        for line in source.splitlines():
            if "FileWriteString" in line:
                assert "PublishApiKey" not in line


class TestHttpIsAdditive:
    def test_the_files_are_still_written(self, source):
        """HTTP publishing must not replace the local bridge.

        A terminal that already publishes to a folder keeps working exactly as
        it did, and a network outage costs the remote copy rather than the
        whole bridge - so turning this on cannot break a setup that works.
        """
        for writer in (
            "WriteAccount()",
            "WriteSymbols()",
            "WritePositions()",
            "WriteHeartbeat(cycle)",
        ):
            assert writer in source

    def test_publishing_over_http_happens_after_the_files(self, source):
        """A slow endpoint must not delay the bridge this terminal already has."""
        cycle = source.split("void Publish()")[1]
        assert cycle.index("WriteHeartbeat(cycle)") < cycle.index("PostToPlatform()")

    def test_an_empty_url_disables_it_entirely(self, source):
        """The default. An expert nobody configured must behave as it always did."""
        assert 'input string PublishUrl        = "";' in source
        body = source.split("void PostToPlatform()")[1]
        assert "StringLen(PublishUrl) == 0" in body[:300]


class TestOnePayloadNotTwo:
    def test_the_file_and_the_request_share_one_builder(self, source):
        """Two builders for one payload agree today and drift on the next field."""
        assert "string AccountJson()" in source
        assert "string PositionsArray()" in source

        writer = source.split("void WriteAccount()")[1][:300]
        assert "AccountJson()" in writer

        request = source.split("void PostToPlatform()")[1][:1200]
        assert "AccountJson()" in request


class TestItSaysWhatToDoAboutTheFirstError:
    def test_the_whitelist_error_names_the_setting(self, source):
        """4060 is the error everyone hits first, and MetaTrader's own message
        for it does not say what to change."""
        assert "4060" in source
        assert "Allow WebRequest" in source

    def test_the_whitelist_warning_is_said_once(self, source):
        """It is a permanent condition until somebody changes a setting.
        Repeated every twenty seconds it buries the rest of the log."""
        assert "warned_not_whitelisted" in source
