"""Printability checks that look at the mesh as it would sit on the build plate.

The model is taken as placed: its lowest point is on the plate and +Z is up, which is
how Bambu Studio drops an imported object onto the plate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import trimesh

from bambu_studio_ai.mesh._backend import BoolArray, FloatArray
from bambu_studio_ai.mesh.profiles import MaterialProfile, PrinterProfile
from bambu_studio_ai.mesh.rays import material_below
from bambu_studio_ai.mesh.result import CheckResult, Status
from bambu_studio_ai.mesh.topology import body_labels

#: Overhang limit, measured from vertical: a face overhangs when its outward normal
#: points down at more than this angle from vertical (the usual 45 degree rule).
DEFAULT_OVERHANG_LIMIT_DEG = 45.0
#: Faces and bodies within this height of the plate count as resting on it.
PLATE_TOLERANCE_MM = 0.1
#: A face counts as flat on the plate when its normal is within this angle of straight down.
FLAT_FACE_DEG = 5.0

OVERHANG_WARN_PCT = 5.0
OVERHANG_FAIL_PCT = 20.0
#: Less contact than this is a point or an edge touching the plate.
MIN_CONTACT_MM2 = 1.0
#: Contact below this share of the footprint (bounding box in X/Y) risks the part
#: coming loose or tipping over.
SMALL_CONTACT_PCT = 5.0

FULL_SIZE_PCT = 100.0
_PROBES_PER_BODY = 64
_PROBE_SEED = 0


@dataclass(frozen=True)
class OverhangResult(CheckResult):
    """Surface that faces down more steeply than the overhang limit."""

    limit_deg: float
    area_mm2: float
    area_pct: float


@dataclass(frozen=True)
class BedContactResult(CheckResult):
    """Area of the model lying flat on the plate."""

    contact_mm2: float
    footprint_mm2: float
    contact_pct: float
    """Contact area as a share of the X/Y bounding box."""


@dataclass(frozen=True)
class FloatingResult(CheckResult):
    """Bodies that would start printing in mid-air."""

    bodies: int
    floating: int
    lowest_floating_gap_mm: float | None
    """Height of the lowest floating body above the plate."""


@dataclass(frozen=True)
class FitResult(CheckResult):
    """Whether the model fits the printer's usable build volume."""

    usable_mm: tuple[float, float, float] | None
    fits: bool | None
    rotate_on_plate: bool
    """Fits only when turned 90 degrees on the plate."""
    max_scale_pct: float | None
    """Largest uniform scale (percent of the current size) that fits."""


@dataclass(frozen=True)
class MaterialResult(CheckResult):
    """Whether the printer can print the material."""

    problems: tuple[str, ...]


def overhang_mask(
    normal_z: FloatArray, face_top_z: FloatArray, plate_z: float, limit_deg: float
) -> BoolArray:
    """Faces that overhang more than ``limit_deg`` from vertical and are not on the plate.

    A face tilted by angle a from vertical has a normal ``sin(a)`` below horizontal, so
    it overhangs when ``normal_z < -sin(limit)``.
    """
    steep = normal_z < -math.sin(math.radians(limit_deg))
    return steep & (face_top_z - plate_z >= PLATE_TOLERANCE_MM)


def contact_mask(normal_z: FloatArray, face_top_z: FloatArray, plate_z: float) -> BoolArray:
    """Faces lying flat on the plate."""
    flat = normal_z < -math.cos(math.radians(FLAT_FACE_DEG))
    return flat & (face_top_z - plate_z < PLATE_TOLERANCE_MM)


def check_overhangs(mesh: trimesh.Trimesh, limit_deg: float) -> OverhangResult:
    """Area-weighted share of the surface that overhangs more than ``limit_deg``."""
    areas = mesh.area_faces
    top = mesh.triangles[:, :, 2].max(axis=1)
    mask = overhang_mask(mesh.face_normals[:, 2], top, float(mesh.bounds[0][2]), limit_deg)
    area = float(areas[mask].sum())
    pct = round(100 * area / float(areas.sum()), 1) if areas.sum() > 0 else 0.0
    status: Status = "pass"
    summary = f"No surface overhangs more than {limit_deg:g} deg from vertical."
    if area > 0:
        summary = (
            f"{pct:g} % of the surface ({area / 100:.1f} cm2) overhangs more than "
            f"{limit_deg:g} deg from vertical."
        )
    if pct > OVERHANG_FAIL_PCT:
        status, summary = "fail", summary + " Needs supports or a different orientation."
    elif pct > OVERHANG_WARN_PCT:
        status, summary = "warn", summary + " Probably needs supports (tree supports work well)."
    return OverhangResult(status, summary, limit_deg, round(area, 1), pct)


