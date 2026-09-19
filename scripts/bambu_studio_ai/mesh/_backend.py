"""Typed wrappers for the trimesh and scipy calls that carry no type information.

trimesh annotates its ``Trimesh`` properties but not most module-level helpers, and scipy
ships without stubs, so under pyright's strict mode their results are ``Unknown``. Every
such call goes through this module, which gives each result an explicit numpy type; the
rest of the package is then checked strictly. ``Any`` below means exactly that: an
untyped third-party object whose result is converted before it leaves this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
import scipy.sparse  # pyright: ignore[reportMissingTypeStubs]
import scipy.sparse.csgraph  # pyright: ignore[reportMissingTypeStubs]
import scipy.spatial  # pyright: ignore[reportMissingTypeStubs]
import trimesh
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

_trimesh = cast("Any", trimesh)
_sparse = cast("Any", scipy.sparse)
_csgraph = cast("Any", scipy.sparse.csgraph)
_spatial = cast("Any", scipy.spatial)


def load(path: Path) -> object:
    """Read a mesh file; scenes are flattened into one mesh."""
    return cast("object", _trimesh.load(str(path), force="mesh"))


def export(mesh: trimesh.Trimesh, path: Path) -> None:
    """Write a mesh; the format follows the file suffix."""
    cast("Any", mesh).export(str(path))


def sample_surface(mesh: trimesh.Trimesh, count: int, seed: int) -> tuple[FloatArray, IntArray]:
    """Area-weighted random points on the surface and the face each one lies on."""
    points, faces = _trimesh.sample.sample_surface(mesh, count, seed=seed)
    return np.asarray(points, dtype=np.float64), np.asarray(faces, dtype=np.int64)


def stable_poses(
    mesh: trimesh.Trimesh, center_mass: FloatArray
) -> tuple[NDArray[np.float64], FloatArray]:
    """Resting poses on a flat plane, as (n, 4, 4) transforms, most probable first."""
    transforms, probabilities = _trimesh.poses.compute_stable_poses(mesh, center_mass=center_mass)
    return np.asarray(transforms, dtype=np.float64), np.asarray(probabilities, dtype=np.float64)


def fix_winding(mesh: trimesh.Trimesh) -> None:
    """Make neighbouring faces agree on orientation (in place)."""
    _trimesh.repair.fix_winding(mesh)


def fill_holes(mesh: trimesh.Trimesh, *, use_fan: bool) -> None:
    """Close boundary loops (in place); without fans only 3- and 4-edge holes are closed."""
    _trimesh.repair.fill_holes(mesh, use_fan=use_fan)


def connected_labels(node_count: int, edges: IntArray) -> IntArray:
    """Label each node with the connected component it belongs to."""
    weights = np.ones(len(edges), dtype=np.int8)
    graph = _sparse.coo_matrix((weights, (edges[:, 0], edges[:, 1])), shape=(node_count,) * 2)
    _, labels = _csgraph.connected_components(graph, directed=False)
    return np.asarray(labels, dtype=np.int64)


def ball_pairs(points: FloatArray, queries: FloatArray, radius: float) -> tuple[IntArray, IntArray]:
    """All (query, point) index pairs closer than ``radius``, as two flat arrays."""
    tree = _spatial.cKDTree(points)
    lists = cast("list[list[int]]", tree.query_ball_point(queries, radius))
    sizes = np.fromiter((len(found) for found in lists), dtype=np.int64, count=len(lists))
    found = np.fromiter(
        (index for group in lists for index in group), dtype=np.int64, count=int(sizes.sum())
    )
    return np.repeat(np.arange(len(lists), dtype=np.int64), sizes), found


def invert(mesh: trimesh.Trimesh) -> None:
    """Flip every face so the normals point the other way (in place)."""
    cast("Any", mesh).invert()


def apply_transform(mesh: trimesh.Trimesh, transform: FloatArray) -> None:
    """Apply a 4x4 homogeneous transform to the mesh (in place)."""
    cast("Any", mesh).apply_transform(transform)
