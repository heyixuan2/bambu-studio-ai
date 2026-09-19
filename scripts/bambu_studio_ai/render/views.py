"""Camera directions and framing shared by every preview renderer.

Blender's copy of Python loads this file by path (``blender_scene.py``), so it may only
depend on the standard library and numpy, both of which ship inside Blender.

Coordinates are the model file's own, with Z up. That is how Bambu Studio and
``analyze.py`` read every format, glTF included, so the preview shows the model the way
it will sit on the build plate.
"""

from __future__ import annotations

import math
from typing import Final

import numpy as np
from numpy.typing import NDArray

Vector = tuple[float, float, float]
FloatArray = NDArray[np.float64]

GRID_VIEWS: Final = ("perspective", "front", "side", "top")
"""Tile order of the 2x2 grid: perspective, front on the top row; side, top below."""

VIEW_LABELS: Final = {
    "perspective": "Perspective",
    "front": "Front",
    "side": "Side (right)",
    "top": "Top",
}

# From the model's centre towards the camera. Front looks along +Y, side along -X.
_VIEW_DIRECTIONS: Final[dict[str, Vector]] = {
    "perspective": (0.7, -0.9, 0.5),
    "front": (0.0, -1.0, 0.0),
    "side": (1.0, 0.0, 0.0),
    "top": (0.0, 0.0, 1.0),
}

LENS_MM: Final = 50.0
SENSOR_MM: Final = 36.0
TAN_HALF_FOV: Final = (SENSOR_MM / 2) / LENS_MM
FILL: Final = 0.92
"""Share of the half-frame the model may reach, so a thin margin stays around it."""

TURNTABLE_FRAMES: Final = 36
_TURNTABLE_ELEVATION_DEG: Final = 28.0
_TURNTABLE_SWAY_DEG: Final = 8.0
_STRAIGHT_UP: Final = 0.999


def _normalize(vector: Vector) -> Vector:
    length = math.sqrt(sum(c * c for c in vector))
    return (vector[0] / length, vector[1] / length, vector[2] / length)


def _cross(a: Vector, b: Vector) -> Vector:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def view_direction(name: str) -> Vector:
    """Unit vector from the model's centre towards the camera for a named view."""
    return _normalize(_VIEW_DIRECTIONS[name])


def turntable_directions(frames: int = TURNTABLE_FRAMES) -> list[Vector]:
    """Camera directions for one full turn, starting at the perspective view.

    The elevation sways gently (20-36 degrees) so the top and the sides both show
    without the camera ever dipping under the model.
    """
    start = view_direction("perspective")
    azimuth0 = math.atan2(start[1], start[0])
    directions: list[Vector] = []
    for index in range(frames):
        phase = 2 * math.pi * index / frames
        elevation = math.radians(_TURNTABLE_ELEVATION_DEG + _TURNTABLE_SWAY_DEG * math.sin(phase))
        azimuth = azimuth0 + phase
        directions.append(
            (
                math.cos(elevation) * math.cos(azimuth),
                math.cos(elevation) * math.sin(azimuth),
                math.sin(elevation),
            )
        )
    return directions


def camera_basis(direction: Vector) -> tuple[Vector, Vector, Vector]:
    """Right, up and backward unit vectors of a camera looking along ``-direction``.

    Up follows world Z, except when looking straight down or up, where +Y is up
    in the image (so the model's front is at the bottom of a top view).
    """
    back = _normalize(direction)
    world_up: Vector = (0.0, 1.0, 0.0) if abs(back[2]) > _STRAIGHT_UP else (0.0, 0.0, 1.0)
    right = _normalize(_cross(world_up, back))
    up = _cross(back, right)
    return right, up, back


def fit_distance(points: FloatArray, direction: Vector) -> float:
    """Distance from the centre at which every point fits in the frame.

    Args:
        points: ``(n, 3)`` vertex positions relative to the framing centre.
        direction: unit vector from the centre towards the camera.

    Returns:
        The smallest camera distance that keeps each point inside ``FILL`` of the
        half-frame. A point at lateral offset ``s`` and ``t`` towards the camera
        projects inside the frame when ``s / (d - t) <= tan(fov/2) * FILL``.
    """
    right, up, back = camera_basis(direction)
    lateral = np.maximum(np.abs(points @ np.array(right)), np.abs(points @ np.array(up)))
    towards = points @ np.array(back)
    needed = lateral / (TAN_HALF_FOV * FILL) + towards
    radius = float(np.sqrt((points**2).sum(axis=1)).max()) or 1.0
    # Keep the nearest point clearly in front of the lens, even for a flat part seen edge-on.
    return max(float(needed.max()), float(towards.max()) + 0.05 * radius)


def framing(vertices: FloatArray) -> tuple[FloatArray, FloatArray]:
    """Framing centre (bounding-box centre) and the vertices relative to it."""
    centre = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    return centre, vertices - centre


def shared_distance(points: FloatArray, directions: list[Vector]) -> float:
    """One distance that fits every direction, so a turntable doesn't zoom in and out."""
    return max(fit_distance(points, d) for d in directions)
