"""The shape every check result shares."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Status = Literal["pass", "warn", "fail", "skipped"]


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one check: a status and one true sentence about the model."""

    status: Status
    summary: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict."""
        return asdict(self)
