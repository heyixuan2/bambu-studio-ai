"""Meshy (https://docs.meshy.ai, checked 2026-09-19).

- Text-to-3D is two paid tasks on ``/openapi/v2/text-to-3d``: a *preview* (untextured
  mesh, 20 credits) and a *refine* that textures it (10 credits). The refine is only
  started when a textured GLB is wanted.
- Image-to-3D is one task on ``/openapi/v1/image-to-3d``. Meshy has no upload endpoint:
  a local image is sent inline as a base64 data URI. It has no prompt field.
- Finished tasks list download URLs per format in ``model_urls`` (GLB, FBX, OBJ, USDZ,
  STL by default; 3MF only when requested in ``target_formats``). ``/openapi/v1/convert``
  (1 credit) converts an existing task when a format is missing.
- Statuses: PENDING, IN_PROGRESS, SUCCEEDED, FAILED, CANCELED.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

from bambu_studio_ai.generation.errors import InputError, ProviderError
from bambu_studio_ai.generation.inputs import data_uri
from bambu_studio_ai.generation.providers.base import (
    Fetched,
    FollowUp,
    GenerationRequest,
    OutputFormat,
    TaskRef,
    TaskState,
    TaskStatus,
)
from bambu_studio_ai.generation.providers.outputs import fetch_listed_output

if TYPE_CHECKING:
    from pathlib import Path

    from bambu_studio_ai.generation.http import HttpClient

BASE_URL = "https://api.meshy.ai/openapi"
#: Meshy's alias for its newest model (``meshy-7.1`` as of 2026-09-18). Pinning a
#: version would break when Meshy retires it, as it did ``meshy-5`` on 2026-09-16.
DEFAULT_MODEL = "latest"
IMAGE_TYPES = frozenset({"image/png", "image/jpeg"})

# Token kinds: "text" = preview whose refine (texture) is still wanted, "preview" = text
# task without texture, "refine" = texture task, "image", "convert".
_ROUTES = {
    "text": "v2/text-to-3d",
    "preview": "v2/text-to-3d",
    "refine": "v2/text-to-3d",
    "image": "v1/image-to-3d",
    "convert": "v1/convert",
}
_STATES = {
    "PENDING": TaskState.QUEUED,
    "IN_PROGRESS": TaskState.RUNNING,
    "SUCCEEDED": TaskState.SUCCEEDED,
    "FAILED": TaskState.FAILED,
    "CANCELED": TaskState.CANCELLED,
    "CANCELLED": TaskState.CANCELLED,
}


class MeshyProvider:
    """Meshy text-to-3D and image-to-3D."""

    name = "meshy"
    image_prompt_supported = False
    poll_interval_s = 5.0
    max_poll_interval_s = 20.0

    def __init__(self, api_key: str, http: HttpClient) -> None:
        """Create a client using ``api_key`` (sent only in the Authorization header)."""
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http

    def submit_text(self, request: GenerationRequest) -> TaskRef:
        """Start the preview task; the refine follows via :meth:`follow_up`."""
        if not request.prompt:
            raise InputError("a text prompt is required")
        body: dict[str, Any] = {
            "mode": "preview",
            "prompt": request.prompt,
            "ai_model": request.model or DEFAULT_MODEL,
        }
        _add_target_formats(body, request.output_format)
        task_id = self._create("v2/text-to-3d", body)
        return TaskRef(self.name, "text" if request.texture else "preview", (task_id,))

    def submit_image(self, request: GenerationRequest) -> TaskRef:
        """Start an image-to-3D task (a local image is sent as a data URI)."""
        image = request.image
        if image is None:
            raise InputError("an image is required")
        if image.url is not None:
            image_url = image.url
        elif image.mime in IMAGE_TYPES:
            image_url = data_uri(image)
        else:
            raise InputError(f"Meshy accepts PNG or JPEG images, not {image.mime}")
        body: dict[str, Any] = {
            "image_url": image_url,
            "ai_model": request.model or DEFAULT_MODEL,
            "should_texture": request.texture,
        }
        _add_target_formats(body, request.output_format)
        return TaskRef(self.name, "image", (self._create("v1/image-to-3d", body),))

    def poll(self, ref: TaskRef) -> TaskStatus:
        """Read the task (never starts the refine; see :meth:`follow_up`)."""
        route = _ROUTES.get(ref.kind)
        if route is None:
            raise InputError(f"unknown Meshy task kind {ref.kind!r}")
        data = self._http.get_json(
            f"{BASE_URL}/{route}/{quote(ref.primary_id, safe='')}", headers=self._headers
        )
        return parse_task(data)

    def follow_up(
        self, ref: TaskRef, status: TaskStatus, output_format: OutputFormat, *, texture: bool
    ) -> FollowUp | None:
        """Refine for a textured GLB; server-side conversion when a format is missing."""
        if ref.kind == "text" and output_format == "glb" and texture:
            return FollowUp(
                key=f"{ref.token}>refine",
                action="refine",
                source=ref,
                description="Meshy texture step (refine, 10 credits)",
            )
        if output_format != "glb" and output_format not in status.outputs and ref.kind != "convert":
            return FollowUp(
                key=f"{ref.token}>convert:{output_format}",
                action=f"convert:{output_format}",
                source=ref,
                description=f"Meshy server-side {output_format.upper()} conversion (1 credit)",
            )
        return None

    def start_follow_up(self, step: FollowUp) -> TaskRef:
        """Start the refine or conversion task."""
        source_id = step.source.primary_id
        if step.action == "refine":
            # ai_model is omitted so the refine inherits the preview's model.
            body: dict[str, Any] = {"mode": "refine", "preview_task_id": source_id}
            return TaskRef(self.name, "refine", (self._create("v2/text-to-3d", body),))
        if step.action.startswith("convert:"):
            target = step.action.split(":", 1)[1]
            body = {"input_task_id": source_id, "target_formats": [target]}
            return TaskRef(self.name, "convert", (self._create("v1/convert", body),))
        raise InputError(f"unknown Meshy step {step.action!r}")

    def fetch(self, ref: TaskRef, output_format: OutputFormat, dest_dir: Path) -> Fetched:
        """Download from ``model_urls`` (expired links are refreshed by polling again)."""
        return fetch_listed_output(
            self._http,
            lambda: self.poll(ref),
            wanted=output_format,
            dest_dir=dest_dir,
            stem=f"meshy_{ref.primary_id}",
        )

    def _create(self, route: str, body: dict[str, Any]) -> str:
        data = self._http.post_json(f"{BASE_URL}/{route}", headers=self._headers, json=body)
        task_id = cast("dict[str, Any]", data).get("result") if isinstance(data, dict) else None
        if not isinstance(task_id, str) or not task_id:
            raise ProviderError(
                "bad_response", f"Meshy returned no task id: {str(cast(object, data))[:120]}"
            )
        return task_id


def parse_task(data: object) -> TaskStatus:
    """Normalise a Meshy task object."""
    if not isinstance(data, dict):
        raise ProviderError("bad_response", "Meshy returned a task that is not a JSON object")
    task = cast("dict[str, Any]", data)
    raw = str(task.get("status", ""))
    state = _STATES.get(raw.upper(), TaskState.RUNNING)
    error = task.get("task_error")
    message = ""
    if isinstance(error, dict):
        message = str(cast("dict[str, Any]", error).get("message") or "")
    if state is TaskState.RUNNING and raw.upper() not in _STATES:
        message = f"unrecognised Meshy status {raw!r}"
    elif state is TaskState.CANCELLED:
        message = message or "the task was cancelled at Meshy"
    urls = task.get("model_urls")
    outputs: dict[str, str] = {}
    if isinstance(urls, dict):
        outputs = {
            str(key): value
            for key, value in cast("dict[str, object]", urls).items()
            if isinstance(value, str) and value
        }
    progress = task.get("progress")
    return TaskStatus(
        state=state,
        progress=int(progress) if isinstance(progress, (int, float)) else None,
        message=message,
        raw_status=raw,
        outputs=outputs,
    )


def _add_target_formats(body: dict[str, Any], output_format: OutputFormat) -> None:
    # Omitted, Meshy returns every format except 3MF, which must be asked for.
    if output_format == "3mf":
        body["target_formats"] = ["glb", "3mf"]
