"""Repair mesh topology in tiers, and remove loose bodies on request.

Tier ``minor`` (holes, inconsistent or inverted normals, degenerate or duplicate faces)
uses local operations that cannot change the shape, so callers may apply it by default.
The thorough pass adds fan-filling of larger holes (which can be wrong for very
non-convex holes) and, when installed, PyMeshLab's non-manifold repair.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import trimesh
from numpy.typing import NDArray

from bambu_studio_ai.mesh import _backend
from bambu_studio_ai.mesh.topology import MeshDiagnosis, body_labels, diagnose

# PyMeshLab closes holes up to this many edges; larger ones are left for the user.
_PYMESHLAB_MAX_HOLE_EDGES = 100
#: ``keep_largest_body`` refuses when the largest body holds no more than this share of
#: the surface: with no dominant body the "loose pieces" are probably real parts.
DOMINANT_BODY_SHARE = 0.5


@dataclass(frozen=True)
class RepairResult:
    """What a repair pass did."""

    before: MeshDiagnosis
    after: MeshDiagnosis
    steps: tuple[str, ...]
    """Human-readable operations applied, in order."""
    notes: tuple[str, ...]
    """What is still wrong and how to fix it."""

    @property
    def changed(self) -> bool:
        """Whether the repaired mesh differs from the input."""
        return bool(self.steps)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict."""
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "steps": list(self.steps),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class KeepMainResult:
    """What ``keep_largest_body`` did."""

    bodies: int
    removed: int
    kept_area_pct: float
    note: str


def repair_mesh(mesh: trimesh.Trimesh, *, thorough: bool) -> tuple[trimesh.Trimesh, RepairResult]:
    """Return a repaired copy of ``mesh`` and a before/after report.

    Args:
        mesh: the mesh to repair; it is not modified.
        thorough: also fan-fill holes larger than a quad and, if PyMeshLab is installed,
            repair non-manifold edges.
    """
    before = diagnose(mesh)
    work = mesh.copy()
    steps: list[str] = []
    notes: list[str] = []
    work.merge_vertices()
    work.update_faces(work.nondegenerate_faces())
    work.update_faces(work.unique_faces())
    work.remove_unreferenced_vertices()
    removed = len(mesh.faces) - len(work.faces)
    if removed:
        steps.append(f"removed {removed} degenerate or duplicate faces")
    if not before.winding_consistent:
        _backend.fix_winding(work)
        steps.append("made face winding consistent")
    if before.boundary_edges:
        unfilled = work.copy()
        _backend.fill_holes(work, use_fan=thorough)
        filled = diagnose(work)
        if filled.nonmanifold_edges > before.nonmanifold_edges:
            # Filling the rim of an open sheet doubles the sheet instead of closing a gap.
            work = unfilled
            notes.append("hole filling undone: it created non-manifold edges (open sheets?)")
        elif filled.boundary_edges < before.boundary_edges:
            steps.append(
                f"filled holes ({before.boundary_edges} -> {filled.boundary_edges} hole edges)"
            )
    if diagnose(work).inside_out:
        _backend.invert(work)
        steps.append("turned the inside-out mesh the right way round")
    after = diagnose(work)
    if thorough and not after.watertight:
        repaired = _pymeshlab_repair(work)
        if repaired is not None:
            work, after = repaired, diagnose(repaired)
            steps.append("PyMeshLab: repaired non-manifold edges and vertices, closed holes")
    notes.extend(_remaining(after, thorough=thorough))
    return work, RepairResult(before, after, tuple(steps), tuple(notes))


def keep_largest_body(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, KeepMainResult]:
    """Return a copy with only the body that has the largest surface area.

    Bodies are faces connected through shared vertices. Nothing is removed when the
    largest body holds no more than ``DOMINANT_BODY_SHARE`` of the surface.
    """
    count, labels = body_labels(mesh)
    if count <= 1:
        return mesh, KeepMainResult(count, 0, 100.0, "single body; nothing to remove")
    face_areas: NDArray[np.float64] = np.asarray(mesh.area_faces, dtype=np.float64)
    # asarray: numpy 2.4's stubs type a weighted bincount as intp, 2.5's as float64
    areas = np.asarray(np.bincount(labels, weights=face_areas, minlength=count), dtype=np.float64)
    largest = int(np.argmax(areas))
    share = float(areas[largest] / areas.sum()) if areas.sum() > 0 else 0.0
    if share <= DOMINANT_BODY_SHARE:
        note = (
            f"not removed: the largest of {count} bodies holds only {share:.0%} of the surface, "
            "so the others are probably real parts"
        )
        return mesh, KeepMainResult(count, 0, round(share * 100, 1), note)
    work = mesh.copy()
    work.update_faces(labels == largest)
    work.remove_unreferenced_vertices()
    note = f"kept the largest of {count} bodies ({share:.0%} of the surface)"
    return work, KeepMainResult(count, count - 1, round(share * 100, 1), note)


def _remaining(after: MeshDiagnosis, *, thorough: bool) -> list[str]:
    notes: list[str] = []
    if after.boundary_edges:
        hint = (
            "install pymeshlab, or use Fix Model in Bambu Studio"
            if thorough
            else "run with --repair to fill larger holes"
        )
        notes.append(f"{after.boundary_edges} hole edges remain: {hint}")
    if after.nonmanifold_edges:
        hint = (
            "install pymeshlab, use Fix Model in Bambu Studio, or remesh in Blender "
            "(Remesh modifier, Voxel, 0.15-0.25 mm)"
            if thorough
            else "run with --repair"
        )
        notes.append(f"{after.nonmanifold_edges} non-manifold edges remain: {hint}")
    return notes


def _pymeshlab_repair(mesh: trimesh.Trimesh) -> trimesh.Trimesh | None:
    """Repair with PyMeshLab if it is installed; ``None`` when it is not.

    Not covered by the test suite: PyMeshLab is an optional ~100 MB dependency.
    """
    try:
        import pymeshlab  # pyright: ignore[reportMissingImports]  # noqa: PLC0415 - optional
    except ImportError:
        return None
    # Any: pymeshlab ships no type information.
    meshlab = cast("Any", pymeshlab)
    with tempfile.TemporaryDirectory() as folder:
        # A closed file in a temp folder: Windows cannot reopen an open NamedTemporaryFile.
        path = Path(folder) / "mesh.ply"
        _backend.export(mesh, path)
        meshes = meshlab.MeshSet()
        meshes.load_new_mesh(str(path))
        meshes.meshing_remove_duplicate_vertices()
        meshes.meshing_remove_duplicate_faces()
        meshes.meshing_repair_non_manifold_edges()
        meshes.meshing_repair_non_manifold_vertices()
        meshes.meshing_close_holes(maxholesize=_PYMESHLAB_MAX_HOLE_EDGES)
        meshes.save_current_mesh(str(path))
        repaired = _backend.load(path)
    return repaired if isinstance(repaired, trimesh.Trimesh) else None
