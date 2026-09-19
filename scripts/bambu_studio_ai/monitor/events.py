"""Decide what is worth telling the user, one printer status at a time.

Pure logic: :func:`evaluate` takes the latest status, the state carried over from the
previous check and the current time, and returns the events to announce. The caller
handles the network, clocks, persistence and notifications.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from bambu_studio_ai.printer.report import PrinterStatus

STALL_MINUTES = 20
"""A RUNNING print whose layer and time-left haven't moved for this long is flagged."""
PROGRESS_EVERY_MINUTES = 30
TEMPERATURE_MARGIN_C = 10.0
"""Readings this far above the printer's rated maximum are flagged."""


@dataclass(frozen=True)
class Limits:
    """Rated maximums for the printer being watched."""

    nozzle_c: float = 300.0
    bed_c: float = 120.0


@dataclass(frozen=True)
class Event:
    """Something the user should hear about."""

    kind: str
    """``started``, ``progress``, ``paused``, ``alert``, ``finished``, ``failed`` or ``stopped``."""
    severity: str
    """``info``, ``warning`` or ``critical``."""
    title: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


@dataclass
class MonitorState:
    """What the monitor remembers between checks (persisted for ``--once`` runs)."""

    watching: bool = False
    job: str = ""
    last_layer: int | None = None
    last_remaining: int | None = None
    last_change_at: float | None = None
    last_progress_at: float | None = None
    announced: list[str] = field(default_factory=list[str])
    """Keys of warnings already sent for this job, so each is sent once."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MonitorState:
        """Rebuild from :meth:`to_dict` output, ignoring unknown keys."""
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


def evaluate(status: PrinterStatus, state: MonitorState, now: float, limits: Limits) -> list[Event]:
    """Return the events for this status and update ``state`` in place."""
    events: list[Event] = []
    if status.active and not state.watching:
        _start_job(status, state, now)
        events.append(Event("started", "info", "Watching print", _summary(status)))
    if not state.watching:
        return events

    ended = _job_end(status)
    if ended:
        events.append(ended)
        _reset(state)
        return events

    _track_movement(status, state, now)
    events += _warnings(status, state, now, limits)
    if (
        status.state == "RUNNING"
        and _minutes_since(state.last_progress_at, now) >= PROGRESS_EVERY_MINUTES
    ):
        state.last_progress_at = now
        events.append(Event("progress", "info", "Print progress", _summary(status)))
    return events


def _start_job(status: PrinterStatus, state: MonitorState, now: float) -> None:
    _reset(state)
    state.watching = True
    state.job = status.file
    state.last_change_at = now
    state.last_progress_at = now


def _reset(state: MonitorState) -> None:
    fresh = MonitorState()
    for name in MonitorState.__dataclass_fields__:
        setattr(state, name, getattr(fresh, name))


def _job_end(status: PrinterStatus) -> Event | None:
    if status.state == "FINISH":
        return Event("finished", "info", "Print finished", f"{status.file or 'The print'} is done.")
    if status.state == "FAILED":
        detail = f" (error {status.print_error})" if status.print_error else ""
        return Event(
            "failed", "critical", "Print failed", f"The printer reports a failed print{detail}."
        )
    if not status.active and status.state != "UNKNOWN":
        return Event(
            "stopped",
            "warning",
            "Print stopped",
            "The printer is idle again; the job was cancelled.",
        )
    return None


def _warnings(
    status: PrinterStatus, state: MonitorState, now: float, limits: Limits
) -> list[Event]:
    candidates: list[tuple[str, Event]] = []
    if status.state == "PAUSE":
        candidates.append(
            (
                "pause",
                Event(
                    "paused",
                    "warning",
                    "Print paused",
                    "Paused on the printer (filament runout, a detected problem, or by hand). "
                    "Check the printer screen or Bambu Handy.",
                ),
            )
        )
    if status.print_error:
        candidates.append(
            (
                f"error:{status.print_error}",
                Event(
                    "alert",
                    "critical",
                    "Printer error",
                    f"Error code {status.print_error}; see the printer screen.",
                ),
            )
        )
    candidates.extend(
        (f"hms:{code}", Event("alert", "warning", "Printer warning", f"HMS code {code}."))
        for code in status.hms
    )
    if (
        status.nozzle_temp is not None
        and status.nozzle_temp > limits.nozzle_c + TEMPERATURE_MARGIN_C
    ):
        candidates.append(
            (
                "nozzle-temp",
                Event(
                    "alert",
                    "critical",
                    "Nozzle too hot",
                    f"Nozzle at {status.nozzle_temp:.0f} °C, "
                    f"above the {limits.nozzle_c:.0f} °C rating.",
                ),
            )
        )
    if status.bed_temp is not None and status.bed_temp > limits.bed_c + TEMPERATURE_MARGIN_C:
        candidates.append(
            (
                "bed-temp",
                Event(
                    "alert",
                    "critical",
                    "Bed too hot",
                    f"Bed at {status.bed_temp:.0f} °C, above the {limits.bed_c:.0f} °C rating.",
                ),
            )
        )
    if status.state == "RUNNING" and _minutes_since(state.last_change_at, now) >= STALL_MINUTES:
        candidates.append(
            (
                "stall",
                Event(
                    "alert",
                    "warning",
                    "Print may be stuck",
                    f"No new layer and no change in time left for {STALL_MINUTES}+ minutes "
                    f"(layer {status.layer}/{status.total_layers}).",
                ),
            )
        )
    if status.state != "PAUSE" and "pause" in state.announced:
        state.announced.remove("pause")  # a later pause is news again

    events: list[Event] = []
    for key, event in candidates:
        if key not in state.announced:
            state.announced.append(key)
            events.append(event)
    return events


def _track_movement(status: PrinterStatus, state: MonitorState, now: float) -> None:
    if (status.layer, status.remaining_min) != (state.last_layer, state.last_remaining):
        state.last_layer, state.last_remaining = status.layer, status.remaining_min
        state.last_change_at = now
        if "stall" in state.announced:
            state.announced.remove("stall")


def _minutes_since(then: float | None, now: float) -> float:
    return (now - then) / 60 if then is not None else float("inf")


def _summary(status: PrinterStatus) -> str:
    parts: list[str] = []
    if status.file:
        parts.append(status.file)
    if status.progress_pct is not None:
        parts.append(f"{status.progress_pct}%")
    if status.layer is not None and status.total_layers:
        parts.append(f"layer {status.layer}/{status.total_layers}")
    if status.remaining_min is not None:
        hours, minutes = divmod(status.remaining_min, 60)
        parts.append(f"{hours} h {minutes:02d} min left" if hours else f"{minutes} min left")
    return " · ".join(parts) or status.state
