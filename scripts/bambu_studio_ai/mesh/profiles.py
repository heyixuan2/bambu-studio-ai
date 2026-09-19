"""The printer and material facts the checks need, passed in by the caller.

The data itself lives elsewhere (``scripts/common.py`` today); keeping it out of the
analysis code means the checks can be tested with any numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrinterProfile:
    """A printer, as far as printability is concerned."""

    name: str
    usable_volume_mm: tuple[float, float, float]
    """X, Y, Z space the model may occupy (already reduced by any safety margin)."""
    enclosed: bool
    high_temp: bool
    """Has a hotend for materials that print above 300 C."""


@dataclass(frozen=True)
class MaterialProfile:
    """A filament, as far as printability is concerned."""

    name: str
    min_wall_mm: float
    """Thinnest wall this material is recommended for."""
    nozzle_min_c: int
    nozzle_max_c: int
    bed_c: int
    infill_decorative_pct: int
    infill_functional_pct: int
    needs_enclosure: bool

    @property
    def needs_high_temp(self) -> bool:
        """Whether even the coolest recommended nozzle temperature is above 300 C."""
        return self.nozzle_min_c > HIGH_TEMP_NOZZLE_C


#: Nozzle temperature above which a material needs a high-temperature hotend.
HIGH_TEMP_NOZZLE_C = 300
