"""Why a decision was not traded, kept with the decision.

Sixteen different refusals are produced in the order stage and not one of
them was written down. They went into the cycle report, which is a log line,
and when the log rotated the reason was gone for good.

The journal already resolves every rule-arm decision whether or not an order
was sent, so the *outcome* of a refused trade is recorded. What was missing
was the other half of the pair. With both, a question nothing could answer
becomes arithmetic: of the trades the council vetoed, how many would have
won? The same for the news gate, the spread gate, the concentration cap -
each one trusted, none of them measured, which is the exact shape of the gold
defect that cost $3,730.
"""

from __future__ import annotations

import inspect

from app.workers import autotrade


class TestEveryRefusalIsRecorded:
    def test_no_refusal_bypasses_the_recorder(self):
        """`skipped.append` is the old path. Exactly one may remain - the one
        inside `refuse` itself - or a gate has gone back to refusing silently."""
        source = inspect.getsource(autotrade)

        assert source.count("skipped.append(") == 1
        assert source.count("refuse(entry,") == 16

    def test_the_one_remaining_append_is_the_recorder_itself(self):
        source = inspect.getsource(autotrade.run_cycle)
        line = next(
            text for text in source.splitlines() if "skipped.append(" in text
        )

        assert "candidate.symbol" in line

    def test_the_first_refusal_is_the_one_kept(self):
        """The loop moves on straight after refusing, so a later gate never
        overwrites the earlier one. Keeping the first is what makes the
        record answer "which gate stopped this"."""
        source = inspect.getsource(autotrade.run_cycle)

        assert "refusals.setdefault(candidate, reason)" in source


class TestHowItIsStored:
    def test_it_is_keyed_by_login_beside_the_orders(self):
        """A decision refused for one account is often traded by another -
        the fleet is offered the same decisions and the gates answer per
        account. A single "refused" field would record whichever account
        happened to run last."""
        source = inspect.getsource(autotrade.run_cycle)

        assert 'during["refused"] = book' in source
        assert "book[login] = {" in source

    def test_it_writes_once_rather_than_per_refusal(self):
        """Sixty-four refusals an account is sixty-four row updates if each
        one commits. The day this was written was spent taking pointless
        writes out of the cycle."""
        source = inspect.getsource(autotrade.run_cycle)
        tail = source[source.index("if refusals:") :]

        assert tail.count("session.commit()") == 1

    def test_the_reason_carries_a_timestamp(self):
        """A reason without a time cannot be matched to the market it was
        given in."""
        source = inspect.getsource(autotrade.run_cycle)

        assert '"at": moment.isoformat()' in source


class TestTheRecorderItself:
    def test_it_still_feeds_the_cycle_report(self):
        """The report is what an operator reads during a cycle. Recording
        must add a second home for the reason, not move it."""
        source = inspect.getsource(autotrade.run_cycle)
        body = source[source.index("def refuse(") :]

        assert "skipped.append(" in body[:400]

    def test_the_symbol_prefix_survived_the_rewrite(self):
        """Every message used to begin with the symbol. Sixteen call sites
        were rewritten mechanically; if the prefix moved into `refuse` and
        the callers kept theirs, every line would read "EURUSD: EURUSD: ..."."""
        source = inspect.getsource(autotrade.run_cycle)

        assert 'f"{candidate.symbol}: {reason}"' in source
        assert "refuse(entry, f\"{entry.symbol}" not in source
