"""Wait for a remote task without ever paying twice.

A poll timeout is not a failure: the task keeps running at the provider and can be
resumed later with ``generate.py status/download <task id>``. Nothing here submits
work, so running out of time can never start (or pay for) another generation.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from bambu_studio_ai.generation.errors import ProviderError
from bambu_studio_ai.generation.providers.base import TaskState, TaskStatus

_BACKOFF = 1.5


@dataclass(frozen=True)
class WaitOutcome:
    """How waiting ended."""

    status: TaskStatus
    """The last status seen (final unless ``timed_out``)."""
    timed_out: bool
    """True when time ran out first; the task may still finish at the provider."""
    last_error: str = ""
    """A temporary polling error seen at the end, if any."""


def wait_for_task(  # noqa: PLR0913  (timing knobs are injected for tests)
    poll: Callable[[], TaskStatus],
    *,
    timeout_s: float,
    interval_s: float,
    max_interval_s: float,
    initial_delay_s: float = 0.0,
    on_update: Callable[[TaskStatus], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> WaitOutcome:
    """Poll until the task reaches a final state or ``timeout_s`` has passed.

    Temporary errors (5xx, 429, dropped connections) are tolerated until the deadline;
    anything else (a rejected key, an unknown task) is raised at once.

    Args:
        poll: Reads the task's status once.
        timeout_s: Total time to wait, including ``initial_delay_s``.
        interval_s: First delay between polls; grows by 1.5x up to ``max_interval_s``.
        max_interval_s: Longest delay between polls.
        initial_delay_s: Delay before the first poll (providers ask for ~5 s after submit).
        on_update: Called with every status read.
        sleep: Injected for tests.
        clock: Injected for tests.

    Raises:
        ProviderError: a non-temporary error while polling.
    """
    deadline = clock() + timeout_s
    delay = interval_s
    last = TaskStatus(TaskState.QUEUED, message="not checked yet")
    last_error = ""
    if initial_delay_s > 0:
        sleep(min(initial_delay_s, max(deadline - clock(), 0.0)))
    while True:
        try:
            status = poll()
        except ProviderError as exc:
            if not exc.retryable:
                raise
            last_error = exc.message
        else:
            last, last_error = status, ""
            if on_update is not None:
                on_update(status)
            if status.state.terminal:
                return WaitOutcome(status, timed_out=False)
        remaining = deadline - clock()
        if remaining <= 0:
            return WaitOutcome(last, timed_out=True, last_error=last_error)
        sleep(min(delay, remaining))
        delay = min(delay * _BACKOFF, max_interval_s)
