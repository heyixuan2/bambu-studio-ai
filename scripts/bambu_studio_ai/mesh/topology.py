"""Count what is wrong with a mesh's topology, and find its separate bodies."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import trimesh

from bambu_studio_ai.mesh import _backend
from bambu_studio_ai.mesh._backend import IntArray

RepairTier = Literal["none", "minor", "major"]

_EDGES_PER_MANIFOLD_EDGE = 2


@dataclass(frozen=True)
class MeshDiagnosis:
    """Topology counts for a triangle mesh.

    A mesh is watertight when every edge is shared by exactly two faces: it then has
    no boundary edges (holes) and no non-manifold edges (three or more faces).
    """

    faces: int
    watertight: bool
    winding_consistent: bool
    """Neighbouring faces agree on which side is outside."""
    inside_out: bool
    """Watertight, but the normals point inwards (negative volume)."""
    boundary_edges: int
    """Edges used by one face: the rims of holes."""
    nonmanifold_edges: int
    """Edges used by three or more faces."""
    degenerate_faces: int
    """Faces with (near) zero area."""
    bodies: int
    """Groups of faces connected through shared vertices."""

    @property
    def repair_tier(self) -> RepairTier:
        """How invasive a repair would be.

        ``none``: nothing to fix. ``minor``: holes, flipped or degenerate faces, all fixed
        by low-risk local operations. ``major``: non-manifold edges, which need edits
        that can change the shape.
        """
        if self.nonmanifold_edges:
            return "major"
        clean = self.watertight and self.winding_consistent and not self.inside_out
        return "none" if clean and not self.degenerate_faces else "minor"

    def to_dict(self) -> dict[str, int | bool | str]:
        """Return a JSON-serialisable dict, including the repair tier."""
        return {**asdict(self), "repair_tier": self.repair_tier}


def diagnose(mesh: trimesh.Trimesh) -> MeshDiagnosis:
    """Count holes, non-manifold edges, flipped and degenerate faces, and bodies."""
    edge_uses = _edge_use_counts(mesh)
    boundary = int(np.count_nonzero(edge_uses == 1))
    nonmanifold = int(np.count_nonzero(edge_uses > _EDGES_PER_MANIFOLD_EDGE))
    watertight = boundary == 0 and nonmanifold == 0
    winding_consistent = bool(mesh.is_winding_consistent)
    inside_out = watertight and winding_consistent and float(mesh.volume) < 0
    degenerate = int(np.count_nonzero(~mesh.nondegenerate_faces()))
    count, _ = body_labels(mesh)
    return MeshDiagnosis(
        faces=len(mesh.faces),
        watertight=watertight,
        winding_consistent=winding_consistent,
        inside_out=inside_out,
        boundary_edges=boundary,
        nonmanifold_edges=nonmanifold,
        degenerate_faces=degenerate,
        bodies=count,
    )


def body_labels(mesh: trimesh.Trimesh) -> tuple[int, IntArray]:
    """Number of bodies, and the body index of every face.

    Faces belong to the same body when they share a vertex. That is looser than
    trimesh's ``split`` (which follows manifold edges only), so a mesh that is merely
    non-manifold is not reported as dozens of loose pieces.
    """
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(faces) == 0:
        return 0, np.zeros(0, dtype=np.int64)
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]]])
    vertex_labels = _backend.connected_labels(len(mesh.vertices), edges)
    _, face_labels = np.unique(vertex_labels[faces[:, 0]], return_inverse=True)
    face_labels = np.ravel(np.asarray(face_labels, dtype=np.int64))
    return int(face_labels.max()) + 1, face_labels


def _edge_use_counts(mesh: trimesh.Trimesh) -> IntArray:
    """How many faces use each distinct edge."""
    edges = np.asarray(mesh.edges_sorted, dtype=np.int64)
    if len(edges) == 0:
        return np.zeros(0, dtype=np.int64)
    keys = edges[:, 0] * (int(edges.max()) + 1) + edges[:, 1]
    _, counts = np.unique(keys, return_counts=True)
    return np.asarray(counts, dtype=np.int64)
