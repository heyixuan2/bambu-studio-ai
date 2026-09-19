"""Run every check on a prepared mesh and collect the results into one report."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import trimesh

from bambu_studio_ai.mesh.checks import (
    DEFAULT_OVERHANG_LIMIT_DEG,
    BedContactResult,
    FitResult,
    FloatingResult,
    MaterialResult,
    OverhangResult,
    check_bed_contact,
    check_fit,
    check_floating,
    check_material,
    check_overhangs,
)
from bambu_studio_ai.mesh.profiles import MaterialProfile, PrinterProfile
from bambu_studio_ai.mesh.result import CheckResult
from bambu_studio_ai.mesh.score import Score, score
from bambu_studio_ai.mesh.thickness import ThicknessResult, check_wall_thickness
from bambu_studio_ai.mesh.topology import MeshDiagnosis, diagnose

Purpose = Literal["general", "decorative", "functional"]

#: Above this many triangles Bambu Studio gets slow; simplifying there is suggested.
HIGH_TRIANGLE_COUNT = 500_000
#: A part whose height is this many times its narrowest side is "slender".
SLENDER_RATIO = 5.0
SMALL_MODEL_MM = 30.0
LARGE_MODEL_MM = 200.0


@dataclass(frozen=True)
class Geometry:
    """Size facts about the mesh as analysed (in millimetres)."""

    dimensions_mm: tuple[float, float, float]
    volume_cm3: float | None
    """``None`` when the mesh is not watertight: an open mesh has no volume."""
    surface_area_cm2: float
    triangles: int
    bodies: int


@dataclass(frozen=True)
class PrintSettings:
    """Starting-point slicer settings; the user decides in Bambu Studio."""

    layer_height: str
    infill: str
    walls: str
    top_layers: str
    nozzle_temp: str
    bed_temp: str
    supports: str


@dataclass(frozen=True)
class Analysis:
    """Every check result for one mesh, and the score they add up to."""

    geometry: Geometry
    diagnosis: MeshDiagnosis
    overhangs: OverhangResult
    wall_thickness: ThicknessResult
    bed_contact: BedContactResult
    floating: FloatingResult
    fit: FitResult
    material: MaterialResult
    score: Score
    print_settings: PrintSettings
    suggestions: tuple[str, ...]

    def checks(self) -> list[tuple[str, str, CheckResult]]:
        """``(id, name, result)`` for every check, in report order."""
        return [
            ("mesh", "Mesh", _mesh_check(self.diagnosis)),
            ("build_volume", "Build volume", self.fit),
            ("floating_parts", "Floating parts", self.floating),
            ("overhangs", "Overhangs", self.overhangs),
            ("wall_thickness", "Wall thickness", self.wall_thickness),
            ("bed_contact", "Bed contact", self.bed_contact),
            ("material", "Material", self.material),
        ]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict (native floats, no NaN)."""
        checks = [
            {"id": check_id, "name": name, **result.to_dict()}
            for check_id, name, result in self.checks()
        ]
        return {
            "geometry": asdict(self.geometry),
            "mesh": self.diagnosis.to_dict(),
            "checks": checks,
            "score": self.score.value,
            "score_rubric": self.score.to_dict(),
            "issues": [r.summary for _, _, r in self.checks() if r.status == "fail"],
            "warnings": [r.summary for _, _, r in self.checks() if r.status == "warn"],
            "suggestions": list(self.suggestions),
            "print_settings": asdict(self.print_settings),
        }


def analyze(
    mesh: trimesh.Trimesh,
    *,
    material: MaterialProfile,
    printer: PrinterProfile | None,
    purpose: Purpose = "general",
    overhang_limit_deg: float = DEFAULT_OVERHANG_LIMIT_DEG,
) -> Analysis:
    """Run every printability check on ``mesh`` as it sits (lowest point on the plate).

    Args:
        mesh: the mesh in millimetres, +Z up.
        material: the filament to check against.
        printer: the target printer, or ``None`` to skip the fit and material checks.
        purpose: changes the infill and wall suggestions, never the score.
        overhang_limit_deg: overhang limit measured from vertical.
    """
    diagnosis = diagnose(mesh)
    overhangs = check_overhangs(mesh, overhang_limit_deg)
    thickness = check_wall_thickness(mesh, diagnosis, material.min_wall_mm)
    bed_contact = check_bed_contact(mesh)
    floating = check_floating(mesh)
    fit = check_fit(np.asarray(mesh.extents, dtype=np.float64), printer)
    material_fit = check_material(material, printer)
    geometry = _geometry(mesh, diagnosis)
    return Analysis(
        geometry=geometry,
        diagnosis=diagnosis,
        overhangs=overhangs,
        wall_thickness=thickness,
        bed_contact=bed_contact,
        floating=floating,
        fit=fit,
        material=material_fit,
        score=score(
            diagnosis=diagnosis,
            overhangs=overhangs,
            thickness=thickness,
            bed_contact=bed_contact,
            floating=floating,
            fit=fit,
            material=material_fit,
        ),
        print_settings=_print_settings(geometry, material, overhangs, purpose),
        suggestions=tuple(_suggestions(geometry, purpose)),
    )


