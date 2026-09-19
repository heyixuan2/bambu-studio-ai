"""Sample the colour each triangle shows, straight from its material's texture.

Each triangle's UV footprint is split into ``n x n`` equal sub-triangles and the texel
under every sub-triangle centre is read (nearest texel, as a printer can't blend
filaments anyway). ``n`` grows with the footprint so that a sample stands for about
:data:`TEXELS_PER_SAMPLE` texels. Only texels that some triangle covers are ever read,
so atlas padding and unused texture space never count, and every sample is weighted by
the 3D area it represents times its opacity.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np
from numpy.typing import NDArray

from bambu_studio_ai.color.lab import FloatArray, linear_to_srgb, srgb_to_linear, unit_clip
from bambu_studio_ai.color.load import Part, SourceModel

TEXELS_PER_SAMPLE = 2.0
SAMPLE_BUDGET = 2_000_000
"""Samples per textured part beyond one per triangle; above it, samples thin out evenly."""
MAX_LEVEL = 64
"""At most ``MAX_LEVEL**2`` samples per triangle, however large its UV footprint."""
MIN_VISIBLE_SHARE = 0.01
"""A part whose alpha hides more than 99 % of it has a junk alpha channel; ignore alpha."""


@dataclass(frozen=True)
class Samples:
    """Colour samples on the model's surface."""

    face: NDArray[np.int64]
    """``(S,)`` index of the triangle each sample lies on."""
    rgb: FloatArray
    """``(S, 3)`` sRGB in [0, 1]."""
    weight: FloatArray
    """``(S,)`` surface area in mm² the sample stands for, times its opacity."""
    warnings: tuple[str, ...] = ()


def face_areas(vertices: FloatArray, faces: NDArray[np.int64]) -> FloatArray:
    """Area of every triangle."""
    corners = vertices[faces]
    return 0.5 * np.linalg.norm(
        np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1
    )


