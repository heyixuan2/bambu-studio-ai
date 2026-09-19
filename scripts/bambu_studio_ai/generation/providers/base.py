"""The provider contract: typed requests, task references, statuses and results.

Every provider turns a request into a remote task, reports that task's status in the
terms defined here, and downloads the finished model. Adding a provider means one new
module implementing :class:`Provider` and one line in ``providers/__init__.py``.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Literal, Protocol

from bambu_studio_ai.generation.errors import InputError

if TYPE_CHECKING:
    from pathlib import Path

    from bambu_studio_ai.generation.inputs import ImageInput

OutputFormat = Literal["glb", "stl", "3mf", "obj"]
#: Formats the CLI offers. GLB is the provider's textured original; the rest carry no colour.
OUTPUT_FORMATS: tuple[OutputFormat, ...] = ("glb", "stl", "3mf", "obj")

_NAME = re.compile(r"[a-z0-9-]{1,32}")
_PLAIN_ID = re.compile(r"[A-Za-z0-9._=-]{1,4096}")
_ENCODED = "~"  # marks an id stored as base64url because it has other characters


class TaskState(str, Enum):
    """Provider-independent task state. Everything except QUEUED and RUNNING is final."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"
    """The provider refused the input (content policy)."""

    @property
    def terminal(self) -> bool:
        """Whether the task will not change state any more."""
        return self not in (TaskState.QUEUED, TaskState.RUNNING)


@dataclass(frozen=True)
class TaskRef:
    """Everything needed to find a remote task again, printable as one token.

    The token is ``provider:kind:id[:id…]`` (for example ``meshy:text:0193…`` or
    ``rodin:task:<uuid>:<subscription key>``), so ``generate.py status/download``
    can resume a task from another process with nothing but that string.
    """

    provider: str
    kind: str
    ids: tuple[str, ...]
    """The provider's own ids, raw. Providers quote them in URLs; file names are sanitised."""

    def __post_init__(self) -> None:
        """Reject names and ids that could not round-trip through a token."""
        for name in (self.provider, self.kind):
            if not _NAME.fullmatch(name):
                raise InputError(f"invalid task id part: {name[:40]!r}")
        if not self.ids or not all(0 < len(value) <= 4096 for value in self.ids):  # noqa: PLR2004
            raise InputError("a task id needs one or more provider ids of up to 4096 characters")

    @property
    def token(self) -> str:
        """The opaque string printed to the user."""
        return ":".join((self.provider, self.kind, *(_encode(value) for value in self.ids)))

    @property
    def primary_id(self) -> str:
        """The provider's own task id (the first id)."""
        return self.ids[0]

    @classmethod
    def parse(cls, token: str) -> TaskRef:
        """Parse a token printed by :attr:`token`.

        Raises:
            InputError: the string is not a task token.
        """
        parts = token.strip().split(":")
        if len(parts) < 3:  # noqa: PLR2004  (provider, kind, at least one id)
            raise InputError(
                f"not a task id: {token[:60]!r} "
                "(expected the provider:kind:id string printed by generate.py)"
            )
        return cls(parts[0], parts[1], tuple(_decode(part) for part in parts[2:]))


@dataclass(frozen=True)
class TaskStatus:
    """One observation of a remote task."""

    state: TaskState
    progress: int | None = None
    """0-100 when the provider reports it."""
    message: str = ""
    """The provider's failure reason or stage note, when there is one."""
    raw_status: str = ""
    """The vendor's own status string, for diagnostics."""
    outputs: Mapping[str, str] = field(default_factory=dict[str, str])
    """Download URLs by format (``"glb"``, ``"stl"``…), when the provider lists them."""


@dataclass(frozen=True)
class GenerationRequest:
    """What the user asked for. The prompt is sent exactly as written."""

    prompt: str | None
    image: ImageInput | None = None
    model: str | None = None
    """Provider model/tier override; ``None`` uses the provider's default."""
    output_format: OutputFormat = "glb"
    texture: bool = True
    """Whether to pay for a texture. Pipeline sets it False for colourless formats."""


@dataclass(frozen=True)
class FollowUp:
    """A further paid step needed before the requested file exists.

    Examples: Meshy's texture (refine) task after a preview, or a server-side format
    conversion. Starting one costs credits, so the pipeline records each started step
    and never starts the same one twice.
    """

    key: str
    """Stable identity of the step, e.g. ``"meshy:text:abc>refine"``."""
    action: str
    """Provider-specific action name, e.g. ``"refine"`` or ``"convert:stl"``."""
    source: TaskRef
    description: str
    """Human description including the cost, e.g. ``"texture step (10 credits)"``."""


@dataclass(frozen=True)
class Fetched:
    """A model file downloaded from a provider."""

    path: Path
    output_format: OutputFormat


class Provider(Protocol):
    """A text/image-to-3D service.

    Implementations must not print, must put a timeout on every network call, and must
    never start a paid task except in ``submit_*`` and ``start_follow_up``.
    """

    name: str
    image_prompt_supported: bool
    """Whether image-to-3D sends the optional ``--prompt`` to the provider."""
    poll_interval_s: float
    max_poll_interval_s: float

    def submit_text(self, request: GenerationRequest) -> TaskRef:
        """Start a text-to-3D task (costs credits)."""
        ...

    def submit_image(self, request: GenerationRequest) -> TaskRef:
        """Start an image-to-3D task (costs credits)."""
        ...

    def poll(self, ref: TaskRef) -> TaskStatus:
        """Read the task's current status. Never starts or changes anything."""
        ...

    def follow_up(
        self, ref: TaskRef, status: TaskStatus, output_format: OutputFormat, *, texture: bool
    ) -> FollowUp | None:
        """The paid step still needed after ``ref`` succeeded, if any. No network access."""
        ...

    def start_follow_up(self, step: FollowUp) -> TaskRef:
        """Start ``step`` (costs credits) and return the new task."""
        ...

    def fetch(self, ref: TaskRef, output_format: OutputFormat, dest_dir: Path) -> Fetched:
        """Download the finished model, in ``output_format`` if the provider has it, else GLB."""
        ...


def _encode(value: str) -> str:
    if _PLAIN_ID.fullmatch(value):
        return value
    return _ENCODED + base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _decode(part: str) -> str:
    if not part.startswith(_ENCODED):
        if not _PLAIN_ID.fullmatch(part):
            raise InputError(f"invalid task id part: {part[:40]!r}")
        return part
    body = part[len(_ENCODED) :]
    try:
        return base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise InputError(f"invalid task id part: {part[:40]!r}") from exc


def format_from_name(name: str) -> OutputFormat | None:
    """The output format a file name or URL path ends with, if it is one we handle."""
    lowered = name.lower().split("?", 1)[0]
    for candidate in OUTPUT_FORMATS:
        if lowered.endswith("." + candidate):
            return candidate
    return None