def _mesh_check(diagnosis: MeshDiagnosis) -> CheckResult:
    if diagnosis.watertight and diagnosis.winding_consistent and not diagnosis.inside_out:
        return CheckResult("pass", "Watertight, with consistent outward-facing normals.")
    problems = [
        f"{diagnosis.boundary_edges} hole edges" if diagnosis.boundary_edges else "",
        f"{diagnosis.nonmanifold_edges} non-manifold edges" if diagnosis.nonmanifold_edges else "",
        "inconsistent face winding" if not diagnosis.winding_consistent else "",
        "inside out" if diagnosis.inside_out else "",
    ]
    listed = ", ".join(problem for problem in problems if problem)
    if not diagnosis.watertight:
        return CheckResult(
            "fail", f"Not watertight ({listed}); slicers may fill or drop parts of it."
        )
    return CheckResult("warn", f"Watertight, but {listed}.")


def _geometry(mesh: trimesh.Trimesh, diagnosis: MeshDiagnosis) -> Geometry:
    extents = np.asarray(mesh.extents, dtype=np.float64)
    closed = diagnosis.watertight and diagnosis.winding_consistent
    return Geometry(
        dimensions_mm=(
            round(float(extents[0]), 2),
            round(float(extents[1]), 2),
            round(float(extents[2]), 2),
        ),
        volume_cm3=round(abs(float(mesh.volume)) / 1000, 2) if closed else None,
        surface_area_cm2=round(float(mesh.area) / 100, 2),
        triangles=len(mesh.faces),
        bodies=diagnosis.bodies,
    )


def _print_settings(
    geometry: Geometry, material: MaterialProfile, overhangs: OverhangResult, purpose: Purpose
) -> PrintSettings:
    largest = max(geometry.dimensions_mm)
    layer = "0.20 mm"
    if largest < SMALL_MODEL_MM:
        layer = "0.12 mm (small model, finer detail)"
    elif largest > LARGE_MODEL_MM:
        layer = "0.28 mm (large model, faster)"
    infill = {
        "decorative": f"{material.infill_decorative_pct} %",
        "functional": f"{material.infill_functional_pct} %",
        "general": "15-30 % (depends on what the part is for)",
    }[purpose]
    return PrintSettings(
        layer_height=layer,
        infill=infill,
        walls=">= 4" if purpose == "functional" else ">= 3",
        top_layers=">= 5",
        nozzle_temp=f"{material.nozzle_min_c}-{material.nozzle_max_c} C",
        bed_temp=f"{material.bed_c} C",
        supports="likely not needed" if overhangs.status == "pass" else "needed for the overhangs",
    )


def _suggestions(geometry: Geometry, purpose: Purpose) -> list[str]:
    suggestions: list[str] = []
    x, y, z = geometry.dimensions_mm
    narrowest = min(x, y)
    if z >= max(x, y) and narrowest > 0 and z / narrowest > SLENDER_RATIO:
        suggestions.append(
            f"Tall and slender ({z / narrowest:.0f}x taller than its narrowest side): it is "
            "weakest across its layer lines, so print it lying down if it has to carry load."
        )
    if geometry.triangles > HIGH_TRIANGLE_COUNT:
        suggestions.append(
            f"{geometry.triangles:,} triangles: if Bambu Studio is slow, simplify it there "
            "(right-click the model, Simplify Model)."
        )
    if purpose == "functional":
        suggestions.append(
            "Functional part: use 4 walls, and leave about 0.2 mm clearance where parts "
            "fit together."
        )
    return suggestions
