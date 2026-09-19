"""Pick a renderer, render the requested views and write the preview file.

Renderers are tried in order, best first: Blender (Cycles, materials and textures),
Bambu Studio (``--export-png``: flat, fast, perspective only) and the built-in software
renderer (numpy + Pillow, always available). A renderer is skipped when it isn't
installed or can't draw the request, and the next one takes over when one fails.
"""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from PIL import Image

from bambu_studio_ai.render import bambu_studio, blender, compose, meshes, software
from bambu_studio_ai.render.errors import (
    BackendError,
    ModelError,
    RendererMissingError,
    RenderFailedError,
    RequestError,
)
from bambu_studio_ai.render.views import (
    GRID_VIEWS,
    TURNTABLE_FRAMES,
    VIEW_LABELS,
    turntable_directions,
    view_direction,
)

if TYPE_CHECKING:
    from bambu_studio_ai.render.meshes import LoadedModel

logger = logging.getLogger(__name__)

MODES: Final = (*GRID_VIEWS, "all", "turntable")
RENDERERS: Final = ("blender", "bambu-studio", "software")
RENDERER_NAMES: Final = {
    "blender": "Blender",
    "bambu-studio": "Bambu Studio",
    "software": "software",
}
HEIGHT_TOLERANCE_PCT: Final = 10.0
STILL_SIZE: Final = 800
TILE_SIZE: Final = 600
TURNTABLE_SIZE: Final = 600
BLENDER_INSTALL: Final = (
    "install Blender 4+ from https://www.blender.org/download/ (macOS: brew install --cask blender)"
)
BAMBU_STUDIO_INSTALL: Final = "install Bambu Studio from https://bambulab.com/en/download/studio"


@dataclass(frozen=True)
class Tools:
    """External programs found on this machine (None when not installed)."""

    blender: str | None = None
    bambu_studio: tuple[str, ...] | None = None


@dataclass(frozen=True)
class PreviewRequest:
    """One preview to make."""

    model: Path
    output: Path
    mode: str = "perspective"
    expected_height_mm: float | None = None
    renderer: str = "auto"
    timeout_s: float | None = None
    cpu_only: bool = False


@dataclass(frozen=True)
class HeightCheck:
    """The model's Z extent compared with the height the user asked for."""

    expected_mm: float
    actual_mm: float

    @property
    def diff_pct(self) -> float:
        """How far off the height is, in percent of the expected height."""
        return abs(self.actual_mm - self.expected_mm) / self.expected_mm * 100

    @property
    def ok(self) -> bool:
        """Within the tolerance."""
        return self.diff_pct <= HEIGHT_TOLERANCE_PCT

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "expected_mm": self.expected_mm,
            "actual_mm": round(self.actual_mm, 2),
            "diff_pct": round(self.diff_pct, 1),
            "ok": self.ok,
        }


@dataclass(frozen=True)
class PreviewResult:
    """What was written and what was measured."""

    output_file: Path
    renderer: str
    views: tuple[str, ...]
    dimensions_mm: tuple[float, float, float]
    faces: int
    material: str
    device: str | None = None
    height_check: HeightCheck | None = None
    warnings: tuple[str, ...] = ()
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form (the ``--json`` output)."""
        return {
            "output_file": str(self.output_file),
            "renderer": self.renderer,
            "views": list(self.views),
            "dimensions_mm": [round(v, 3) for v in self.dimensions_mm],
            "faces": self.faces,
            "material": self.material,
            "device": self.device,
            "height_check": self.height_check.to_dict() if self.height_check else None,
            "warnings": list(self.warnings),
            "seconds": round(self.seconds, 1),
        }


@dataclass
class _Rendered:
    frames: list[Image.Image]
    material: str
    dimensions: tuple[float, float, float] | None = None
    faces: int | None = None
    device: str | None = None


def frame_views(mode: str) -> tuple[str, ...]:
    """The named views a mode renders (a turntable has none)."""
    if mode == "all":
        return GRID_VIEWS
    return () if mode == "turntable" else (mode,)


def supports(renderer: str, mode: str) -> bool:
    """Whether a renderer can draw this mode at all."""
    return mode in bambu_studio.SUPPORTED_VIEWS if renderer == "bambu-studio" else True


def installed(renderer: str, tools: Tools) -> bool:
    """Whether a renderer's program is present (the software renderer always is)."""
    if renderer == "blender":
        return tools.blender is not None
    if renderer == "bambu-studio":
        return tools.bambu_studio is not None
    return True


