"""Ray queries against a triangle mesh, in plain numpy.

trimesh's own ray engine needs the optional ``rtree`` or ``embreex`` packages and, even
with rtree, tests every triangle near the whole length of each ray, which takes about
20 s for 2000 rays on a 300k-face mesh. The queries here only ever need short rays or
vertical ones, so they cull candidates with a KD-tree (or a bounding-box test) and run a
vectorised Moller-Trumbore intersection on what is left: under a second for the same job.
"""

from __future__ import annotations

import numpy as np
import trimesh

from bambu_studio_ai.mesh import _backend
from bambu_studio_ai.mesh._backend import BoolArray, FloatArray, IntArray

# Ray/triangle pairs tested per numpy batch; bounds peak memory to a few hundred MB.
_PAIRS_PER_BATCH = 400_000
# Below this many ray x triangle pairs, test every pair instead of building a KD-tree.
_BRUTE_FORCE_PAIRS = 2_000_000
# Triangles bigger than this percentile of circumradius are tested against every ray, so
# a few huge faces (common in CAD exports) do not inflate the KD-tree search radius.
_LARGE_TRIANGLE_PERCENTILE = 99.0
_MAX_SEGMENTS_PER_RAY = 16
_PARALLEL_EPS = 1e-12


def first_exit_distances(
    mesh: trimesh.Trimesh, origins: FloatArray, directions: FloatArray, max_distance: float
) -> FloatArray:
    """Distance along each ray to the first face it leaves the solid through.

    Only faces whose outward normal points along the ray count, so a ray that starts on
    the surface and heads inwards stops where the material ends, and faces it enters
    through (e.g. overlapping shells) are ignored.

    Args:
        mesh: a closed, outward-facing mesh.
        origins: (n, 3) ray starts.
        directions: (n, 3) unit ray directions.
        max_distance: rays are only followed this far.

    Returns:
        (n,) distances; ``inf`` where no exit lies within ``max_distance``.
    """
    count = len(origins)
    result = np.full(count, np.inf)
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    if count == 0 or len(triangles) == 0:
        return result
    ray_index, face_index = _candidate_pairs(triangles, origins, directions, max_distance)
    for start in range(0, len(ray_index), _PAIRS_PER_BATCH):
        rays = ray_index[start : start + _PAIRS_PER_BATCH]
        faces = face_index[start : start + _PAIRS_PER_BATCH]
        hit, distance, leaving = _intersect(triangles[faces], origins[rays], directions[rays])
        hit &= leaving & (distance <= max_distance)
        np.minimum.at(result, rays[hit], distance[hit])
    return result


def material_below(triangles: FloatArray, points: FloatArray) -> IntArray:
    """How many layers of material each point sits in, found by looking straight down.

    Follows a vertical ray from each point downwards and adds +1 for every face it
    leaves material through (outward normal pointing down) and -1 for every face it
    enters through. The sum is the winding number: 1 inside a solid, 0 outside it or in
    a cavity (a cavity's inward-facing shell cancels the outer one).

    Args:
        triangles: (n, 3, 3) faces of closed, outward-facing bodies; faces that cannot be
            below the points may be left out.
        points: (m, 3) query points.
    """
    if len(points) == 0 or len(triangles) == 0:
        return np.zeros(len(points), dtype=np.int64)
    # Nudge the rays off the exact vertex coordinates so a ray never runs along a shared
    # edge, where it would count two faces or none.
    nudge = float(np.ptp(np.reshape(triangles, (-1, 3)), axis=0).max()) * np.array(
        [1.3e-6, 0.7e-6, 0.0]
    )
    points = points + nudge
    low, high = triangles.min(axis=1), triangles.max(axis=1)
    down = np.array([0.0, 0.0, -1.0])
    winding = np.zeros(len(points), dtype=np.int64)
    for index, (x, y, z) in enumerate(points):
        near = (low[:, 0] <= x) & (high[:, 0] >= x) & (low[:, 1] <= y) & (high[:, 1] >= y)
        near = np.flatnonzero(near & (low[:, 2] < z))
        if len(near) == 0:
            continue
        origin = np.broadcast_to(points[index], (len(near), 3))
        hit, _, leaving = _intersect(triangles[near], origin, np.broadcast_to(down, (len(near), 3)))
        winding[index] = int(np.count_nonzero(hit & leaving)) - int(
            np.count_nonzero(hit & ~leaving)
        )
    return winding


def _candidate_pairs(
    triangles: FloatArray, origins: FloatArray, directions: FloatArray, max_distance: float
) -> tuple[IntArray, IntArray]:
    """(ray, triangle) pairs that may intersect; a superset of the real hits."""
    rays, faces = len(origins), len(triangles)
    if rays * faces <= _BRUTE_FORCE_PAIRS:
        return (
            np.repeat(np.arange(rays, dtype=np.int64), faces),
            np.tile(np.arange(faces, dtype=np.int64), rays),
        )
    centres = triangles.mean(axis=1)
    radii = np.linalg.norm(triangles - centres[:, None, :], axis=2).max(axis=1)
    cutoff = float(np.percentile(radii, _LARGE_TRIANGLE_PERCENTILE))
    small = np.flatnonzero(radii <= cutoff)
    large = np.flatnonzero(radii > cutoff)
    # Cover each ray with a chain of balls: any triangle crossing the ray has its centre
    # within (half a segment + its circumradius) of some ball centre.
    segments = int(
        min(_MAX_SEGMENTS_PER_RAY, max(1, np.ceil(max_distance / max(2 * cutoff, 1e-9))))
    )
    length = max_distance / segments
    offsets = length * (np.arange(segments) + 0.5)
    queries = origins[:, None, :] + directions[:, None, :] * offsets[None, :, None]
    query_index, found = _backend.ball_pairs(
        centres[small], np.reshape(queries, (-1, 3)), length / 2 + cutoff
    )
    keys = np.unique((query_index // segments) * faces + small[found])
    ray_index, face_index = keys // faces, keys % faces
    if len(large):
        ray_index = np.concatenate(
            [ray_index, np.repeat(np.arange(rays, dtype=np.int64), len(large))]
        )
        face_index = np.concatenate([face_index, np.tile(large, rays)])
    return ray_index, face_index


def _intersect(
    triangles: FloatArray, origins: FloatArray, directions: FloatArray
) -> tuple[BoolArray, FloatArray, BoolArray]:
    """Moller-Trumbore for row-aligned rays and triangles (distance > 0 only).

    Returns:
        A hit mask, the distance along each ray (meaningful where hit), and whether the
        ray leaves the solid through that face (its outward normal points along the ray).
    """
    corner = triangles[:, 0]
    edge1 = triangles[:, 1] - corner
    edge2 = triangles[:, 2] - corner
    p = np.cross(directions, edge2)
    # determinant = -direction . (edge1 x edge2), so its sign says which side was hit.
    determinant = np.einsum("ij,ij->i", edge1, p)
    hit = np.abs(determinant) > _PARALLEL_EPS
    inverse = np.zeros_like(determinant)
    inverse[hit] = 1.0 / determinant[hit]
    to_origin = origins - corner
    u = np.einsum("ij,ij->i", to_origin, p) * inverse
    q = np.cross(to_origin, edge1)
    v = np.einsum("ij,ij->i", directions, q) * inverse
    distance = np.einsum("ij,ij->i", edge2, q) * inverse
    hit &= (u >= 0) & (v >= 0) & (u + v <= 1) & (distance > _PARALLEL_EPS)
    return hit, distance, determinant < 0
