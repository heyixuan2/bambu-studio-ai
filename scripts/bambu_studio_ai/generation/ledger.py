"""Remember which paid follow-up steps were started, so resuming never pays twice.

Some results need a second paid task after the first one finishes: Meshy's texture
(refine) step, or a server-side format conversion. When a user resumes with the task
id printed earlier, the step may already be running under a newer id. This small
JSON file maps each step to the task that was started for it.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

_LOG = logging.getLogger(__name__)
_MAX_ENTRIES = 500


class FollowUpLedger:
    """A persistent ``step key → task token`` map (in memory when ``path`` is None)."""

    def __init__(self, path: Path | None) -> None:
        """Use ``path`` as the backing file; it is created on the first record."""
        self.path = path
        self._steps: dict[str, str] = self._load()

    def get(self, key: str) -> str | None:
        """The task token started for ``key``, if any."""
        return self._steps.get(key)

    def started_from(self, token: str) -> str | None:
        """The most recent step started from the task ``token``, if any."""
        prefix = token + ">"
        matches = [value for key, value in self._steps.items() if key.startswith(prefix)]
        return matches[-1] if matches else None

    def record(self, key: str, token: str) -> None:
        """Remember that ``token`` was started for ``key`` (written to disk at once)."""
        self._steps.pop(key, None)
        self._steps[key] = token
        while len(self._steps) > _MAX_ENTRIES:
            self._steps.pop(next(iter(self._steps)))
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "steps": self._steps}, indent=1), "utf-8")
        tmp.replace(self.path)

    def _load(self) -> dict[str, str]:
        if self.path is None or not self.path.exists():
            return {}
        try:
            document: object = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError) as exc:
            _LOG.warning("ignoring unreadable %s: %s", self.path, exc)
            return {}
        steps = (
            cast("dict[str, object]", document).get("steps") if isinstance(document, dict) else None
        )
        if not isinstance(steps, dict):
            return {}
        return {
            str(key): value
            for key, value in cast("dict[object, object]", steps).items()
            if isinstance(value, str)
        }