def plan(request: PreviewRequest, tools: Tools, model: LoadedModel | None) -> list[str]:
    """Renderers to try, best first.

    ``model`` is None when trimesh can't read the file (FBX), which leaves Blender.

    Raises:
        RequestError: the renderer asked for can't draw this mode or file.
        RendererMissingError: nothing that can draw it is installed.
    """
    mode = request.mode
    if request.renderer != "auto":
        name = request.renderer
        if not supports(name, mode):
            raise RequestError(f"{RENDERER_NAMES[name]} can only render the perspective view")
        if model is None and name != "blender":
            raise RequestError(f"only Blender can read {request.model.suffix} files")
        if not installed(name, tools):
            hint = BLENDER_INSTALL if name == "blender" else BAMBU_STUDIO_INSTALL
            raise RendererMissingError(f"{RENDERER_NAMES[name]} is not installed: {hint}")
        return [name]
    chain: list[str] = []
    for name in RENDERERS:
        if not (installed(name, tools) and supports(name, mode)):
            continue
        if model is None and name != "blender":
            continue
        if name == "bambu-studio" and model is not None and model.color_kind != "none":
            logger.debug("skipping Bambu Studio: its thumbnail would hide the model's colours")
            continue
        chain.append(name)
    if not chain:
        raise RendererMissingError(
            f"{request.model.suffix} previews need Blender: {BLENDER_INSTALL}"
        )
    return chain


def default_timeout(mode: str) -> float:
    """Blender time budget: room for a one-off GPU kernel compile plus the frames."""
    frames = TURNTABLE_FRAMES if mode == "turntable" else len(frame_views(mode))
    return 180.0 + 20.0 * frames


def _check_request(request: PreviewRequest) -> None:
    if request.mode not in MODES:
        raise RequestError(f"unknown view {request.mode!r} (choose from {', '.join(MODES)})")
    if not request.model.is_file():
        raise ModelError(f"file not found: {request.model}")
    suffix = request.model.suffix.lower()
    if suffix not in meshes.supported_suffixes():
        accepted = ", ".join(sorted(meshes.supported_suffixes()))
        raise ModelError(
            f"can't preview {suffix or 'files without an extension'} (accepted: {accepted})"
        )
    wanted = ".gif" if request.mode == "turntable" else ".png"
    if request.output.suffix.lower() != wanted:
        raise RequestError(
            f"--views {request.mode} writes a {wanted} file, not {request.output.name}"
        )


def render_preview(request: PreviewRequest, tools: Tools) -> PreviewResult:
    """Render the preview described by ``request`` and write it to ``request.output``.

    Raises:
        ModelError: missing, unsupported or empty model file.
        RequestError: options that can't work together.
        RendererMissingError: no suitable renderer is installed.
        RenderFailedError: every renderer tried failed.
    """
    started = time.monotonic()
    _check_request(request)
    suffix = request.model.suffix.lower()
    model = None if suffix in meshes.BLENDER_ONLY_FORMATS else meshes.load_model(request.model)
    chain = plan(request, tools, model)
    failures: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="bsa-preview-") as scratch:
        for name in chain:
            logger.info("Rendering %s with %s…", request.mode, RENDERER_NAMES[name])
            try:
                rendered = _render(name, request, tools, model, Path(scratch) / name)
            except BackendError as exc:
                failures.append((name, str(exc)))
                logger.warning("%s failed: %s", RENDERER_NAMES[name], exc)
                continue
            _write(request, rendered.frames)
            return _result(request, name, model, rendered, time.monotonic() - started)
    raise RenderFailedError(failures)


