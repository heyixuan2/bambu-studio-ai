"""Software renderer: numpy + Pillow, no GPU, no external program.

The last link of the fallback chain. A vectorised z-buffer rasterises every triangle
at twice the target size (then scales down for anti-aliasing), interpolates vertex
colours and samples textures per pixel with perspective-correct barycentrics, and
lights faces from the camera's side like the Blender renderer does.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

import numpy as np
from PIL import Image

from bambu_studio_ai.render.meshes import PREVIEW_RGB, FloatArray, IntArray, LoadedModel
from bambu_studio_ai.render.views import (
    TAN_HALF_FOV,
    Vector,
    camera_basis,
    framing,
    shared_distance,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

SUPERSAMPLE: Final = 2
_CHUNK: Final = 600_000  # candidate pixels per batch: bounds peak memory to ~100 MB
_AMBIENT: Final = 0.32
_KEY: Final = 0.58
_FILL: Final = 0.22
_SKY: Final = 0.10
_MIN_AREA: Final = 1e-12  # screen-space area below which a triangle is a sliver
_EDGE_EPS: Final = 1e-9  # pixel centres exactly on a shared edge belong to both triangles


class _Scene:
    """The model flattened into arrays once, then drawn from any direction."""

    def __init__(self, model: LoadedModel) -> None:
        """Stack every part's triangles with per-corner colours."""
        offset = 0
        vertices: list[FloatArray] = []
        faces: list[IntArray] = []
        corners: list[FloatArray] = []
        self.textured: list[tuple[IntArray, FloatArray, FloatArray]] = []
        for part in model.parts:
            face_ids = np.arange(len(part.faces)) + sum(len(f) for f in faces)
            vertices.append(part.vertices)
            faces.append(part.faces + offset)
            offset += len(part.vertices)
            rgb = part.corner_rgb
            if rgb is None:
                rgb = np.broadcast_to(
                    np.array(PREVIEW_RGB, dtype=np.uint8), (len(part.faces), 3, 3)
                )
            corners.append(rgb.astype(np.float64) / 255.0)
            if part.texture is not None and part.corner_uv is not None:
                self.textured.append(
                    (face_ids, part.corner_uv, part.texture.astype(np.float64) / 255)
                )
        self.vertices = np.vstack(vertices)
        self.faces = np.vstack(faces)
        self.corner_rgb = np.concatenate(corners)
        self.centre, self.relative = framing(self.vertices)
        tri = self.vertices[self.faces]
        normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        self.normals = normals / np.where(lengths == 0, 1.0, lengths)
        self.centroids = tri.mean(axis=1)

    def draw(self, direction: Vector, distance: float, size: int) -> Image.Image:
        """One RGBA frame (transparent background) seen from ``direction``."""
        right, up, back = (np.array(axis) for axis in camera_basis(direction))
        eye = self.centre + back * distance
        relative = self.vertices - eye
        depth = -(relative @ back)
        big = size * SUPERSAMPLE
        scale = (big / 2) / TAN_HALF_FOV
        screen = np.stack(
            [
                big / 2 + (relative @ right) / depth * scale,
                big / 2 - (relative @ up) / depth * scale,
            ],
            axis=1,
        )
        face_buf, bary = _rasterize(screen[self.faces], 1.0 / depth[self.faces], big)
        covered = np.flatnonzero(face_buf >= 0)
        hit = face_buf[covered]
        weights = bary[covered]

        rgb = np.einsum("pc,pck->pk", weights, self.corner_rgb[hit])
        for face_ids, corner_uv, texture in self.textured:
            mask = np.isin(hit, face_ids)
            local = hit[mask] - face_ids[0]
            uv = np.einsum("pc,pck->pk", weights[mask], corner_uv[local]) % 1.0
            rows = ((1.0 - uv[:, 1]) * (texture.shape[0] - 1)).round().astype(np.int64)
            cols = (uv[:, 0] * (texture.shape[1] - 1)).round().astype(np.int64)
            rgb[mask] = texture[rows, cols]

        shade = self._shade(eye, right, up, back)[hit]
        pixels = np.zeros((big * big, 4), dtype=np.uint8)
        pixels[covered, :3] = np.round(np.minimum(rgb * shade[:, None], 1.0) * 255)
        pixels[covered, 3] = 255
        image = Image.fromarray(np.reshape(pixels, (big, big, 4)), "RGBA")
        # Pillow resizes RGBA with premultiplied alpha, so edges don't darken.
        return image.resize((size, size), Image.Resampling.LANCZOS)

    def _shade(
        self, eye: FloatArray, right: FloatArray, up: FloatArray, back: FloatArray
    ) -> FloatArray:
        """Brightness per face, lit from the camera's side (flat shading).

        Normals are flipped towards the camera, so open meshes show their inside too.
        """
        towards_eye = (self.normals * (eye - self.centroids)).sum(axis=1)
        normals = self.normals * np.where(towards_eye < 0, -1.0, 1.0)[:, None]
        key = _unit(-0.45 * right + 0.65 * up + 0.6 * back)
        fill = _unit(0.7 * right + 0.1 * up + 0.7 * back)
        return (
            _AMBIENT
            + _KEY * np.maximum(normals @ key, 0.0)
            + _FILL * np.maximum(normals @ fill, 0.0)
            + _SKY * np.maximum(normals[:, 2], 0.0)
        )


