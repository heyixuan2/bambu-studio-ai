"""Hyper3D Rodin (https://docs.hyper3d.ai, checked 2026-09-19). Needs a Rodin API plan.

- ``POST /api/v2/rodin`` (multipart form) starts a task. ``tier`` must be sent: without
  it Rodin falls back to the legacy Gen-1 ``Regular`` tier. The output format is chosen
  here (``geometry_file_format``: glb, stl, obj, fbx, usdz; no 3MF).
- The reply carries ``uuid`` (for downloads) and ``jobs.subscription_key`` (for status);
  both go into the task id this module prints.
- Rejections come back as HTTP 201 with an ``error`` field, so every reply body is checked.
- ``POST /api/v2/status`` lists jobs as Waiting, Generating, Done or Failed;
  ``POST /api/v2/download`` lists ``{name, url}`` files once every job is Done.
- Image-to-3D accepts an optional prompt; images must be uploaded (no URL field).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from bambu_studio_ai.generation.errors import InputError, ProviderError
from bambu_studio_ai.generation.inputs import fetch_image, upload_name
from bambu_studio_ai.generation.providers.base import (
    Fetched,
    FollowUp,
    GenerationRequest,
    OutputFormat,
    TaskRef,
    TaskState,
    TaskStatus,
    format_from_name,
)
from bambu_studio_ai.generation.providers.outputs import fetch_listed_output

if TYPE_CHECKING:
    from pathlib import Path

    from bambu_studio_ai.generation.http import HttpClient

BASE_URL = "https://api.hyper3d.com/api/v2"
#: Gen-2.5 (May 2026) "balanced structure and detail"; 0.5 credits like every Gen-2.5
#: tier except Extreme-High. ``--model`` or the ``rodin_tier`` setting overrides it.
DEFAULT_TIER = "Gen-2.5-Medium"
#: Formats Rodin can produce directly (it has no 3MF).
SERVER_FORMATS = frozenset({"glb", "stl", "obj"})

_Form = list[tuple[str, tuple[str | None, bytes | str, str | None]]]


class RodinProvider:
    """Rodin text-to-3D and image-to-3D."""

    name = "rodin"
    image_prompt_supported = True
    # Rodin asks clients to wait ~5 s before the first status call and back off to 30 s.
    poll_interval_s = 5.0
    max_poll_interval_s = 30.0

    def __init__(self, api_key: str, http: HttpClient, *, default_tier: str | None = None) -> None:
        """Create a client; ``default_tier`` comes from the user's ``rodin_tier`` setting."""
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http
        self._default_tier = default_tier or DEFAULT_TIER

    def submit_text(self, request: GenerationRequest) -> TaskRef:
        """Start a text-to-3D task."""
        if not request.prompt:
            raise InputError("a text prompt is required")
        return self._submit([("prompt", (None, request.prompt, None)), *self._options(request)])

    def submit_image(self, request: GenerationRequest) -> TaskRef:
        """Start an image-to-3D task (a URL image is downloaded and uploaded)."""
        if request.image is None:
            raise InputError("an image is required")
        image = fetch_image(self._http, request.image)
        if image.data is None:
            raise InputError("the image has no data")
        form: _Form = [("images", (upload_name(image), image.data, image.mime))]
        if request.prompt:
            form.append(("prompt", (None, request.prompt, None)))
        return self._submit([*form, *self._options(request)])

    def poll(self, ref: TaskRef) -> TaskStatus:
        """Read the status of every job in the task."""
        _uuid, subscription_key = _split(ref)
        body = self._http.post_json(
            f"{BASE_URL}/status", headers=self._headers, json={"subscription_key": subscription_key}
        )
        return parse_status(body)

    def follow_up(
        self, ref: TaskRef, status: TaskStatus, output_format: OutputFormat, *, texture: bool
    ) -> FollowUp | None:
        """Rodin picks the format when the task is submitted, so there is never a second step."""
        del ref, status, output_format, texture
        return None

    def start_follow_up(self, step: FollowUp) -> TaskRef:
        """Not used: Rodin has no follow-up steps."""
        raise InputError(f"Rodin has no follow-up step {step.action!r}")

    def fetch(self, ref: TaskRef, output_format: OutputFormat, dest_dir: Path) -> Fetched:
        """Download the model file from the task's file list (never a texture or preview)."""
        task_uuid, _key = _split(ref)

        def listing() -> TaskStatus:
            body = self._http.post_json(
                f"{BASE_URL}/download", headers=self._headers, json={"task_uuid": task_uuid}
            )
            return TaskStatus(TaskState.SUCCEEDED, outputs=parse_file_list(body))

        return fetch_listed_output(
            self._http, listing, wanted=output_format, dest_dir=dest_dir, stem=f"rodin_{task_uuid}"
        )

    def _options(self, request: GenerationRequest) -> _Form:
        geometry = request.output_format if request.output_format in SERVER_FORMATS else "glb"
        return [
            ("tier", (None, request.model or self._default_tier, None)),
            ("geometry_file_format", (None, geometry, None)),
            ("material", (None, "PBR" if request.texture else "None", None)),
        ]

    def _submit(self, form: _Form) -> TaskRef:
        # Rodin requires multipart/form-data even for text-only requests.
        body = _checked(
            self._http.post_json(f"{BASE_URL}/rodin", headers=self._headers, files=form)
        )
        task_uuid = body.get("uuid")
        jobs = body.get("jobs")
        key = (
            cast("dict[str, Any]", jobs).get("subscription_key") if isinstance(jobs, dict) else None
        )
        if not isinstance(task_uuid, str) or not task_uuid or not isinstance(key, str) or not key:
            raise ProviderError(
                "bad_response", "Rodin accepted the request but returned no task id"
            )
        return TaskRef(self.name, "task", (task_uuid, key))