def check_bed_contact(mesh: trimesh.Trimesh) -> BedContactResult:
    """Area lying flat on the plate, compared with the model's X/Y footprint."""
    top = mesh.triangles[:, :, 2].max(axis=1)
    mask = contact_mask(mesh.face_normals[:, 2], top, float(mesh.bounds[0][2]))
    contact = float(mesh.area_faces[mask].sum())
    footprint = float(mesh.extents[0] * mesh.extents[1])
    pct = round(100 * contact / footprint, 1) if footprint > 0 else 0.0
    if contact < MIN_CONTACT_MM2:
        return BedContactResult(
            "warn",
            "Touches the plate only at a point or an edge: add a brim or supports, or reorient.",
            round(contact, 1),
            round(footprint, 1),
            pct,
        )
    summary = f"{contact:.0f} mm2 lies flat on the plate ({pct:g} % of the footprint)."
    if pct < SMALL_CONTACT_PCT:
        return BedContactResult(
            "warn",
            summary + " Small base: consider a brim.",
            round(contact, 1),
            round(footprint, 1),
            pct,
        )
    return BedContactResult("pass", summary, round(contact, 1), round(footprint, 1), pct)


def check_floating(mesh: trimesh.Trimesh) -> FloatingResult:
    """Bodies whose lowest point is above the plate with no material directly under it.

    A body resting on or embedded in another body is supported, and so is the inner
    shell of a hollow part: probes just below its lowest points land inside material.
    """
    count, labels = body_labels(mesh)
    plate = float(mesh.bounds[0][2])
    triangles = np.asarray(mesh.triangles, dtype=np.float64)
    bottoms = np.full(count, np.inf)
    np.minimum.at(bottoms, labels, triangles[:, :, 2].min(axis=1))
    order = np.argsort(labels, kind="stable")
    starts = np.searchsorted(labels[order], np.arange(count + 1))
    corner_low, corner_high = triangles.min(axis=1), triangles.max(axis=1)
    gaps: list[float] = []
    for body in np.flatnonzero(bottoms - plate > PLATE_TOLERANCE_MM):
        faces = order[starts[body] : starts[body + 1]]
        probes = _bottom_probes(triangles[faces], float(bottoms[body]))
        probes[:, 2] -= PLATE_TOLERANCE_MM
        under = _overlapping(corner_low, corner_high, probes)
        if not (material_below(triangles[under], probes) > 0).any():
            gaps.append(float(bottoms[body]) - plate)
    if not gaps:
        summary = (
            "One body, resting on the plate."
            if count == 1
            else f"All {count} bodies rest on the plate or on other parts."
        )
        return FloatingResult("pass", summary, count, 0, None)
    what = "body starts" if len(gaps) == 1 else "bodies start"
    summary = (
        f"{len(gaps)} of {count} {what} in mid-air (lowest {min(gaps):.1f} mm above the "
        "plate, nothing under it). Remove them (--keep-main), connect them, or add supports."
    )
    return FloatingResult("fail", summary, count, len(gaps), round(min(gaps), 2))


