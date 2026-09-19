"""The steps behind ``generate.py``: submit, wait, follow up, download, measure, size.

Credits are only spent in :meth:`Generator.submit` and when a follow-up step (Meshy's
texture pass, a server-side conversion) is started for the first time. Waiting,
checking and resuming never spend anything, and a wait that runs out of time returns
the task id to resume with instead of failing or trying again.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from bambu_studio_ai.generation import scale
from bambu_studio_ai.generation.providers.base import TaskRef, TaskState
from bambu_studio_ai.generation.task import wait_for_task

if TYPE_CHECKING:
    from pathlib import Path

    from bambu_studio_ai.generation.ledger import FollowUpLedger
    from bambu_studio_ai.generation.providers.base import (
        FollowUp,
        GenerationRequest,
        OutputFormat,
        Provider,
        TaskStatus,
    )

GLB_AXIS_NOTE = (
    "Bambu Studio 2.7 reads GLB coordinates as-is with Z up and does not convert glTF's "
    "Y-up axis, so the model may import lying on its back; the Z extent above is its "
    "height as imported."
)


def _ignore(_message: str) -> None:
    """Default ``notify``: drop progress messages."""


@dataclass
class GenerationResult:
    """What a command reports (``--json`` prints :meth:`to_dict`)."""

    task_id: str
    provider: str
    status: str
    """A :class:`TaskState` value, or ``"submitted"`` right after submitting."""
    output_file: str | None = None
    output_format: str | None = None
    extents_mm: tuple[float, float, float] | None = None
    """X, Y, Z in millimetres as Bambu Studio imports the file (Z is up)."""
    has_texture: bool | None = None
    progress: int | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list[str])
    prompt_used: bool | None = None
    """For image-to-3D: whether the provider received ``--prompt``."""

    @property
    def still_running(self) -> bool:
        """Whether the task has not finished yet (resume with ``download``)."""
        return self.status in ("submitted", TaskState.QUEUED.value, TaskState.RUNNING.value)

    def to_dict(self) -> dict[str, object]:
        """A JSON-ready dict with a stable set of keys."""
        extents = [round(value, 2) for value in self.extents_mm] if self.extents_mm else None
        return {
            "task_id": self.task_id,
            "provider": self.provider,
            "status": self.status,
            "output_file": self.output_file,
            "format": self.output_format,
            "extents_mm": extents,
            "has_texture": self.has_texture,
            "progress": self.progress,
            "message": self.message,
            "warnings": list(self.warnings),
            "prompt_used": self.prompt_used,
        }


class Generator:
    """Runs one provider's tasks to a finished, measured file."""

    def __init__(  # noqa: PLR0913  (clock and sleep are injected for tests)
        self,
        provider: Provider,
        *,
        output_dir: Path,
        ledger: FollowUpLedger,
        notify: Callable[[str], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a generator writing into ``output_dir``; ``notify`` receives progress text."""
        self.provider = provider
        self.output_dir = output_dir
        self.ledger = ledger
        self.notify = notify or _ignore
        self.sleep = sleep
        self.clock = clock
        self._last_report = ""

    def submit(self, request: GenerationRequest) -> TaskRef:
        """Start the generation (the only place that pays for a new model)."""
        if request.image is not None:
            return self.provider.submit_image(request)
        return self.provider.submit_text(request)

    def status(self, ref: TaskRef) -> GenerationResult:
        """Check a task once, following a step already started from it. Never pays."""
        started = self.ledger.started_from(ref.token)
        current = TaskRef.parse(started) if started else ref
        status = self.provider.poll(current)
        result = self._result(current, status)
        if status.state is TaskState.SUCCEEDED:
            step = self.provider.follow_up(current, status, "glb", texture=True)
            if step is not None:
                result.message = f"finished; `download` starts the {step.description}"
        return result

    def complete(  # noqa: PLR0913
        self,
        ref: TaskRef,
        *,
        output_format: OutputFormat,
        texture: bool,
        height_mm: float | None,
        timeout_s: float,
        first_delay_s: float = 0.0,
    ) -> GenerationResult:
        """Wait for ``ref``, run any follow-up step, download, and size the model.

        Returns a result with status ``queued``/``running`` (and the id to resume with)
        when ``timeout_s`` runs out; nothing is resubmitted in that case.
        """
        deadline = self.clock() + timeout_s
        current, delay = ref, first_delay_s
        while True:
            outcome = wait_for_task(
                partial(self.provider.poll, current),
                timeout_s=max(deadline - self.clock(), 0.0),
                interval_s=self.provider.poll_interval_s,
                max_interval_s=self.provider.max_poll_interval_s,
                initial_delay_s=delay,
                on_update=self._report,
                sleep=self.sleep,
                clock=self.clock,
            )
            result = self._result(current, outcome.status)
            if outcome.timed_out:
                result.message = outcome.last_error or "still running at the provider"
                return result
            if outcome.status.state is not TaskState.SUCCEEDED:
                return result
            step = self.provider.follow_up(current, outcome.status, output_format, texture=texture)
            if step is None:
                break
            current, delay = self._start_once(step), self.provider.poll_interval_s
        return self._download(current, output_format, height_mm)

    def _start_once(self, step: FollowUp) -> TaskRef:
        recorded = self.ledger.get(step.key)
        if recorded:
            self.notify(f"{step.description} was already started: {recorded}")
            return TaskRef.parse(recorded)
        started = self.provider.start_follow_up(step)
        self.ledger.record(step.key, started.token)
        self.notify(f"Started the {step.description}; its task id is {started.token}")
        return started

    def _download(
        self, ref: TaskRef, output_format: OutputFormat, height_mm: float | None
    ) -> GenerationResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        fetched = self.provider.fetch(ref, output_format, self.output_dir)
        path, got = fetched.path, fetched.output_format
        result = GenerationResult(ref.token, ref.provider, TaskState.SUCCEEDED.value)
        if got != output_format and got == "glb":
            converted = path.with_suffix(f".{output_format}")
            scale.convert_glb_locally(path, converted, output_format)
            unscaled = " (at the provider's size)" if height_mm else ""
            result.warnings.append(
                f"{ref.provider} cannot deliver {output_format.upper()} for this task, so it was "
                f"converted locally from the GLB and its colour was discarded. "
                f"The textured GLB is kept at {path}{unscaled}."
            )
            path, got = converted, output_format
        elif got != output_format:
            result.warnings.append(
                f"this task only has {got.upper()}, not {output_format.upper()}; kept {got.upper()}"
            )
        elif got != "glb":
            result.warnings.append(
                f"{got.upper()} carries no colour; the default GLB output keeps the texture"
            )
        extents = (
            scale.scale_to_height(path, got, height_mm) if height_mm else scale.measure(path, got)
        )
        if max(extents) < scale.TINY_MODEL_MM:
            result.warnings.append(
                f"the model is only {max(extents):.2f} mm across (AI providers use arbitrary "
                "units); rerun download with --height MM to size it"
            )
        if got == "glb":
            result.warnings.append(GLB_AXIS_NOTE)
        result.output_file = str(path)
        result.output_format = got
        result.extents_mm = extents
        result.has_texture = scale.has_texture(path, got)
        result.progress = 100
        return result

    def _result(self, ref: TaskRef, status: TaskStatus) -> GenerationResult:
        return GenerationResult(
            task_id=ref.token,
            provider=ref.provider,
            status=status.state.value,
            progress=status.progress,
            message=status.message,
        )

    def _report(self, status: TaskStatus) -> None:
        progress = f" {status.progress}%" if status.progress is not None else ""
        note = f" ({status.message})" if status.message else ""
        line = f"{self.provider.name}: {status.state.value}{progress}{note}"
        if line != self._last_report:
            self._last_report = line
            self.notify(line)
