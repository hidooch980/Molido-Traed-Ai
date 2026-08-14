"""What an AI agent may ask this system, and the line it may never cross.

Every tool here reads. That is not caution for its own sake, and both reasons
are worth keeping in front of whoever changes this file next.

An MCP connection authenticates the client, not the person at the keyboard, and
the endpoint lives in a config file. A tool that could trade would be an
order-placing surface with no session and nothing in the audit trail but "MCP
said so" - exactly what the execution gate exists to refuse.

And an agent reading a web page can be instructed by it. If a tool here could
trade, a sentence inside a news article becomes an order. Read-only makes that
attack a no-op instead of a loss.
"""

from __future__ import annotations

from app.integrations import mcp


class TestEveryToolReads:
    def test_the_manifest_says_so(self):
        assert mcp.manifest()["read_only"] is True

    def test_every_published_tool_is_marked_read_only(self):
        assert all(tool["read_only"] for tool in mcp.manifest()["tools"])

    def test_nothing_that_trades_is_offered(self):
        """A name check, deliberately crude. If somebody adds `place_order`
        one afternoon, this fails before it ships."""
        forbidden = ("order", "trade", "buy", "sell", "close", "size", "risk_set")
        names = [tool.name for tool in mcp.TOOLS]

        assert not [n for n in names if any(word in n for word in forbidden)]

    def test_the_refusals_are_published_beside_the_capabilities(self):
        """A capability list that only says yes teaches nobody where the edge
        of the sandbox is."""
        manifest = mcp.manifest()

        assert manifest["refused"]
        assert any("order" in refusal for refusal in manifest["refused"])
        assert "why_read_only" in manifest


class TestCalling:
    def test_a_known_tool_runs(self, session):
        result = mcp.call(session, "edge")

        assert result["ok"] is True
        assert "proven_edge_exists" in result["result"]

    def test_an_unknown_tool_returns_the_catalogue(self, session):
        """An agent that guessed wrong can correct itself. One that receives
        "unknown tool" usually tells the person the system is broken."""
        result = mcp.call(session, "place_order")

        assert result["ok"] is False
        assert "available" in result
        assert "refused" in result

    def test_every_tool_answers_without_raising(self, session):
        """An agent calling a tool that throws reports an outage. Each of these
        must return a stated unavailability instead."""
        for tool in mcp.TOOLS:
            result = mcp.call(session, tool.name)

            assert result["ok"] is True, tool.name
            assert isinstance(result["result"], dict), tool.name


class TestTheHonestHeadline:
    def test_no_proven_edge_is_stated_plainly(self, session):
        """The question an agent is most likely to soften. "No proven edge" is
        the honest headline and it must not arrive wrapped in enough context to
        read as "promising"."""
        result = mcp.call(session, "edge")["result"]

        assert result["proven_edge_exists"] is False
        assert "no proven edge" in result["headline"]

    def test_a_missing_account_gives_a_reason_not_an_empty_object(self, session):
        """An agent receiving {} summarises it as "no data" and moves on. One
        receiving a reason tells the person the actual problem."""
        result = mcp.call(session, "account")["result"]

        assert "available" in result
        if not result["available"]:
            assert result["reason"]

    def test_real_money_is_named(self, session):
        """An agent summarising this for a person must not describe a funded
        account as practice."""
        result = mcp.call(session, "account")["result"]

        if result.get("available"):
            assert "is_real_money" in result
