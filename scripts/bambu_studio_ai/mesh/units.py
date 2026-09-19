"""Decide which unit a model's coordinates are in, and say how sure that is.

Most mesh formats (STL, OBJ, PLY) carry no unit, and GLB files from AI generators use
arbitrary scales despite glTF's metre convention. So the numbers are only converted
when the evidence is strong: the user said so, a 3MF file declares its unit, or the
model is too small to be anything but metres. Otherwise millimetres are assumed and
the assumption is reported, never applied silently.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

#: Millimetres per unit for ``--unit``.
MM_PER_UNIT = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}

# Unit names used in 3MF's ``unit`` attribute (and trimesh's spelling of them).
_DECLARED_UNITS = {
    "micron": ("um", 0.001),
    "millimeter": ("mm", 1.0),
    "millimeters": ("mm", 1.0),
    "centimeter": ("cm", 10.0),
    "centimeters": ("cm", 10.0),
    "meter": ("m", 1000.0),
    "meters": ("m", 1000.0),
    "inch": ("in", 25.4),
    "inches": ("in", 25.4),
    "foot": ("ft", 304.8),
    "feet": ("ft", 304.8),
}

#: A model whose largest dimension is below this many file units cannot be millimetres
#: (nothing that small prints), and read as metres it is a plausible 0-500 mm object.
METRES_BELOW = 0.5
#: Below this many millimetres the model is suspiciously small, so the note says how to
#: override the assumption.
SMALL_MODEL_MM = 10.0

UnitSource = Literal["flag", "file", "size", "assumed"]


@dataclass(frozen=True)
class UnitDecision:
    """Which unit the coordinates are in and the factor that converts them to mm."""

    unit: str
    scale: float
    """Multiply coordinates by this to get millimetres."""
    source: UnitSource
    """``flag`` (--unit), ``file`` (declared in a 3MF), ``size`` (too small to be mm)
    or ``assumed`` (no evidence; millimetres)."""
    note: str
    doubtful: bool = False
    """The guess could easily be wrong; show ``note`` to the user."""

    def to_dict(self) -> dict[str, str | float | bool]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


def decide_units(
    largest_dimension: float, *, requested: str | None, declared: str | None
) -> UnitDecision:
    """Pick the unit of a model from the strongest evidence available.

    Args:
        largest_dimension: largest bounding-box side, in file units.
        requested: unit from ``--unit`` (a key of ``MM_PER_UNIT``), or ``None`` for auto.
        declared: unit named inside the file (3MF), or ``None``.
    """
    if requested is not None:
        scale = MM_PER_UNIT[requested]
        return UnitDecision(requested, scale, "flag", f"Units: {requested} (from --unit).")
    if declared is not None and declared.lower() in _DECLARED_UNITS:
        unit, scale = _DECLARED_UNITS[declared.lower()]
        converted = "" if scale == 1.0 else f", converted to mm (x{scale:g})"
        return UnitDecision(
            unit, scale, "file", f"Units: {declared}, declared in the file{converted}."
        )
    if 0 < largest_dimension < METRES_BELOW:
        return UnitDecision(
            "m",
            MM_PER_UNIT["m"],
            "size",
            f"Units: the model is only {largest_dimension:.3g} units across, too small to be "
            "millimetres, so it was read as metres (x1000). If that is wrong, pass --unit.",
            doubtful=True,
        )
    if largest_dimension < SMALL_MODEL_MM:
        note = (
            f"Units: assumed millimetres, which makes the model {largest_dimension:.3g} mm across. "
            "If it was exported in another unit, pass --unit cm|in|m, or --height."
        )
        return UnitDecision("mm", 1.0, "assumed", note, doubtful=True)
    return UnitDecision("mm", 1.0, "assumed", "Units: assumed millimetres (the file does not say).")
