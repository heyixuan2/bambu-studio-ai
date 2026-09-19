"""A quick flat-shaded picture of the painted model, without Blender or a GPU.

Points are scattered over every triangle (about :data:`POINTS_PER_PIXEL` per pixel it
covers on screen), projected orthographically from the front-right and kept only where
they are nearest to the camera. It is a check of where the colours landed, not a render.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from bambu_studio_ai.color.lab import FloatArray, unit_clip

POINTS_PER_PIXEL = 8.0
_AZIMUTH_DEG = -35.0  # camera to the front-right (front is -Y, as in Bambu Studio)
_ELEVATION_DEG = 25.0
_BACKGROUND = 255


def render_preview(
    vertices: FloatArray, faces: NDArray[np.int64], face_rgb: FloatArray, size: int = 512
) -> NDArray[np.uint8]:
    """Return a ``(size, size, 3)`` RGB image of the mesh with one flat colour per face."""
    right, up, towards_camera = _camera_axes()
    corners = vertices[faces]
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    # Two-sided light from the camera, so flipped normals still read as surfaces.
    shade = 0.45 + 0.55 * np.abs(normals @ towards_camera)
    screen = np.stack([vertices @ right, vertices @ up], axis=1)
    low, high = screen.min(axis=0), screen.max(axis=0)
    scale = 0.9 * size / max(float(np.max(high - low)), 1e-9)
    pixels = (screen - (low + high) / 2) * scale + size / 2
    tri = pixels[faces]
    edge1, edge2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    area = 0.5 * np.abs(edge1[:, 0] * edge2[:, 1] - edge1[:, 1] * edge2[:, 0])
    wanted = np.ceil(area * POINTS_PER_PIXEL)
    counts = np.maximum(wanted, 1).astype(np.int64)
    face_of_point = np.repeat(np.arange(len(faces)), counts)
    rng = np.random.default_rng(0)  # fixed seed: the same model gives the same picture
    s, t = rng.random(len(face_of_point)), rng.random(len(face_of_point))
    fold = s + t > 1
    s, t = np.where(fold, 1 - s, s), np.where(fold, 1 - t, t)
    base = corners[face_of_point, 0]
    points = (
        base
        + s[:, None] * (corners[face_of_point, 1] - base)
        + t[:, None] * (corners[face_of_point, 2] - base)
    )
    x = ((points @ right - (low[0] + high[0]) / 2) * scale + size / 2).astype(np.int64)
    y = (size / 2 - (points @ up - (low[1] + high[1]) / 2) * scale).astype(np.int64)
    inside = (x >= 0) & (x < size) & (y >= 0) & (y < size)
    pixel = (y * size + x)[inside]
    depth = -(points @ towards_camera)[inside]
    order = np.lexsort((depth, pixel))
    first = np.ones(len(order), dtype=bool)
    first[1:] = pixel[order][1:] != pixel[order][:-1]
    winners = order[first]
    colour = face_rgb[face_of_point[inside][winners]] * shade[face_of_point[inside][winners], None]
    image = np.full((size * size, 3), _BACKGROUND, dtype=np.uint8)
    image[pixel[winners]] = np.round(unit_clip(colour) * 255).astype(np.uint8)
    return np.reshape(image, (size, size, 3))


def _camera_axes() -> tuple[FloatArray, FloatArray, FloatArray]:
    azimuth, elevation = np.radians(_AZIMUTH_DEG), np.radians(_ELEVATION_DEG)
    towards_camera = np.array(
        [
            np.sin(-azimuth) * np.cos(elevation),
            -np.cos(azimuth) * np.cos(elevation),
            np.sin(elevation),
        ]
    )
    right = np.cross(np.array([0.0, 0.0, 1.0]), towards_camera)
    right /= np.linalg.norm(right)
    up = np.cross(towards_camera, right)
    return right, up, towards_camera