def sample_surface(model: SourceModel) -> Samples:
    """Sample every triangle of ``model`` (see the module docstring for how)."""
    areas = face_areas(model.vertices, model.faces)
    chunks: list[tuple[NDArray[np.int64], FloatArray, FloatArray, FloatArray]] = []
    warnings: list[str] = []
    for part in model.parts:
        face_ids = np.arange(part.faces.start, part.faces.stop, dtype=np.int64)
        if len(face_ids) == 0:
            continue
        faces, rgb, area, alpha = _sample_part(model, part, face_ids, areas)
        opacity = _opacity(part, alpha)
        visible = float(np.sum(area * opacity))
        if visible < MIN_VISIBLE_SHARE * float(np.sum(area)):
            warnings.append("a texture is almost fully transparent; its alpha channel is ignored")
            opacity = np.ones_like(opacity)
        chunks.append((faces, rgb, area, opacity))
    if not chunks:
        return Samples(np.zeros(0, np.int64), np.zeros((0, 3)), np.zeros(0))
    return Samples(
        face=np.concatenate([c[0] for c in chunks]),
        rgb=np.concatenate([c[1] for c in chunks]),
        weight=np.concatenate([c[2] * c[3] for c in chunks]),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def texel_index(coord: FloatArray, size: int) -> NDArray[np.int64]:
    """Map texture coordinates to texel indices along one axis.

    glTF's default wrap mode is REPEAT, but a coordinate of exactly 1.0 is the far edge of
    the image, not the start of the next tile: wrapping it with ``% size`` is what painted
    the right-hand edge of models with the colour of the left-hand edge.
    """
    outside = (coord < 0.0) | (coord > 1.0)
    wrapped = np.where(outside, coord - np.floor(coord), coord)
    return np.minimum((wrapped * size).astype(np.int64), size - 1)


@cache
def sub_triangle_centres(level: int) -> FloatArray:
    """Barycentric centres of the ``level**2`` sub-triangles of a regularly split triangle."""
    centres: list[tuple[float, float]] = []
    for i in range(level):
        for j in range(level - i):
            centres.append(((i + 1 / 3) / level, (j + 1 / 3) / level))
            if i + j <= level - 2:
                centres.append(((i + 2 / 3) / level, (j + 2 / 3) / level))
    grid = np.array(centres, dtype=np.float64)
    s, t = grid[:, 0], grid[:, 1]
    return np.stack([1 - s - t, s, t], axis=1)


def _sample_part(
    model: SourceModel, part: Part, face_ids: NDArray[np.int64], areas: FloatArray
) -> tuple[NDArray[np.int64], FloatArray, FloatArray, FloatArray]:
    """Return per-sample (face, sRGB, area, alpha) for one part."""
    corners = model.faces[face_ids]
    if part.texture is not None:
        return _sample_texture(model, part, face_ids, corners, areas)
    factor_rgb = linear_to_srgb(part.factor[:3])
    if part.has_colour and not np.allclose(model.vertex_colours[corners], 1.0):
        # Vertex colours: one sample per corner, so a triangle takes its majority corner.
        colours = np.reshape(model.vertex_colours[corners], (-1, 4))
        rgb = _tint(colours[:, :3], part.factor[:3])
        alpha = colours[:, 3] * part.factor[3]
        area = np.repeat(areas[face_ids] / 3, 3)
        return np.repeat(face_ids, 3), rgb, area, alpha
    rgb = np.tile(factor_rgb, (len(face_ids), 1))
    alpha = np.full(len(face_ids), part.factor[3])
    return face_ids, rgb, areas[face_ids], alpha


def _sample_texture(
    model: SourceModel,
    part: Part,
    face_ids: NDArray[np.int64],
    corners: NDArray[np.int64],
    areas: FloatArray,
) -> tuple[NDArray[np.int64], FloatArray, FloatArray, FloatArray]:
    texture = part.texture
    assert texture is not None  # noqa: S101 - narrowed by the caller
    height, width = texture.shape[:2]
    uv = model.uv[corners]  # (F, 3, 2)
    texel_uv = uv * np.array([width, height])
    edge1, edge2 = texel_uv[:, 1] - texel_uv[:, 0], texel_uv[:, 2] - texel_uv[:, 0]
    texel_area = 0.5 * np.abs(edge1[:, 0] * edge2[:, 1] - edge1[:, 1] * edge2[:, 0])
    # Low-poly models get dense samples (thin texture lines still count); huge textures on
    # dense meshes are thinned so the whole part stays within the budget.
    texels_per_sample = max(TEXELS_PER_SAMPLE, float(texel_area.sum()) / SAMPLE_BUDGET)
    wanted = np.ceil(np.sqrt(texel_area / texels_per_sample))
    levels = np.minimum(np.maximum(wanted, 1), MAX_LEVEL).astype(np.int64)
    tinted = not np.allclose(model.vertex_colours[corners], 1.0)
    faces_out: list[NDArray[np.int64]] = []
    rgba_out: list[NDArray[np.uint8]] = []
    area_out: list[FloatArray] = []
    vertex_out: list[FloatArray] = []
    for level in np.unique(levels):
        chosen = levels == level
        weights = sub_triangle_centres(int(level))  # (K, 3)
        points = np.reshape(np.einsum("kc,fcd->fkd", weights, uv[chosen]), (-1, 2))
        columns = texel_index(points[:, 0], width)
        rows = texel_index(1.0 - points[:, 1], height)  # UV origin is the bottom-left
        rgba_out.append(texture[rows, columns])
        count = len(weights)
        faces_out.append(np.repeat(face_ids[chosen], count))
        area_out.append(np.repeat(areas[face_ids[chosen]] / count, count))
        if tinted:
            vertex = model.vertex_colours[corners[chosen]]  # (f, 3, 4)
            vertex_out.append(np.reshape(np.einsum("kc,fcd->fkd", weights, vertex), (-1, 4)))
    rgba = np.concatenate(rgba_out).astype(np.float64) / 255
    rgb = _tint(rgba[:, :3], part.factor[:3])
    alpha = rgba[:, 3] * part.factor[3]
    if tinted:
        vertex_rgba = np.concatenate(vertex_out)
        rgb = linear_to_srgb(srgb_to_linear(rgb) * srgb_to_linear(vertex_rgba[:, :3]))
        alpha = alpha * vertex_rgba[:, 3]
    return np.concatenate(faces_out), rgb, np.concatenate(area_out), alpha


def _tint(srgb: FloatArray, factor_linear: FloatArray) -> FloatArray:
    """Multiply sRGB colours by a linear ``baseColorFactor`` (in linear light, per glTF)."""
    if np.allclose(factor_linear, 1.0):
        return srgb
    return linear_to_srgb(srgb_to_linear(srgb) * factor_linear)


def _opacity(part: Part, alpha: FloatArray) -> FloatArray:
    """How much each sample counts.

    glTF says OPAQUE materials ignore alpha, but texels with alpha 0 inside a UV island are
    unpainted padding bleeding over the island's edge; their RGB is meaningless, so they
    get no say in the palette under every alpha mode.
    """
    if part.alpha_mode == "MASK":
        return (alpha >= part.alpha_cutoff).astype(np.float64)
    return unit_clip(alpha)
