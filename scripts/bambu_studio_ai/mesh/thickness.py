"""Estimate wall thickness by casting rays inwards from points on the surface.

From each of a fixed number of area-weighted random surface points, a ray goes straight
into the material (against the face normal) until it leaves the solid again; that
distance is the local thickness. Because the points are spread by area, the share of
points below a threshold is the share of the surface that is that thin.

Known limits: sharp edges and tips read thin (they are), and where separate shells
overlap (common in AI meshes) a few points can read thin that are not; the verdict
therefore rests on the thin share of the surface, not on the single thinnest point.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from bambu_studio_ai.mesh import _backend
from bambu_studio_ai.mesh.rays import first_exit_distances
from bambu_studio_ai.mesh.result import CheckResult, Status
from bambu_studio_ai.mesh.topology import MeshDiagnosis

SAMPLES = 2000
#: Rays are followed this far; anything thicker is reported as this value.
MAX_MEASURED_MM = 10.0
#: Share of the surface below the minimum wall that is still a pass (edges and tips).
THIN_WARN_PCT = 1.0
#: Above this share of thin surface the part is weak or may not print.
THIN_FAIL_PCT = 5.0
_SEED = 0
_PERCENTILE = 5


@dataclass(frozen=True)
class ThicknessResult(CheckResult):
    """Wall thickness measured at points spread evenly over the surface."""

    min_wall_mm: float
    """The material's recommended minimum wall."""
    thin_area_pct: float | None
    """Share of the surface thinner than ``min_wall_mm``."""
    min_mm: float | None
    p5_mm: float | None
    """5th percentile: 95 % of the surface is at least this thick."""
    samples: int
    max_measured_mm: float
    """Thicker regions are reported as this value."""


def check_wall_thickness(
    mesh: trimesh.Trimesh, diagnosis: MeshDiagnosis, min_wall_mm: float
) -> ThicknessResult:
    """Measure how much of the surface is thinner than ``min_wall_mm``.

    Rays only mean something on a closed, outward-facing mesh, so other meshes are
    skipped rather than guessed at.
    """
    if not diagnosis.watertight or not diagnosis.winding_consistent or diagnosis.inside_out:
        return ThicknessResult(
            status="skipped",
            summary="Not measured: wall thickness needs a watertight mesh (see the mesh check).",
            min_wall_mm=min_wall_mm,
            thin_area_pct=None,
            min_mm=None,
            p5_mm=None,
            samples=0,
            max_measured_mm=MAX_MEASURED_MM,
        )
    points, faces = _backend.sample_surface(mesh, SAMPLES, _SEED)
    inwards = -np.asarray(mesh.face_normals, dtype=np.float64)[faces]
    distances = first_exit_distances(mesh, points, inwards, MAX_MEASURED_MM)
    thickness = np.minimum(distances, MAX_MEASURED_MM)
    thin_pct = round(float(np.mean(thickness < min_wall_mm)) * 100, 1)
    thinnest = round(float(thickness.min()), 2)
    p5 = round(float(np.percentile(thickness, _PERCENTILE)), 2)
    status: Status = "pass"
    if thin_pct > THIN_FAIL_PCT:
        status = "fail"
    elif thin_pct > THIN_WARN_PCT:
        status = "warn"
    return ThicknessResult(
        status=status,
        summary=_summary(thin_pct, thinnest, p5, min_wall_mm, status),
        min_wall_mm=min_wall_mm,
        thin_area_pct=thin_pct,
        min_mm=thinnest,
        p5_mm=p5,
        samples=len(points),
        max_measured_mm=MAX_MEASURED_MM,
    )


def _summary(thin_pct: float, thinnest: float, p5: float, min_wall: float, status: Status) -> str:
    if thin_pct == 0:
        return (
            f"No wall thinner than {min_wall:g} mm found at {SAMPLES} points "
            f"(95 % of the surface is at least {p5:g} mm)."
        )
    text = (
        f"{thin_pct:g} % of the surface is thinner than {min_wall:g} mm "
        f"(thinnest {thinnest:g} mm, 95 % at least {p5:g} mm)."
    )
    if status == "fail":
        return (
            text + " Thicken the walls or scale the model up; thin walls print weak or not at all."
        )
    if status == "warn":
        return text + " Usually edges or tips; check them in the preview."
    return text + " A small share, typically sharp edges or tips."
