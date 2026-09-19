"""Blender backend: run ``blender_scene.py`` in a Blender subprocess and read its report.

The first render on a GPU can take minutes on a new machine or Blender version: Cycles
compiles its GPU kernels once (about 105 s measured on an M2 Max with Metal) and caches
them. The default timeouts leave room for that, and the runner says so when a GPU
render is slow to produce its first frame.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Final

from bambu_studio_ai.render.errors import BackendError

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

SCENE_SCRIPT: Final = Path(__file__).with_name("blender_scene.py")
PROGRESS_PREFIX: Final = "BSA_PROGRESS "
KERNEL_HINT: Final = (
    "the first GPU render on a machine compiles Cycles' GPU kernels once "
    "(about 2 minutes; cached afterwards)"
)
_FIRST_FRAME_PATIENCE_S: Final = 20.0
_POLL_S: Final = 0.5
_TAIL_LINES: Final = 30


@dataclass(frozen=True)
class BlenderJob:
    """What to render: either named views or a turntable with ``turntable`` frames."""

    model: Path
    workdir: Path
    views: tuple[str, ...] = ()
    turntable: int = 0
    size: int = 800
    samples: int = 48
    cpu_only: bool = False

    @property
    def json_out(self) -> Path:
        """Where the Blender script writes its report."""
        return self.workdir / "blender_report.json"

    @property
    def frame_dir(self) -> Path:
        """Where the Blender script writes its frames."""
        return self.workdir / "frames"


@dataclass(frozen=True)
class BlenderReport:
    """What Blender measured and rendered."""

    frames: tuple[Path, ...]
    dimensions: tuple[float, float, float]
    faces: int
    material: str
    device: str
    version: str


def build_command(blender: Sequence[str], job: BlenderJob) -> list[str]:
    """The Blender command line for ``job`` (the script's own args follow ``--``).

    ``blender`` is the command that starts Blender, usually just its path.
    """
    command = [
        *blender,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(SCENE_SCRIPT),
        "--",
        "--model",
        str(job.model),
        "--out-dir",
        str(job.frame_dir),
        "--json-out",
        str(job.json_out),
        "--size",
        str(job.size),
        "--samples",
        str(job.samples),
    ]
    command += ["--turntable", str(job.turntable)] if job.turntable else ["--views", *job.views]
    if job.cpu_only:
        command.append("--cpu")
    return command


class _Watcher:
    """Reads Blender's output on a thread: keeps a tail for errors, tracks progress."""

    def __init__(self, stream: IO[str] | None, frames: int) -> None:
        self.tail: deque[str] = deque(maxlen=_TAIL_LINES)
        self.device: str | None = None
        self.done = 0
        self.frames = frames
        self._stream = stream
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        for raw in self._stream or ():
            line = raw.rstrip()
            if not line.startswith(PROGRESS_PREFIX):
                self.tail.append(line)
                continue
            try:
                event = json.loads(line[len(PROGRESS_PREFIX) :])
            except ValueError:
                self.tail.append(line)
                continue
            if event.get("stage") == "device":
                self.device = str(event.get("device"))
            elif event.get("stage") == "frame":
                self.done = int(event.get("index", 0))
                if self.frames > 1:
                    logger.info("  frame %d/%d (%.1f s)", self.done, self.frames, event["seconds"])


def run(blender: Sequence[str], job: BlenderJob, timeout_s: float) -> BlenderReport:
    """Render ``job`` with Blender and return its report.

    Raises:
        BackendError: Blender failed, timed out or wrote no usable report.
    """
    job.frame_dir.mkdir(parents=True, exist_ok=True)
    frames = job.turntable or len(job.views)
    command = build_command(blender, job)
    logger.debug("running %s", " ".join(command))
    started = time.monotonic()
    process = subprocess.Popen(  # noqa: S603  (fixed argv, no shell)
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
    )
    watcher = _Watcher(process.stdout, frames)
    warned = False
    try:
        while process.poll() is None:
            elapsed = time.monotonic() - started
            if elapsed > timeout_s:
                raise BackendError(_timeout_message(timeout_s, watcher))
            if not warned and _waiting_for_gpu(watcher) and elapsed > _FIRST_FRAME_PATIENCE_S:
                logger.info("Still waiting for the first frame: %s.", KERNEL_HINT)
                warned = True
            time.sleep(_POLL_S)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        watcher.thread.join(timeout=5)
    return _read_report(job, process.returncode, watcher)


def _timeout_message(timeout_s: float, watcher: _Watcher) -> str:
    message = (
        f"Blender did not finish within {timeout_s:.0f} s ({watcher.done}/{watcher.frames} frames)"
    )
    if _waiting_for_gpu(watcher):
        message += f"; {KERNEL_HINT}, so try again, raise --timeout, or pass --cpu"
    return message


def _waiting_for_gpu(watcher: _Watcher) -> bool:
    return watcher.device not in (None, "CPU") and watcher.done == 0


def _read_report(job: BlenderJob, returncode: int, watcher: _Watcher) -> BlenderReport:
    tail = "\n".join(line for line in watcher.tail if line.strip())
    try:
        data = json.loads(job.json_out.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackendError(
            f"Blender exited with {returncode} and no report: {tail[-600:]}"
        ) from exc
    if not data.get("ok"):
        logger.debug("Blender traceback:\n%s", data.get("traceback", ""))
        raise BackendError(str(data.get("error", "unknown error")))
    frames = tuple(Path(frame["path"]) for frame in data["frames"])
    missing = [p.name for p in frames if not p.is_file()]
    if missing:
        raise BackendError(f"Blender reported frames it did not write: {', '.join(missing)}")
    x, y, z = (float(v) for v in data["dimensions"])
    return BlenderReport(
        frames=frames,
        dimensions=(x, y, z),
        faces=int(data["faces"]),
        material=str(data["material"]),
        device=str(data["device"]),
        version=str(data.get("blender_version", "")),
    )
