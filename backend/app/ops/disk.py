"""Watch the disk, because nothing else was (spec §35, §39).

The host reached 82% and nobody noticed until somebody looked by hand. With
four gigabytes left, two more deploys would have filled it, and a full disk
does not announce itself as a full disk - PostgreSQL stops accepting writes,
the collector starts failing, and every symptom points somewhere else.

`readiness` said this could not be checked from inside a container. That turned
out to be wrong: the container's root filesystem is the host's disk, and
`shutil.disk_usage` inside the API reports 51% where the host reports 54% - the
difference is the overlay, not a different disk. The assumption was never
tested, which is how a check that was perfectly possible went unwritten for
months.

Thresholds are about what remains, not only what fraction is used. A 90% full
disk with 40GB free is fine; a 75% full disk with 900MB free is an outage in
progress, and a percentage alone cannot tell those apart.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Any

#: Below this many bytes free, writes are at risk regardless of the
#: percentage. PostgreSQL needs room for WAL, and a build needs room for a
#: layer; neither cares what fraction of the disk that is.
CRITICAL_FREE_BYTES = 1 * 1024**3
SERIOUS_FREE_BYTES = 3 * 1024**3

#: And the proportional view, for a disk large enough that the absolute floor
#: would never trigger until it was far too late.
CRITICAL_USED_RATIO = 0.95
SERIOUS_USED_RATIO = 0.85


@dataclass(frozen=True)
class DiskState:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    path: str

    @property
    def used_ratio(self) -> float:
        return self.used_bytes / self.total_bytes if self.total_bytes else 0.0

    @property
    def severity(self) -> str | None:
        """The worst thing true about this disk, or None if it is fine."""
        if self.free_bytes < CRITICAL_FREE_BYTES or self.used_ratio >= CRITICAL_USED_RATIO:
            return "critical"
        if self.free_bytes < SERIOUS_FREE_BYTES or self.used_ratio >= SERIOUS_USED_RATIO:
            return "serious"
        return None

    @property
    def summary(self) -> str:
        """Deliberately free of exact byte counts.

        The incident fingerprint strips digits, but a summary that changed on
        every megabyte would still read badly in a list. Free space is rounded
        to whole gigabytes so successive reports of the same condition say the
        same thing.
        """
        return (
            f"disk at {self.used_ratio:.0%} with "
            f"{self.free_bytes / 1024**3:.0f}GB free on {self.path}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "total_gb": round(self.total_bytes / 1024**3, 1),
            "used_gb": round(self.used_bytes / 1024**3, 1),
            "free_gb": round(self.free_bytes / 1024**3, 1),
            "used_ratio": round(self.used_ratio, 3),
            "severity": self.severity,
            "healthy": self.severity is None,
            "thresholds": {
                "critical_free_gb": CRITICAL_FREE_BYTES / 1024**3,
                "serious_free_gb": SERIOUS_FREE_BYTES / 1024**3,
                "critical_used_ratio": CRITICAL_USED_RATIO,
                "serious_used_ratio": SERIOUS_USED_RATIO,
            },
            "note": (
                "judged on bytes remaining as well as percentage: a 90% disk "
                "with 40GB free is fine, and a 75% disk with 900MB free is an "
                "outage in progress"
            ),
        }


def measure(path: str = "/") -> DiskState:
    total, used, free = shutil.disk_usage(path)
    return DiskState(total_bytes=total, used_bytes=used, free_bytes=free, path=path)
