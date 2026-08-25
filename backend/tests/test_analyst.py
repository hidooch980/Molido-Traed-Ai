"""The second brain's language half, and the three rules holding it in place.

The chain already decides. This explains the decision and argues with it, and
the entire risk of adding it is that one day it stops being commentary. So the
first class here parses the import graph, and it is the one that matters: a
test of what the analyst *says* can be fixed later; a test of what it can
*reach* is what stops a second, unwatched decision-maker from growing.

The rest are about the two ways a commentary layer becomes worse than none -
by inventing a number that later reads as a measurement, and by failing a
decision cycle because a network call timed out.
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib

import pytest

from app.brain import analyst

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: Shaped like what `pipeline.decide(...).as_dict()` actually returns - the
#: same keys, in the same places. A fixture with an invented shape would test
#: the analyst against a document it will never be handed.
TRACE = {
    "symbol": "EURUSD",
    "timeframe": "H1",
    "as_of": "2026-08-25T12:00:00+00:00",
    "reached_intent": False,
    "stopped_at": "risk",
    "permitted_risk_r": 0.0,
    "stages": [
        {"stage": "features", "passed": True, "detail": "34 features materialised", "payload": {}},
        {"stage": "regime", "passed": True, "detail": "trending, confidence 0.41", "payload": {}},
        {"stage": "council", "passed": True, "detail": "4 of 7 agree, long", "payload": {}},
        {
            "stage": "risk",
            "passed": False,
            "detail": "feed age 3.2 bars exceeds 2.0",
            "payload": {},
        },
    ],
    "intent": None,
}


class FakeBlock:
    def __init__(self, type_: str, text: str = "") -> None:
        self.type = type_
        self.text = text


class FakeResponse:
    def __init__(self, blocks, *, stop_reason="end_turn", stop_details=None, model="m"):
        self.content = blocks
        self.stop_reason = stop_reason
        self.stop_details = stop_details
        self.model = model


class FakeMessages:
    """Records what it was asked, answers what it was told to."""

    def __init__(self, response=None, raises=None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        return self.response


class FakeClient:
    def __init__(self, response=None, raises=None) -> None:
        self.messages = FakeMessages(response=response, raises=raises)


def answering(**overrides) -> FakeClient:
    payload = {
        "headline": "معامله‌ای انجام نشد.",
        "what_happened": "زنجیره تا مرحلهٔ ریسک پیش رفت و آنجا متوقف شد.",
        "objection": "آستانهٔ ۲.۰ بار خودسرانه به نظر می‌رسد.",
        "objection_strength": "worth_checking",
        "missing_from_the_trace": ["اسپرد در لحظهٔ تصمیم"],
        "would_have_traded": False,
    }
    payload.update(overrides)
    return FakeClient(
        FakeResponse(
            [FakeBlock("thinking"), FakeBlock("text", json.dumps(payload, ensure_ascii=False))]
        )
    )


class TestItCannotReachExecution:
    """The load-bearing class. A commentary layer that grows an order path is
    exactly how a system acquires a second decision-maker nobody is watching -
    and it would look like a helpful refactor on the day it happened."""

    def test_the_analyst_imports_nothing_that_trades(self):
        tree = ast.parse(inspect.getsource(analyst))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        assert not any(m.startswith("app.execution") for m in imported), imported
        assert not any(m.startswith("app.workers") for m in imported), imported

    def test_nothing_that_trades_imports_the_analyst(self):
        """The other direction, which the first test cannot see. Execution
        importing the analyst would put its opinion upstream of an order even
        if the analyst itself imports nothing."""
        offenders = []
        for path in sorted((BACKEND / "app").rglob("*.py")):
            relative = path.relative_to(BACKEND).as_posix()
            if not (relative.startswith("app/execution/") or relative.startswith("app/workers/")):
                continue
            if "analyst" in path.read_text(encoding="utf-8"):
                offenders.append(relative)

        assert offenders == [], offenders

    def test_the_payload_says_so_on_every_response(self):
        """Restated on the object a reader actually sees. `objection` is the
        field somebody will be tempted to act on."""
        verdict = analyst.analyse(TRACE, client=answering())

        assert "No path exists" in verdict.as_dict()["note"] or "no path exists" in verdict.as_dict()["note"].lower()


@pytest.fixture()
def key(monkeypatch):
    """Set or clear the configured API key for one test."""
    from app.core.config import get_settings

    settings = get_settings()

    def set_to(value: str) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", value, raising=False)

    return set_to


class TestNotConfiguredIsAnAnswer:
    def test_no_key_returns_a_verdict_rather_than_raising(self, key):
        """A missing commentary layer must not fail a decision cycle."""
        key("")

        verdict = analyst.analyse(TRACE)

        assert verdict.available is False
        assert "no API key" in verdict.unavailable_because

    def test_it_is_not_an_empty_string(self, key):
        """An empty explanation reads exactly like "there was nothing to say"."""
        key("")

        verdict = analyst.analyse(TRACE)

        assert verdict.headline
        assert verdict.unavailable_because

    def test_a_key_with_no_package_says_which_of_the_two_is_missing(self, key, monkeypatch):
        """The live deployment's actual state: `anthropic` is an optional
        extra, so a key set on a container built without it must produce the
        package message rather than the key one. An operator who has just
        pasted a key needs to be told the key is fine."""
        key("sk-ant-not-a-real-key")
        import builtins

        real_import = builtins.__import__

        def refuse(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("No module named 'anthropic'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", refuse)

        verdict = analyst.analyse(TRACE)

        assert verdict.available is False
        assert "not installed" in verdict.unavailable_because
        assert "API key" not in verdict.unavailable_because


class TestFailuresBecomeVerdictsNotExceptions:
    """The caller is in the middle of a decision cycle and the analyst is the
    least important thing in it."""

    @pytest.mark.parametrize(
        "failure",
        [
            TimeoutError("read timed out"),
            ConnectionError("no route to host"),
            RuntimeError("rate limited"),
            ValueError("nonsense"),
        ],
    )
    def test_any_call_failure_is_survivable(self, failure):
        verdict = analyst.analyse(TRACE, client=FakeClient(raises=failure))

        assert verdict.available is False
        assert type(failure).__name__ in verdict.unavailable_because

    def test_a_refusal_is_reported_as_a_refusal(self):
        """Not as an empty analysis. They mean different things."""

        class Details:
            category = "reasoning_extraction"

        client = FakeClient(
            FakeResponse([], stop_reason="refusal", stop_details=Details())
        )

        verdict = analyst.analyse(TRACE, client=client)

        assert verdict.available is False
        assert "declined" in verdict.unavailable_because
        assert "reasoning_extraction" in verdict.unavailable_because

    def test_an_unreadable_answer_is_not_a_blank_one(self):
        client = FakeClient(FakeResponse([FakeBlock("text", "not json at all")]))

        verdict = analyst.analyse(TRACE, client=client)

        assert verdict.available is False
        assert "shape" in verdict.unavailable_because

    def test_thinking_blocks_do_not_break_the_read(self):
        """`content[0]` is a thinking block whenever thinking is on. An analyst
        that crashed on its own reasoning would fail exactly when it thought
        hardest."""
        verdict = analyst.analyse(TRACE, client=answering())

        assert verdict.available is True


class TestATruncatedTraceIsRefusedRatherThanSent:
    """An analysis of a decision that did not happen is indistinguishable
    downstream from an analysis of one that did."""

    def test_an_oversized_trace_is_reported_not_trimmed(self):
        huge = {"stages": [{"reason": "x" * 1000} for _ in range(200)]}

        verdict = analyst.analyse(huge, client=answering())

        assert verdict.available is False
        assert "Truncating" in verdict.unavailable_because

    def test_it_never_reached_the_model(self):
        huge = {"stages": [{"reason": "x" * 1000} for _ in range(200)]}
        client = answering()

        analyst.analyse(huge, client=client)

        assert client.messages.calls == []


class TestTheRequestItActuallyMakes:
    def test_it_asks_for_the_structured_shape(self):
        """Free prose would mean the disagreement is a sentence somebody has to
        read and classify, rather than a field that can be counted."""
        client = answering()

        analyst.analyse(TRACE, client=client)

        call = client.messages.calls[0]
        assert call["output_config"]["format"]["type"] == "json_schema"
        assert call["output_config"]["format"]["schema"] is analyst.SCHEMA

    def test_it_uses_adaptive_thinking(self):
        client = answering()

        analyst.analyse(TRACE, client=client)

        assert client.messages.calls[0]["thinking"] == {"type": "adaptive"}

    def test_the_whole_trace_is_sent(self):
        client = answering()

        analyst.analyse(TRACE, client=client)

        sent = client.messages.calls[0]["messages"][0]["content"]
        assert "feed age 3.2 bars exceeds 2.0" in sent

    def test_the_language_is_asked_for(self):
        client = answering()

        analyst.analyse(TRACE, client=client, language="en")

        assert "Answer in en" in client.messages.calls[0]["messages"][0]["content"]

    def test_the_model_comes_from_configuration(self):
        from app.core.config import get_settings

        client = answering()

        analyst.analyse(TRACE, client=client)

        assert client.messages.calls[0]["model"] == get_settings().analyst_model


class TestTheSystemPromptForbidsInvention:
    """The failure that matters: a number the analyst produced is
    indistinguishable, later, from one the system measured."""

    def test_it_says_every_number_must_come_from_the_trace(self):
        assert "must appear in the trace" in analyst.SYSTEM

    def test_it_offers_saying_nothing_is_missing_as_a_real_answer(self):
        assert '"none"' in analyst.SYSTEM

    def test_the_schema_has_somewhere_to_put_what_is_missing(self):
        """So "the trace does not say" is a thing it can do rather than a thing
        it has to phrase."""
        assert "missing_from_the_trace" in analyst.SCHEMA["required"]

    def test_it_is_told_it_decides_nothing(self):
        assert "not deciding anything" in analyst.SYSTEM


class TestTheVerdictIsRecordable:
    def test_it_carries_what_scoring_would_need(self):
        """"Was the analyst right" has to be a question with an answer, or its
        track record is whatever anybody remembers."""
        verdict = analyst.analyse(TRACE, client=answering())
        body = verdict.as_dict()

        assert body["would_have_traded"] is False
        assert body["objection_strength"] == "worth_checking"
        assert body["at"]

    def test_an_objection_of_none_survives_the_round_trip(self):
        verdict = analyst.analyse(
            TRACE, client=answering(objection_strength="none", objection="")
        )

        assert verdict.available is True
        assert verdict.objection_strength == "none"