def check_fit(extents: FloatArray, printer: PrinterProfile | None) -> FitResult:
    """Compare the bounding box with the printer's usable build volume."""
    if printer is None:
        return FitResult(
            status="skipped",
            summary="Unknown printer: build volume not checked.",
            usable_mm=None,
            fits=None,
            rotate_on_plate=False,
            max_scale_pct=None,
        )
    usable = printer.usable_volume_mm
    size = tuple(float(value) for value in extents)
    straight = _max_scale_pct(size, usable)
    turned = _max_scale_pct(size, (usable[1], usable[0], usable[2]))
    volume = (
        " x ".join(f"{value:g}" for value in usable)
        + " mm usable, a safety margin inside the printer's spec"
    )
    if straight >= FULL_SIZE_PCT or turned >= FULL_SIZE_PCT:
        rotate = straight < FULL_SIZE_PCT
        how = " when turned 90 deg on the plate" if rotate else ""
        return FitResult(
            status="warn" if rotate else "pass",
            summary=f"Fits the {printer.name} ({volume}){how}.",
            usable_mm=usable,
            fits=True,
            rotate_on_plate=rotate,
            max_scale_pct=_floor_tenth(max(straight, turned)),
        )
    best = max(straight, turned)
    over = ", ".join(
        f"{axis} {s:.1f} mm > {u:g} mm"
        for axis, s, u in zip("XYZ", size, usable, strict=True)
        if s > u
    )
    return FitResult(
        status="fail",
        summary=(
            f"Too big for the {printer.name}: {over} ({volume}). "
            f"Scale to at most {math.floor(best * 10) / 10:g} % or split the model."
        ),
        usable_mm=usable,
        fits=False,
        rotate_on_plate=False,
        max_scale_pct=_floor_tenth(best),
    )


def check_material(material: MaterialProfile, printer: PrinterProfile | None) -> MaterialResult:
    """Enclosure and hotend-temperature requirements of the material."""
    if printer is None:
        return MaterialResult("skipped", "Unknown printer: material compatibility not checked.", ())
    problems: list[str] = []
    if material.needs_enclosure and not printer.enclosed:
        problems.append(
            f"{material.name} needs an enclosed printer; the {printer.name} is open-frame"
        )
    if material.needs_high_temp and not printer.high_temp:
        problems.append(
            f"{material.name} prints at {material.nozzle_min_c}-{material.nozzle_max_c} C, "
            f"hotter than the {printer.name}'s hotend"
        )
    if problems:
        return MaterialResult("fail", "; ".join(problems) + ".", tuple(problems))
    return MaterialResult("pass", f"{material.name} suits the {printer.name}.", ())


def _floor_tenth(value: float) -> float | None:
    """Round down to 0.1, so a suggested scale never overshoots; ``None`` if unbounded."""
    return math.floor(value * 10) / 10 if math.isfinite(value) else None


def _max_scale_pct(size: tuple[float, ...], usable: tuple[float, float, float]) -> float:
    """Largest uniform scale, in percent, at which ``size`` fits inside ``usable``."""
    ratios = [room / extent for room, extent in zip(usable, size, strict=True) if extent > 0]
    return min(ratios, default=math.inf) * 100


def _bottom_probes(triangles: FloatArray, bottom: float) -> FloatArray:
    """Points on the lowest part of a body: its lowest vertices and area samples near them."""
    corners = np.reshape(triangles, (-1, 3))
    lowest = corners[corners[:, 2] <= bottom + PLATE_TOLERANCE_MM][:_PROBES_PER_BODY]
    band = triangles[triangles[:, :, 2].min(axis=1) <= bottom + PLATE_TOLERANCE_MM]
    edges = np.cross(band[:, 1] - band[:, 0], band[:, 2] - band[:, 0])
    areas = np.linalg.norm(edges, axis=1)
    if areas.sum() <= 0:
        return np.copy(lowest)
    rng = np.random.default_rng(_PROBE_SEED)
    chosen = rng.choice(len(band), size=_PROBES_PER_BODY, p=areas / areas.sum())
    u, v = rng.random((2, _PROBES_PER_BODY))
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    picked = band[chosen]
    samples = (
        picked[:, 0]
        + u[:, None] * (picked[:, 1] - picked[:, 0])
        + v[:, None] * (picked[:, 2] - picked[:, 0])
    )
    samples = samples[samples[:, 2] <= bottom + PLATE_TOLERANCE_MM]
    return np.concatenate([lowest, samples])


def _overlapping(corner_low: FloatArray, corner_high: FloatArray, probes: FloatArray) -> BoolArray:
    """Triangles whose X/Y extent overlaps the probes' (the only ones a vertical ray can hit)."""
    low = probes.min(axis=0) - PLATE_TOLERANCE_MM
    high = probes.max(axis=0) + PLATE_TOLERANCE_MM
    overlap = (corner_low[:, 0] <= high[0]) & (corner_high[:, 0] >= low[0])
    return overlap & (corner_low[:, 1] <= high[1]) & (corner_high[:, 1] >= low[1])
