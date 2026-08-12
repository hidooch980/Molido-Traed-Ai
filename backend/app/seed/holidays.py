"""Baseline market holiday data.

Deliberately conservative: only the closures that are unambiguous and stable
across brokers — New Year's Day and Christmas, when the FX market genuinely
stops rather than merely thinning out. Good Friday, Easter Monday and the
national holidays vary by venue and by year, and a wrong entry here is worse
than a missing one: it would silently mask a real data outage.

Everything else is expected to be loaded from an operator-maintained source
and marked with `source` so its provenance is visible.
"""

from __future__ import annotations

from datetime import date, time

from sqlalchemy.orm import Session

from app.core.enums import HolidayKind
from app.services.sessions import upsert_holiday

SOURCE = "molido:baseline"

# (month, day, name, kind, closes_at)
_FX_FIXED: list[tuple[int, int, str, HolidayKind, time | None]] = [
    (1, 1, "New Year's Day", HolidayKind.CLOSED, None),
    (12, 24, "Christmas Eve", HolidayKind.EARLY_CLOSE, time(13, 0)),
    (12, 25, "Christmas Day", HolidayKind.CLOSED, None),
    (12, 31, "New Year's Eve", HolidayKind.EARLY_CLOSE, time(13, 0)),
]


def seed_fx_holidays(session: Session, years: list[int]) -> int:
    """Insert the baseline FX closures for the given years. Idempotent."""
    written = 0
    for year in years:
        for month, day, name, kind, closes_at in _FX_FIXED:
            upsert_holiday(
                session,
                "FX",
                date(year, month, day),
                name=name,
                kind=kind,
                closes_at=closes_at,
                source=SOURCE,
            )
            written += 1
    return written
