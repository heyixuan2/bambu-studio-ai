"""Turn check results into a 0-10 printability score with a published rubric.

The score starts at 10 and loses points for graded problems. Hard failures (the mesh
is not watertight, a body starts in mid-air, the model does not fit the printer) cap it
at ``HARD_FAIL_CAP`` however good the rest is. Every rule, and what it cost this model,
is part of the result so the number can be explained.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from bambu_studio_ai.mesh.checks import (
    MIN_CONTACT_MM2,
    SMALL_CONTACT_PCT,
    BedContactResult,
    FitResult,
    FloatingResult,
    MaterialResult,
    OverhangResult,
)
from bambu_studio_ai.mesh.thickness import ThicknessResult
from bambu_studio_ai.mesh.topology import MeshDiagnosis

MAX_SCORE = 10.0
HARD_FAIL_CAP = 4.0
_PCT_PER_POINT = 5.0
_MAX_OVERHANG_POINTS = 4.0
_MAX_THIN_POINTS = 4.0
_POINT_CONTACT_POINTS = 2.0
_SMALL_CONTACT_POINTS = 1.0
_MATERIAL_POINTS = 3.0


@dataclass(frozen=True)
class Deduction:
    """One graded rule and the points it cost."""

    check: str
    rule: str
    points: float


@dataclass(frozen=True)
class Cap:
    """One hard-failure rule and whether it applied."""

    check: str
    rule: str
    limit: float
    applied: bool


@dataclass(frozen=True)
class Score:
    """A printability score and the rubric that produced it."""

    value: float
    deductions: tuple[Deduction, ...]
    caps: tuple[Cap, ...]

    def to_dict(self) -> dict[str, object]:
        """Return the rubric as a JSON-serialisable dict."""
        return {
            "max": MAX_SCORE,
            "deductions": [asdict(line) for line in self.deductions],
            "caps": [asdict(cap) for cap in self.caps],
        }


def score(  # noqa: PLR0913 - one argument per check keeps the rubric explicit
    *,
    diagnosis: MeshDiagnosis,
    overhangs: OverhangResult,
    thickness: ThicknessResult,
    bed_contact: BedContactResult,
    floating: FloatingResult,
    fit: FitResult,
    material: MaterialResult,
) -> Score:
    """Score a model from its check results."""
    thin_pct = thickness.thin_area_pct or 0.0
    contact_points = 0.0
    if bed_contact.contact_mm2 < MIN_CONTACT_MM2:
        contact_points = _POINT_CONTACT_POINTS
    elif bed_contact.contact_pct < SMALL_CONTACT_PCT:
        contact_points = _SMALL_CONTACT_POINTS
    deductions = (
        Deduction(
            "overhangs",
            f"-1 per {_PCT_PER_POINT:g} % of the surface overhanging past the limit, "
            f"at most -{_MAX_OVERHANG_POINTS:g}",
            -min(_MAX_OVERHANG_POINTS, overhangs.area_pct / _PCT_PER_POINT),
        ),
        Deduction(
            "wall_thickness",
            f"-1 per {_PCT_PER_POINT:g} % of the surface thinner than the material's minimum "
            f"wall, at most -{_MAX_THIN_POINTS:g} (0 when not measured)",
            -min(_MAX_THIN_POINTS, thin_pct / _PCT_PER_POINT),
        ),
        Deduction(
            "bed_contact",
            f"-{_POINT_CONTACT_POINTS:g} if it touches the plate only at a point or edge "
            f"(< {MIN_CONTACT_MM2:g} mm2), -{_SMALL_CONTACT_POINTS:g} if the flat contact is "
            f"under {SMALL_CONTACT_PCT:g} % of the footprint",
            -contact_points,
        ),
        Deduction(
            "material",
            f"-{_MATERIAL_POINTS:g} if the printer cannot print the material "
            "(no enclosure, or hotend too cool)",
            -_MATERIAL_POINTS if material.status == "fail" else 0.0,
        ),
    )
    caps = (
        Cap("mesh", "not watertight (after any repair)", HARD_FAIL_CAP, not diagnosis.watertight),
        Cap("floating_parts", "a body starts in mid-air", HARD_FAIL_CAP, floating.floating > 0),
        Cap("build_volume", "does not fit the printer", HARD_FAIL_CAP, fit.fits is False),
    )
    # Round each line first so the published lines add up to the score exactly;
    # + 0.0 turns -0.0 into 0.0 so the JSON never shows "-0.0".
    rounded = tuple(Deduction(d.check, d.rule, round(d.points, 1) + 0.0) for d in deductions)
    value = MAX_SCORE + sum(line.points for line in rounded)
    for cap in caps:
        if cap.applied:
            value = min(value, cap.limit)
    return Score(round(max(0.0, value), 1), rounded, caps)