def _render(
    name: str, request: PreviewRequest, tools: Tools, model: LoadedModel | None, workdir: Path
) -> _Rendered:
    workdir.mkdir(parents=True)
    views = frame_views(request.mode)
    turntable = request.mode == "turntable"
    size = TURNTABLE_SIZE if turntable else (TILE_SIZE if len(views) > 1 else STILL_SIZE)
    if name == "blender" and tools.blender:
        job = blender.BlenderJob(
            model=meshes.blender_input(request.model, model, workdir),
            workdir=workdir,
            views=views,
            turntable=TURNTABLE_FRAMES if turntable else 0,
            size=size,
            samples=24 if turntable else 48,
            cpu_only=request.cpu_only,
        )
        timeout = request.timeout_s or default_timeout(request.mode)
        report = blender.run([tools.blender], job, timeout)
        frames = [_load(path) for path in report.frames]
        return _Rendered(frames, report.material, report.dimensions, report.faces, report.device)
    if model is None:  # plan() never lets this happen
        raise BackendError(f"{name} can't read {request.model.name}")
    if name == "bambu-studio" and tools.bambu_studio:
        source = request.model
        if source.suffix.lower() not in bambu_studio.IMPORT_FORMATS:
            source = workdir / "model.stl"
            meshes.write_mesh(meshes.geometry(model), source)
        image = bambu_studio.render_view(tools.bambu_studio, source, request.mode, workdir)
        return _Rendered([_load(image)], "filament")
    directions = turntable_directions() if turntable else [view_direction(v) for v in views]
    frames = software.render_frames(model, directions, size, same_distance=turntable)
    material = "preview" if model.color_kind == "none" else model.color_kind
    return _Rendered(frames, material)


def _load(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _write(request: PreviewRequest, frames: list[Image.Image]) -> None:
    request.output.parent.mkdir(parents=True, exist_ok=True)
    if request.mode == "turntable":
        compose.save_gif(frames, request.output)
    elif request.mode == "all":
        tiles = [(VIEW_LABELS[view], frame) for view, frame in zip(GRID_VIEWS, frames, strict=True)]
        compose.grid(tiles).save(request.output, format="PNG", optimize=True)
    else:
        compose.save_png(frames[0], request.output)


def _result(
    request: PreviewRequest,
    name: str,
    model: LoadedModel | None,
    rendered: _Rendered,
    seconds: float,
) -> PreviewResult:
    warnings: list[str] = []
    if model is not None:
        dimensions, faces = model.dimensions, model.faces
        if rendered.dimensions and not _close(dimensions, rendered.dimensions):
            warnings.append(
                f"Blender measured {_fmt(rendered.dimensions)}, trimesh {_fmt(dimensions)}"
            )
    else:
        dimensions, faces = rendered.dimensions or (0.0, 0.0, 0.0), rendered.faces or 0
    units = meshes.units_warning(dimensions)
    if units:
        warnings.append(units)
    height = None
    if request.expected_height_mm:
        height = HeightCheck(request.expected_height_mm, dimensions[2])
    return PreviewResult(
        output_file=request.output,
        renderer=name,
        views=frame_views(request.mode) or ("turntable",),
        dimensions_mm=dimensions,
        faces=faces,
        material=rendered.material,
        device=rendered.device,
        height_check=height,
        warnings=tuple(warnings),
        seconds=seconds,
    )


def _close(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return all(abs(x - y) <= 0.01 * max(abs(x), abs(y), 1e-9) for x, y in zip(a, b, strict=True))


def _fmt(dimensions: tuple[float, float, float]) -> str:
    return " x ".join(f"{v:g}" for v in dimensions)
