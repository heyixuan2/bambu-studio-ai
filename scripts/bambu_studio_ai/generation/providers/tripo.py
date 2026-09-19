"""Tripo API v3 (https://developers.tripo3d.ai/en/docs, checked 2026-09-19).

Tripo's v2 API (``api.tripo3d.ai/v2/openapi``) stops accepting requests on 2026-11-01;
this module uses only v3:

- ``POST /v3/generation/text-to-model`` and ``/image-to-model`` → ``data.task_id``.
  Image input is one ``input`` string: a public URL, or a ``file_token`` from
  ``POST /v3/files`` (multipart upload). Image-to-model has no prompt field.
- ``GET /v3/tasks/{id}`` → ``status`` (queued, running, success, failed, cancelled,
  banned, expired; v2 also documented ``unknown``) and ``output.model_url`` (a GLB).
  Download links expire within minutes, so they are re-read from the task when needed.
- ``POST /v3/models/convert`` (5 credits) turns a finished model into STL or 3MF.
- Every response is ``{"code": 0, "data": …}``; errors carry ``code``, ``message``
  and ``suggestion``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from bambu_studio_ai.generation.errors import InputError, ProviderError
from bambu_studio_ai.generation.inputs import upload_name
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

BASE_URL = "https://openapi.tripo3d.ai/v3"
#: Current H-series model per the text-to-model reference (quick-start examples also
#: use the alias ``tripo-v3.1``). ``--model`` overrides it.
DEFAULT_MODEL = "v3.1-20260211"
#: Formats ``/v3/models/convert`` produces for printing (geometry only).
SERVER_FORMATS = frozenset({"stl", "3mf"})
#: ``POST /v3/files`` takes JPEG and PNG (image-to-model also reads WebP, but only by URL).
UPLOAD_TYPES = frozenset({"image/png", "image/jpeg"})

_STATES = {
    "queued": TaskState.QUEUED,
    "running": TaskState.RUNNING,
    "success": TaskState.SUCCEEDED,
    "failed": TaskState.FAILED,
    "cancelled": TaskState.CANCELLED,
    "banned": TaskState.REJECTED,
    "expired": TaskState.EXPIRED,
    "unknown": TaskState.FAILED,
}
_STATE_NOTES = {
    "banned": "Tripo rejected the input under its content policy; change the prompt or image",
    "expired": "the task expired at Tripo and its files are gone",
    "cancelled": "the task was cancelled at Tripo (its credits are refunded)",
    "unknown": "Tripo reports the task status as unknown; contact Tripo support with the task id",
}
_OUTPUT_KEYS = ("model_url", "pbr_model", "model", "base_model")


class TripoProvider:
    """Tripo v3 text-to-model and image-to-model."""

    name = "tripo"
    image_prompt_supported = False
    poll_interval_s = 3.0
    max_poll_interval_s = 15.0

    def __init__(self, api_key: str, http: HttpClient) -> None:
        """Create a client using ``api_key`` (sent only in the Authorization header)."""
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http

    def submit_text(self, request: GenerationRequest) -> TaskRef:
        """Start a text-to-model task."""
        if not request.prompt:
            raise InputError("a text prompt is required")
        body = {"prompt": request.prompt, **self._common(request)}
        return self._create("generation/text-to-model", body)

    def submit_image(self, request: GenerationRequest) -> TaskRef:
        """Start an image-to-model task, uploading a local image first."""
        image = request.image
        if image is None:
            raise InputError("an image is required")
        if image.url is not None:
            source = image.url
        else:
            if image.data is None or image.mime not in UPLOAD_TYPES:
                raise InputError(f"Tripo's upload accepts PNG or JPEG images, not {image.mime}")
            files = [("file", (upload_name(image), image.data, image.mime))]
            uploaded = _data(
                self._http.post_json(f"{BASE_URL}/files", headers=self._headers, files=files)
            )
            source = str(uploaded.get("file_token") or "")
            if not source:
                raise ProviderError("bad_response", "Tripo's upload returned no file_token")
        return self._create("generation/image-to-model", {"input": source, **self._common(request)})

    def poll(self, ref: TaskRef) -> TaskStatus:
        """Read the task."""
        url = f"{BASE_URL}/tasks/{quote(ref.primary_id, safe='')}"
        task = _data(self._http.get_json(url, headers=self._headers))
        converted = ref.ids[1] if ref.kind == "convert" and len(ref.ids) > 1 else ""
        target = cast("OutputFormat", converted) if converted in SERVER_FORMATS else None
        return parse_task(task, converted_format=target)

    def follow_up(
        self, ref: TaskRef, status: TaskStatus, output_format: OutputFormat, *, texture: bool
    ) -> FollowUp | None:
        """A server-side STL/3MF conversion; other formats need none."""
        del texture  # Tripo textures in the same task
        if (
            ref.kind != "task"
            or output_format not in SERVER_FORMATS
            or output_format in status.outputs
        ):
            return None
        return FollowUp(
            key=f"{ref.token}>convert:{output_format}",
            action=f"convert:{output_format}",
            source=ref,
            description=f"Tripo server-side {output_format.upper()} conversion (5 credits)",
        )

    def start_follow_up(self, step: FollowUp) -> TaskRef:
        """Start the conversion task."""
        target = step.action.split(":", 1)[1]
        if not step.action.startswith("convert:") or target not in SERVER_FORMATS:
            raise InputError(f"unknown Tripo step {step.action!r}")
        body = {"input": step.source.primary_id, "format": target.upper()}
        created = self._create("models/convert", body)
        return TaskRef(self.name, "convert", (created.primary_id, target))

    def fetch(self, ref: TaskRef, output_format: OutputFormat, dest_dir: Path) -> Fetched:
        """Download ``output.model_url``, re-reading the task if the link has expired."""
        return fetch_listed_output(
            self._http,
            lambda: self.poll(ref),
            wanted=output_format,
            dest_dir=dest_dir,
            stem=f"tripo_{ref.primary_id}",
        )

    def _common(self, request: GenerationRequest) -> dict[str, Any]:
        body: dict[str, Any] = {"model": request.model or DEFAULT_MODEL}
        if not request.texture:
            body.update(texture=False, pbr=False)  # pbr=true would force texture back on
        return body

    def _create(self, route: str, body: dict[str, Any]) -> TaskRef:
        data = _data(self._http.post_json(f"{BASE_URL}/{route}", headers=self._headers, json=body))
        task_id = data.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError("bad_response", f"Tripo returned no task_id: {str(data)[:120]}")
        return TaskRef(self.name, "task", (task_id,))


def parse_task(task: dict[str, Any], *, converted_format: OutputFormat | None = None) -> TaskStatus:
    """Normalise a Tripo v3 task object (the ``data`` of ``GET /v3/tasks/{id}``)."""
    raw = str(task.get("status", ""))
    state = _STATES.get(raw.lower(), TaskState.RUNNING)
    message = _STATE_NOTES.get(raw.lower(), "")
    if raw.lower() not in _STATES:
        message = f"unrecognised Tripo status {raw!r}"
    if task.get("error_message"):
        message = f"{task['error_message']} (error {task.get('error_code', '?')})"
    output = task.get("output")
    outputs: dict[str, str] = {}
    if isinstance(output, dict):
        fields = cast("dict[str, object]", output)
        url = next(
            (
                fields[key]
                for key in _OUTPUT_KEYS
                if isinstance(fields.get(key), str) and fields[key]
            ),
            None,
        )
        if isinstance(url, str):
            outputs[converted_format or format_from_name(url) or "glb"] = url
    progress = task.get("progress")
    return TaskStatus(
        state=state,
        progress=int(progress) if isinstance(progress, (int, float)) else None,
        message=message,
        raw_status=raw,
        outputs=outputs,
    )


def _data(body: object) -> dict[str, Any]:
    """The ``data`` object of a Tripo reply, or the reply's error as a ``ProviderError``."""
    if not isinstance(body, dict):
        raise ProviderError("bad_response", "Tripo returned a reply that is not a JSON object")
    reply = cast("dict[str, Any]", body)
    if reply.get("code", 0) != 0:
        suggestion = f". {reply['suggestion']}" if reply.get("suggestion") else ""
        raise ProviderError(
            str(reply.get("code")), f"{reply.get('message', 'Tripo error')}{suggestion}"
        )
    data = reply.get("data")
    if not isinstance(data, dict):
        raise ProviderError("bad_response", "Tripo returned no data object")
    return cast("dict[str, Any]", data)