def parse_status(body: object) -> TaskStatus:
    """Combine a ``/status`` reply's jobs into one task status."""
    reply = _as_dict(body)
    if reply.get("error") == "NO_SUCH_TASK":
        return TaskStatus(
            TaskState.EXPIRED,
            message="Rodin has no such task (it expired, or the id is wrong)",
            raw_status="NO_SUCH_TASK",
        )
    reply = _checked(reply)
    listed = cast("list[object]", reply.get("jobs") or [])
    jobs = [cast("dict[str, Any]", job) for job in listed if isinstance(job, dict)]
    states = [str(job.get("status", "")) for job in jobs]
    raw = ",".join(states)
    done = states.count("Done")
    if "Failed" in states:
        return TaskStatus(TaskState.FAILED, message="a Rodin job failed", raw_status=raw)
    if states and done == len(states):
        return TaskStatus(TaskState.SUCCEEDED, progress=100, raw_status=raw)
    progress = int(100 * done / len(states)) if states else 0
    if "Generating" in states or done:
        return TaskStatus(TaskState.RUNNING, progress=progress, raw_status=raw)
    queue = next(
        (job.get("queue_length") for job in jobs if job.get("queue_length") is not None), None
    )
    message = f"{queue} jobs ahead in the queue" if queue is not None else ""
    return TaskStatus(TaskState.QUEUED, progress=progress, message=message, raw_status=raw)


def parse_file_list(body: object) -> dict[str, str]:
    """Model URLs by format from a ``/download`` reply (textures and previews are skipped)."""
    reply = _checked(_as_dict(body))
    outputs: dict[str, str] = {}
    for item in cast("list[object]", reply.get("list") or []):
        if not isinstance(item, dict):
            continue
        entry = cast("dict[str, Any]", item)
        name, url = str(entry.get("name", "")), entry.get("url")
        found = format_from_name(name)
        if found and isinstance(url, str) and url and found not in outputs:
            outputs[found] = url
    return outputs


def _split(ref: TaskRef) -> tuple[str, str]:
    if ref.kind != "task" or len(ref.ids) != 2:  # noqa: PLR2004  (uuid, subscription key)
        raise InputError("a Rodin task id has the form rodin:task:<uuid>:<subscription key>")
    return ref.ids[0], ref.ids[1]


def _as_dict(body: object) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ProviderError("bad_response", "Rodin returned a reply that is not a JSON object")
    return cast("dict[str, Any]", body)


def _checked(body: object) -> dict[str, Any]:
    """Raise the ``error`` Rodin reports inside a successful (HTTP 201) reply."""
    reply = _as_dict(body)
    error = reply.get("error")
    if error:
        raise ProviderError(str(error), str(reply.get("message") or "Rodin rejected the request"))
    return reply
