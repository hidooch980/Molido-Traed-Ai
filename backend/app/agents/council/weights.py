"""Versioned council weights with rollback. Every change is a new version.

Rolling back does not delete history: it writes a new version equal to an old
one, with the reason, so the audit trail shows both the change and its undo.
Optional JSON persistence (atomic replace) for restarts.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

DEFAULT_WEIGHTS = {
    "macro": 0.5, "news": 0.0, "sentiment": 0.3, "quant": 0.6, "execution": 0.0,
    "adversarial": 0.0,
}


@dataclass(frozen=True)
class WeightVersion:
    version: int
    weights: dict[str, float]
    reason: str
    author: str
    created_at: str


@dataclass
class WeightStore:
    path: pathlib.Path | None = None
    history: list[WeightVersion] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.history = [WeightVersion(**v) for v in data]
        if not self.history:
            self._append(dict(DEFAULT_WEIGHTS), "initial declared weights", "system")

    def current(self) -> WeightVersion:
        return self.history[-1]

    def propose(self, weights: dict[str, float], *, reason: str, author: str) -> WeightVersion:
        if any(w < 0 for w in weights.values()):
            raise ValueError("weights cannot be negative")
        if not reason.strip() or not author.strip():
            raise ValueError("a weight change needs a reason and an author")
        return self._append(dict(weights), reason, author)

    def rollback(self, to_version: int, *, reason: str, author: str) -> WeightVersion:
        target = next((v for v in self.history if v.version == to_version), None)
        if target is None:
            raise KeyError(to_version)
        return self._append(dict(target.weights),
                            f"rollback to v{to_version}: {reason}", author)

    def _append(self, weights: dict[str, float], reason: str, author: str) -> WeightVersion:
        version = WeightVersion(len(self.history) + 1, weights, reason, author,
                                datetime.now(UTC).isoformat())
        self.history.append(version)
        self._save()
        return version

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump([asdict(v) for v in self.history], handle)
        os.replace(tmp, self.path)
