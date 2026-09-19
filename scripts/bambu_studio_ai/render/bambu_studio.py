"""Bambu Studio backend: the slicer's own plate thumbnail via ``--export-png``.

Fast (about 0.4 s) and shows the model exactly as Bambu Studio imports it, but flat
shaded in the default filament colour, at a fixed 512 x 512, and only from Bambu
Studio's camera presets. Its left/right presets are flat silhouettes and it has no top
view, so this backend only draws the perspective view.

Bambu Studio writes ``result.json`` into its working directory (even for ``--help``),
so it always runs inside a scratch directory.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Final

from bambu_studio_ai.render.errors import BackendError

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

SUPPORTED_VIEWS: Final = frozenset({"perspective"})
IMPORT_FORMATS: Final = frozenset({".stl", ".obj", ".3mf", ".step", ".stp", ".amf", ".glb"})
_CAMERA_VIEW: Final = {"perspective": 0}  # 0 = Iso in `--camera-view`
_TIMEOUT_S: Final = 45.0


def find_bambu_studio_cli() -> list[str] | None:
    """The command that runs Bambu Studio's command-line mode, or None if not installed."""
    system = platform.system()
    if system == "Darwin":
        candidates = [
            Path("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"),
            Path.home() / "Applications/BambuStudio.app/Contents/MacOS/BambuStudio",
        ]
    elif system == "Windows":
        program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        candidates = [program_files / "Bambu Studio" / "bambu-studio.exe"]
    else:
        candidates = []
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]
    for name in ("bambu-studio", "BambuStudio"):
        found = shutil.which(name)
        if found:
            return [found]
    return None


def render_view(cli: Sequence[str], model: Path, view: str, workdir: Path) -> Path:
    """Render one view of ``model``; returns the RGBA PNG Bambu Studio wrote.

    Raises:
        BackendError: Bambu Studio failed, timed out or wrote no image.
    """
    if view not in SUPPORTED_VIEWS:
        raise BackendError(f"Bambu Studio can't render the {view} view")
    out = workdir / f"bambu_studio_{view}"
    out.mkdir(parents=True, exist_ok=True)
    camera = _CAMERA_VIEW[view]
    command = [
        *cli,
        "--export-png",
        "0",
        "--camera-view",
        str(camera),
        "--outputdir",
        str(out),
        str(model),
    ]
    logger.debug("running %s", " ".join(command))
    try:
        result = subprocess.run(  # noqa: S603  (fixed argv, no shell)
            command,
            cwd=out,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackendError(f"Bambu Studio did not finish within {_TIMEOUT_S:.0f} s") from exc
    except OSError as exc:
        raise BackendError(f"could not run Bambu Studio: {exc}") from exc
    image = out / f"plate_1_{camera}.png"
    if result.returncode != 0 or not image.is_file():
        raise BackendError(_failure(out, result.returncode, result.stdout + result.stderr))
    return image


def _failure(out: Path, returncode: int, output: str) -> str:
    try:
        reason = json.loads((out / "result.json").read_text(encoding="utf-8")).get("error_string")
    except (OSError, ValueError):
        reason = None
    if not reason:
        lines = [line for line in output.splitlines() if line.strip()]
        reason = lines[-1] if lines else "no output"
    return f"Bambu Studio exited with {returncode}: {reason}"