def _unit(vector: FloatArray) -> FloatArray:
    return vector / np.linalg.norm(vector)


def _rasterize(tri: FloatArray, inv_depth: FloatArray, size: int) -> tuple[IntArray, FloatArray]:
    """Z-buffer ``(faces, 3, 2)`` screen triangles into a ``size`` x ``size`` image.

    Returns:
        The winning face per pixel (-1 where empty) and its perspective-correct
        barycentric weights, both flattened row-major.
    """
    x, y = tri[:, :, 0], tri[:, :, 1]
    area = (x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0])
    x0 = np.minimum(np.maximum(np.ceil(x.min(axis=1) - 0.5), 0), size).astype(np.int64)
    x1 = np.minimum(np.maximum(np.floor(x.max(axis=1) - 0.5), -1), size - 1).astype(np.int64)
    y0 = np.minimum(np.maximum(np.ceil(y.min(axis=1) - 0.5), 0), size).astype(np.int64)
    y1 = np.minimum(np.maximum(np.floor(y.max(axis=1) - 0.5), -1), size - 1).astype(np.int64)
    width = np.maximum(x1 - x0 + 1, 0)
    height = np.maximum(y1 - y0 + 1, 0)
    counts = width * height
    live = np.flatnonzero((counts > 0) & (np.abs(area) > _MIN_AREA))

    zbuf = np.zeros(size * size)
    face_buf = np.full(size * size, -1, dtype=np.int64)
    bary = np.zeros((size * size, 3))
    batch = np.cumsum(counts[live]) // _CHUNK
    for faces in np.split(live, np.flatnonzero(np.diff(batch)) + 1):
        n = counts[faces]
        owner = np.repeat(faces, n)
        local = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
        px = x0[owner] + local % width[owner]
        py = y0[owner] + local // width[owner]
        cx, cy = px + 0.5, py + 0.5
        tx, ty = x[owner], y[owner]
        w0 = ((tx[:, 1] - cx) * (ty[:, 2] - cy) - (tx[:, 2] - cx) * (ty[:, 1] - cy)) / area[owner]
        w1 = ((tx[:, 2] - cx) * (ty[:, 0] - cy) - (tx[:, 0] - cx) * (ty[:, 2] - cy)) / area[owner]
        w = np.stack([w0, w1, 1.0 - w0 - w1], axis=1)
        inside = (w >= -_EDGE_EPS).all(axis=1)
        w, owner, pixel = w[inside], owner[inside], (py * size + px)[inside]
        weighted = w * inv_depth[owner]
        nearness = weighted.sum(axis=1)
        np.maximum.at(zbuf, pixel, nearness)
        wins = nearness >= zbuf[pixel]
        face_buf[pixel[wins]] = owner[wins]
        bary[pixel[wins]] = weighted[wins] / nearness[wins, None]
    return face_buf, bary


def render_frames(
    model: LoadedModel, directions: Sequence[Vector], size: int, *, same_distance: bool
) -> list[Image.Image]:
    """Render one RGBA frame per direction.

    Args:
        model: the loaded model.
        directions: unit vectors from the model towards the camera.
        size: frame width and height in pixels.
        same_distance: keep one camera distance for all frames (turntables) instead of
            fitting each view on its own.
    """
    scene = _Scene(model)
    logger.debug("software renderer: %d faces, %d frames", len(scene.faces), len(directions))
    common = shared_distance(scene.relative, list(directions)) if same_distance else None
    return [
        scene.draw(d, common if common is not None else shared_distance(scene.relative, [d]), size)
        for d in directions
    ]
