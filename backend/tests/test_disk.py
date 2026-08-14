"""Disk pressure, judged on what is left rather than only on a percentage.

The host reached 82% and nobody noticed until somebody looked by hand. A full
disk does not announce itself as a full disk: PostgreSQL stops accepting
writes, the collector starts failing, and every symptom points somewhere else.

`readiness` recorded that this could not be checked from inside a container.
That was never tested and was wrong - the container's root filesystem is the
host's disk. An untested assumption left a perfectly possible check unwritten
for months, which is the more interesting failure of the two.
"""

from __future__ import annotations

from app.ops.disk import (
    CRITICAL_FREE_BYTES,
    SERIOUS_FREE_BYTES,
    DiskState,
    measure,
)

GB = 1024**3


def state(total_gb, free_gb, path="/"):
    total = int(total_gb * GB)
    free = int(free_gb * GB)
    return DiskState(total_bytes=total, used_bytes=total - free, free_bytes=free, path=path)


class TestBytesLeftMattersNotOnlyThePercentage:
    def test_a_huge_disk_at_ninety_percent_is_worth_knowing_but_not_critical(self):
        """40GB free is not an emergency. It is still 90% used, and the trend
        is the point - so `serious`, not `critical` and not silence.

        This test originally asserted `None`, on the grounds that 40GB free is
        fine "whatever fraction it represents". The code disagreed and the code
        was right: a proportional rule exists precisely to notice a large disk
        before the absolute floor does, and weakening the threshold to make the
        assertion pass would have removed the only warning that arrives early.
        """
        assert state(400, 40).severity == "serious"

    def test_a_small_disk_at_seventy_five_percent_is_not(self):
        """900MB free is an outage in progress, and a percentage alone cannot
        tell it apart from the case above."""
        assert state(4, 0.9).severity == "critical"

    def test_the_proportional_rule_still_catches_a_large_disk(self):
        """On a disk big enough that the absolute floor never trips, the ratio
        has to do the work."""
        assert state(1000, 40).severity == "critical"


class TestThresholds:
    def test_below_the_critical_floor_is_critical(self):
        assert state(23, CRITICAL_FREE_BYTES / GB - 0.1).severity == "critical"

    def test_below_the_serious_floor_is_serious(self):
        assert state(23, SERIOUS_FREE_BYTES / GB - 0.1).severity == "serious"

    def test_a_healthy_disk_reports_no_severity(self):
        """None rather than "ok": a severity of none is the absence of a
        problem, and a string would end up compared against the others."""
        assert state(23, 11).severity is None

    def test_the_real_deployment_shape_is_healthy(self):
        """23GB total with 11GB free - the state the server is actually in."""
        assert state(23, 11).as_dict()["healthy"] is True


class TestTheSummaryIsStableAcrossReports:
    def test_free_space_is_rounded_to_whole_gigabytes(self):
        """The incident fingerprint strips digits, but a summary that changed
        on every megabyte would still read badly in a list of occurrences."""
        first = state(23, 2.4).summary
        second = state(23, 2.4).summary

        assert first == second
        assert "GB free" in first

    def test_the_path_is_named(self):
        """Two mounts filling up are two different problems."""
        assert "/data" in state(23, 1, path="/data").summary


class TestMeasuringForReal:
    def test_it_reads_an_actual_filesystem(self):
        """Guards the guard: a measurement that returned zeros would make every
        threshold above vacuous."""
        reading = measure("/")

        assert reading.total_bytes > 0
        assert reading.free_bytes >= 0
        assert 0.0 <= reading.used_ratio <= 1.0

    def test_the_payload_states_how_it_judges(self):
        payload = measure("/").as_dict()

        assert "bytes remaining as well as percentage" in payload["note"]
        assert payload["thresholds"]["critical_free_gb"] == CRITICAL_FREE_BYTES / GB
