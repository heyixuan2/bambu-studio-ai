"""Suggest the nearest filament from a catalogue for each palette colour."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from bambu_studio_ai.color.lab import delta_e_2000, parse_hex, srgb_to_lab

METRIC = "CIEDE2000"
"""The colour difference reported as ``delta_e``: about 2 is barely visible, above 10 is
clearly a different colour."""


@dataclass(frozen=True)
class Filament:
    """One catalogue entry, e.g. ``Filament("PLA Basic", "Jade White", "#FFFFFF")``."""

    line: str
    name: str
    hex: str


@dataclass(frozen=True)
class FilamentMatch:
    """The closest filament to a palette colour."""

    filament: Filament
    delta_e: float
    """CIEDE2000 between the palette colour and the filament's catalogue colour."""


def nearest_filaments(
    colours: Sequence[str], catalogue: Sequence[Filament]
) -> list[FilamentMatch | None]:
    """For each ``#RRGGBB`` colour, the catalogue filament with the smallest CIEDE2000.

    Translucent filaments are skipped: a see-through spool is never the right match for
    an opaque texture colour. Returns ``None`` entries when the catalogue is empty.
    """
    candidates = [f for f in catalogue if "translucent" not in f.line.lower()]
    if not candidates:
        return [None] * len(colours)
    palette_lab = srgb_to_lab(np.array([parse_hex(c) for c in colours]))
    catalogue_lab = srgb_to_lab(np.array([parse_hex(f.hex) for f in candidates]))
    distances = delta_e_2000(palette_lab[:, None, :], catalogue_lab[None, :, :])
    best = np.argmin(distances, axis=1)
    return [
        FilamentMatch(candidates[int(j)], round(float(distances[i, j]), 1))
        for i, j in enumerate(best)
    ]
