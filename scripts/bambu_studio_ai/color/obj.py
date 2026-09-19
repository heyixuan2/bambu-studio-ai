"""Write a vertex-colour OBJ: the secondary output for slicers that can't read Bambu paint.

Colour lives on vertices here, so each vertex takes the colour of most of the triangles
around it and boundaries fall on vertices rather than exactly between triangles. Bambu
Studio shows its colour-mapping dialog when it imports such a file.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from bambu_studio_ai.color.lab import FloatArray


def vertex_labels(
    vertex_count: int, faces: NDArray[np.int64], labels: NDArray[np.int64], colour_count: int
) -> NDArray[np.int64]:
    """Colour of each vertex: the most common colour among the triangles that use it."""
    keys = np.ravel(faces * colour_count + labels[:, None])
    votes = np.bincount(keys, minlength=vertex_count * colour_count)
    return np.argmax(np.reshape(votes, (vertex_count, colour_count)), axis=1).astype(np.int64)


def build_obj(
    vertices: FloatArray,
    faces: NDArray[np.int64],
    labels: NDArray[np.int64],
    palette_rgb: FloatArray,
) -> str:
    """OBJ text with ``v x y z r g b`` lines (sRGB, 0-1), Z up, in millimetres."""
    colours = palette_rgb[vertex_labels(len(vertices), faces, labels, len(palette_rgb))]
    lines = ["# bambu-studio-ai colorize: Z up, millimetres, sRGB vertex colours"]
    lines += [
        f"v {x:.5f} {y:.5f} {z:.5f} {r:.4f} {g:.4f} {b:.4f}"
        for (x, y, z), (r, g, b) in zip(_rows(vertices), _rows(colours), strict=True)
    ]
    lines += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in _rows(faces)]
    lines.append("")
    return "\n".join(lines)


def _rows(array: NDArray[Any]) -> list[list[Any]]:
    """``ndarray.tolist()`` for a 2-D array (numpy's stubs leave it untyped)."""
    return cast("list[list[Any]]", array.tolist())
