"""The guard that stops a measurement taking the trading host down.

On 2026-09-08 three full edge reports were started on the machine that runs
the fleet, within an hour of each other. Load reached 60, the kernel began
killing terminals, and the host stopped answering ssh for two hours - the
fleet trading blind throughout. The measurements were correct. Where they ran
was the mistake, and a mistake that rests on somebody remembering is a
mistake waiting for the next person.
"""

from __future__ import annotations

import os

import pytest

from app.learning import edge_report


class TestTheHostLoadGuard:
    def test_a_quiet_host_is_allowed(self, monkeypatch):
        monkeypatch.setattr(os, "getloadavg", lambda: (1.0, 1.2, 1.1), raising=False)
        monkeypatch.setattr(os, "cpu_count", lambda: 8)

        busy, why = edge_report.host_is_too_busy()

        assert busy is False
        assert "1.2" in why

    def test_a_loaded_host_is_refused_with_the_number(self, monkeypatch):
        """"No" without a number is an obstacle. "No, the load is 47 on 8
        cores" is information."""
        monkeypatch.setattr(os, "getloadavg", lambda: (50.0, 47.0, 44.0), raising=False)
        monkeypatch.setattr(os, "cpu_count", lambda: 8)

        busy, why = edge_report.host_is_too_busy()

        assert busy is True
        assert "47.0" in why
        assert "8 core" in why
        assert "--anyway" in why

    def test_it_reads_five_minutes_not_one(self, monkeypatch):
        """A momentary spike is not a busy machine. The refusal is about the
        hour ahead, not the second behind."""
        monkeypatch.setattr(os, "getloadavg", lambda: (99.0, 2.0, 2.0), raising=False)
        monkeypatch.setattr(os, "cpu_count", lambda: 8)

        busy, _why = edge_report.host_is_too_busy()

        assert busy is False

    def test_the_ceiling_scales_with_the_machine(self, monkeypatch):
        """Sixteen on eight cores is loaded; on thirty-two it is not."""
        monkeypatch.setattr(os, "getloadavg", lambda: (20.0, 20.0, 20.0), raising=False)

        monkeypatch.setattr(os, "cpu_count", lambda: 8)
        assert edge_report.host_is_too_busy()[0] is True

        monkeypatch.setattr(os, "cpu_count", lambda: 32)
        assert edge_report.host_is_too_busy()[0] is False

    def test_a_platform_without_a_load_average_is_not_blocked(self, monkeypatch):
        """This guard exists to stop one accident on one host, not to become
        a thing that blocks work it does not understand."""
        monkeypatch.delattr(os, "getloadavg", raising=False)

        busy, why = edge_report.host_is_too_busy()

        assert busy is False
        assert "no load average" in why

    def test_an_unreadable_load_average_is_not_blocked(self, monkeypatch):
        def refuse():
            raise OSError("no /proc here")

        monkeypatch.setattr(os, "getloadavg", refuse, raising=False)

        busy, why = edge_report.host_is_too_busy()

        assert busy is False
        assert "not readable" in why


class TestTheCommandLine:
    def test_it_refuses_rather_than_waiting(self, monkeypatch, capsys):
        """A job that quietly waits is a job nobody knows is waiting."""
        monkeypatch.setattr(os, "getloadavg", lambda: (60.0, 55.0, 50.0), raising=False)
        monkeypatch.setattr(os, "cpu_count", lambda: 8)

        code = edge_report.main(["--rule", "trend-following"])

        assert code == 2
        assert "refusing to start" in capsys.readouterr().err

    def test_anyway_overrides_it(self, monkeypatch):
        """The person running this may have a reason, and the guard is not
        the authority on what that reason is worth."""
        monkeypatch.setattr(os, "getloadavg", lambda: (60.0, 55.0, 50.0), raising=False)
        monkeypatch.setattr(os, "cpu_count", lambda: 8)

        # It gets past the guard and fails later for want of a database,
        # which is the proof: the refusal is no longer what stopped it.
        with pytest.raises(Exception) as raised:
            edge_report.main(["--rule", "trend-following", "--anyway"])

        assert "refusing to start" not in str(raised.value)
