"""Textured model -> filament palette -> one filament per triangle, ready to export."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from bambu_studio_ai.color.lab import FloatArray
from bambu_studio_ai.color.load import load_model
from bambu_studio_ai.color.palette import (
    DEFAULT_MAX_COLORS,
    DEFAULT_MIN_AREA,
    Palette,
    assign,
    bin_colours,
    select_palette,
)
from bambu_studio_ai.color.sampling import face_areas, sample_surface
from bambu_studio_ai.color.segment import (
    face_adjacency,
    fill_unlabelled,
    smooth,
    vote_faces,
    weld,
)

DEFAULT_SMOOTH_PASSES = 1
PLAUSIBLE_SIZE_MM = (5.0, 400.0)


class ColorsLostError(RuntimeError):
    """A palette colour ended up on no triangle, so the print would silently lack it."""

    def __init__(self, lost: list[str], kept: list[str]) -> None:
        """Record which colours were lost and which survived."""
        self.lost = lost
        self.kept = kept
        super().__init__(
            f"{', '.join(lost)} would not be printed: no triangle is mostly that colour "
            "(the texture detail is finer than the mesh). Leave it out with "
            f'--colors "{",".join(kept)}", or import the GLB into Bambu Studio 2.7+ '
            "directly and let it convert the texture"
        )


@dataclass(frozen=True)
class ColorizeOptions:
    """How to colour a model."""

    max_colors: int = DEFAULT_MAX_COLORS
    min_area: float = DEFAULT_MIN_AREA
    """Smallest share of the visible surface that gets its own filament (0.002 = 0.2 %)."""
    colors: tuple[str, ...] = ()
    """Fixed ``#RRGGBB`` palette; when given, colours are not detected."""
    height_mm: float | None = None
    """Scale the model uniformly so it is this tall (Z)."""
    smooth_passes: int = DEFAULT_SMOOTH_PASSES


@dataclass(frozen=True)
class ColorizeResult:
    """A welded, Z-up, millimetre mesh with a filament per triangle."""

    vertices: FloatArray
    faces: NDArray[np.int64]
    labels: NDArray[np.int64]
    """0-based palette index of every triangle."""
    palette: Palette
    area_share: FloatArray
    """Share of the surface area painted with each palette colour (sums to 1)."""
    warnings: tuple[str, ...] = field(default=())

    @property
    def size_mm(self) -> tuple[float, float, float]:
        """Bounding-box size (X, Y, Z)."""
        extent = self.vertices.max(axis=0) - self.vertices.min(axis=0)
        return float(extent[0]), float(extent[1]), float(extent[2])


def colorize(path: Path, options: ColorizeOptions | None = None) -> ColorizeResult:
    """Detect the colours of the textured model at ``path`` and paint its triangles.

    Raises:
        ModelLoadError: the file can't be read.
        NoColourError: the model has no colour information.
        ColorsLostError: an automatically chosen colour ended up on no triangle.
        ValueError: invalid options or an entirely transparent model.
    """
    options = options or ColorizeOptions()
    if options.height_mm is not None and options.height_mm <= 0:
        raise ValueError(f"height must be positive, not {options.height_mm}")
    model = load_model(path)
    samples = sample_surface(model)
    bins = bin_colours(samples.rgb, samples.weight)
    forced = bool(options.colors)
    palette = (
        Palette.from_hex(list(options.colors))
        if forced
        else select_palette(bins, options.max_colors, options.min_area)
    )
    count = len(palette)
    sample_labels = assign(bins.lab, palette)[bins.of_sample]
    labels = vote_faces(samples.face, sample_labels, samples.weight, len(model.faces), count)
    mesh = weld(model.vertices, model.faces)
    labels = labels[mesh.source_face]
    pairs = face_adjacency(mesh.faces)
    labels = fill_unlabelled(labels, pairs, count)
    labels = smooth(labels, pairs, count, options.smooth_passes)

    warnings = [*model.warnings, *samples.warnings]
    vertices, note = _scaled(mesh.vertices, options.height_mm)
    if note:
        warnings.append(note)
    areas = face_areas(vertices, mesh.faces)
    share = np.bincount(labels, areas, count) / max(float(areas.sum()), 1e-12)
    unused = [palette.hex[i] for i in range(count) if share[i] == 0]
    if unused and not forced:
        raise ColorsLostError(unused, [c for c in palette.hex if c not in unused])
    if unused:
        warnings.append(f"no triangle uses {', '.join(unused)}; that filament stays unused")
    if count == 1:
        warnings.append("only one colour found: this model doesn't need multi-colour printing")
    return ColorizeResult(vertices, mesh.faces, labels, palette, share, tuple(warnings))


def _scaled(vertices: FloatArray, height_mm: float | None) -> tuple[FloatArray, str]:
    """Scale to ``height_mm`` if given, else warn when the size looks like a unit mix-up."""
    extent = vertices.max(axis=0) - vertices.min(axis=0)
    if height_mm is not None:
        if extent[2] <= 0:
            raise ValueError("the model is flat (zero height); cannot scale it to a height")
        return vertices * (height_mm / float(extent[2])), ""
    largest = float(extent.max())
    low, high = PLAUSIBLE_SIZE_MM
    if not low <= largest <= high:
        return vertices, (
            f"the model is {largest:.1f} mm across, which looks like a unit mismatch; "
            "pass --height to set its printed height"
        )
    return vertices, ""
