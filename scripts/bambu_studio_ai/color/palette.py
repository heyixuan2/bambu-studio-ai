"""Choose up to N filament colours for a set of surface colour samples.

1. Samples are binned (5 bits per sRGB channel) so the clustering works on a few
   thousand weighted colours instead of millions of samples.
2. Weighted k-means in CIELAB over-segments the bins into ``3 x N`` (at least
   :data:`OVERSEGMENT_MIN`) clusters, seeded deterministically.
3. Clusters covering less than ``min_area`` of the visible surface join their nearest
   neighbour; then the two closest clusters (CIEDE2000) merge until at most N remain and
   no two are closer than :data:`MERGE_DELTA_E`. Merging by colour difference rather than
   by variance is what lets a small, distinct feature (dark eyes on a light face) keep
   its own filament while shading variations of one colour collapse into one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from bambu_studio_ai.color.lab import (
    FloatArray,
    delta_e_2000,
    lab_to_srgb,
    parse_hex,
    srgb_to_lab,
    to_hex,
)

MAX_COLORS = 8
"""One AMS unit holds four spools and Bambu Studio paints with up to eight here."""
DEFAULT_MAX_COLORS = 4
DEFAULT_MIN_AREA = 0.002
"""A colour must cover 0.2 % of the visible surface to get its own filament."""
MERGE_DELTA_E = 10.0
"""Clusters closer than this (CIEDE2000) print as the same filament anyway."""
OVERSEGMENT_MIN = 16
BIN_BITS = 5
_KMEANS_ITERATIONS = 40
_REFINE_ROUNDS = 3


@dataclass(frozen=True)
class ColourBins:
    """Samples grouped into small sRGB cubes."""

    lab: FloatArray
    """``(B, 3)`` mean colour of each bin."""
    weight: FloatArray
    """``(B,)`` total sample weight (visible area) in each bin."""
    of_sample: NDArray[np.int64]
    """``(S,)`` bin of every sample."""


@dataclass(frozen=True)
class Palette:
    """The filament colours, in filament order."""

    rgb: FloatArray
    """``(K, 3)`` sRGB, rounded to what ``#RRGGBB`` can express."""

    @property
    def lab(self) -> FloatArray:
        """The colours in CIELAB."""
        return srgb_to_lab(self.rgb)

    @property
    def hex(self) -> list[str]:
        """The colours as ``#RRGGBB``."""
        return [to_hex(colour) for colour in self.rgb]

    def __len__(self) -> int:
        """Number of colours."""
        return len(self.rgb)

    @classmethod
    def from_hex(cls, colours: list[str]) -> Palette:
        """A fixed palette, e.g. the filaments loaded in the user's AMS.

        Raises:
            ValueError: on a malformed colour, or more than :data:`MAX_COLORS` colours.
        """
        if not 1 <= len(colours) <= MAX_COLORS:
            raise ValueError(f"give between 1 and {MAX_COLORS} colours, not {len(colours)}")
        return cls(np.array([parse_hex(colour) for colour in colours]))

    @classmethod
    def from_lab(cls, lab: FloatArray) -> Palette:
        """Palette from CIELAB centres, snapped to 8-bit sRGB."""
        return cls(np.round(lab_to_srgb(lab) * 255) / 255)


def bin_colours(rgb: FloatArray, weight: FloatArray) -> ColourBins:
    """Group samples into ``2**BIN_BITS`` levels per channel."""
    levels = 2**BIN_BITS
    quantised = np.minimum((rgb * levels).astype(np.int64), levels - 1)
    keys = (quantised[:, 0] * levels + quantised[:, 1]) * levels + quantised[:, 2]
    unique, of_sample = np.unique(keys, return_inverse=True)
    counts = np.bincount(of_sample, minlength=len(unique)).astype(np.float64)
    mean_rgb = np.stack(
        [np.bincount(of_sample, rgb[:, c], len(unique)) / counts for c in range(3)], axis=1
    )
    return ColourBins(
        lab=srgb_to_lab(mean_rgb),
        weight=np.bincount(of_sample, weight, len(unique)).astype(np.float64),
        of_sample=of_sample.astype(np.int64),
    )


def select_palette(
    bins: ColourBins, max_colors: int = DEFAULT_MAX_COLORS, min_area: float = DEFAULT_MIN_AREA
) -> Palette:
    """Pick at most ``max_colors`` colours that describe the binned samples.

    Raises:
        ValueError: if ``max_colors`` is out of range or nothing is visible.
    """
    if not 1 <= max_colors <= MAX_COLORS:
        raise ValueError(f"max_colors must be between 1 and {MAX_COLORS}, not {max_colors}")
    visible = bins.weight > 0
    lab, weight = bins.lab[visible], bins.weight[visible]
    if len(lab) == 0:
        raise ValueError("no visible colour: every sampled texel is transparent")
    min_mass = min_area * float(weight.sum())
    centres = _kmeans(lab, weight, min(len(lab), max(OVERSEGMENT_MIN, 3 * max_colors)))
    for _ in range(_REFINE_ROUNDS):
        # Merging moves centres; let k-means settle them, then check the rules again.
        centres, mass = _cluster_mass(lab, weight, centres)
        merged = _merge(centres, mass, max_colors, min_mass)
        if len(merged) == len(centres):
            break
        centres = _lloyd(lab, weight, merged, _KMEANS_ITERATIONS)
    else:
        centres, mass = _cluster_mass(lab, weight, centres)
        centres = _merge(centres, mass, max_colors, min_mass)
    return Palette.from_lab(_dominant_colours(lab, weight, centres))


def assign(lab: FloatArray, palette: Palette) -> NDArray[np.int64]:
    """Index of the nearest palette colour (CIEDE2000) for every colour in ``lab``."""
    distances = delta_e_2000(lab[:, None, :], palette.lab[None, :, :])
    return np.argmin(distances, axis=1).astype(np.int64)


def _squared_distance(lab: FloatArray, centre: FloatArray) -> FloatArray:
    difference: FloatArray = lab - centre
    return np.asarray(np.sum(difference * difference, axis=1), dtype=np.float64)


def _kmeans(lab: FloatArray, weight: FloatArray, k: int) -> FloatArray:
    """Weighted k-means with deterministic farthest-point seeding (heaviest bin first)."""
    centres: list[FloatArray] = [lab[int(np.argmax(weight))]]
    nearest = _squared_distance(lab, centres[0])
    while len(centres) < k:
        score: FloatArray = weight * nearest
        if float(score.max()) <= 0:
            break
        pick: FloatArray = lab[int(np.argmax(score))]
        centres.append(pick)
        nearest = np.minimum(nearest, _squared_distance(lab, pick))
    return _lloyd(lab, weight, np.array(centres), _KMEANS_ITERATIONS)


def _lloyd(lab: FloatArray, weight: FloatArray, centres: FloatArray, rounds: int) -> FloatArray:
    labels = _nearest(lab, centres)
    for _ in range(rounds):
        centres, _mass = _cluster_mass(lab, weight, centres, labels)
        new_labels = _nearest(lab, centres)
        if np.array_equal(new_labels, labels):
            break
        labels = new_labels
    return centres


def _nearest(lab: FloatArray, centres: FloatArray) -> NDArray[np.int64]:
    distances = np.sum((lab[:, None, :] - centres[None, :, :]) ** 2, axis=2)
    return np.argmin(distances, axis=1).astype(np.int64)


def _cluster_mass(
    lab: FloatArray,
    weight: FloatArray,
    centres: FloatArray,
    labels: NDArray[np.int64] | None = None,
) -> tuple[FloatArray, FloatArray]:
    """Weighted means and masses of the clusters; empty clusters are dropped."""
    if labels is None:
        labels = _nearest(lab, centres)
    k = len(centres)
    mass = np.bincount(labels, weight, k).astype(np.float64)
    sums = np.stack([np.bincount(labels, weight * lab[:, c], k) for c in range(3)], axis=1)
    keep = mass > 0
    return sums[keep] / mass[keep, None], mass[keep]


def _dominant_colours(lab: FloatArray, weight: FloatArray, centres: FloatArray) -> FloatArray:
    """The colour each cluster mostly is, rather than the average of what it absorbed.

    When red and brown have to share a filament, the mean of the two is a colour that
    appears nowhere on the model; the mean of the bins near the cluster's heaviest bin
    is the one that covers most of that cluster's area.
    """
    labels = _nearest(lab, centres)
    result = np.copy(centres)
    for cluster in range(len(centres)):
        members = np.flatnonzero(labels == cluster)
        if len(members) == 0:
            continue
        mode = lab[members[int(np.argmax(weight[members]))]]
        near = members[delta_e_2000(lab[members], mode) < MERGE_DELTA_E]
        result[cluster] = np.average(lab[near], axis=0, weights=weight[near])
    return result


def _merge(centres: FloatArray, mass: FloatArray, max_colors: int, min_mass: float) -> FloatArray:
    """Merge small clusters away, then the closest pairs, as the module docstring says."""
    centres, mass = np.copy(centres), np.copy(mass)
    while len(centres) > 1:
        distances = delta_e_2000(centres[:, None, :], centres[None, :, :])
        np.fill_diagonal(distances, np.inf)
        smallest = int(np.argmin(mass))
        if mass[smallest] < min_mass:
            source, target = smallest, int(np.argmin(distances[smallest]))
        elif len(centres) > max_colors or float(distances.min()) < MERGE_DELTA_E:
            source, target = np.unravel_index(int(np.argmin(distances)), distances.shape)
            source, target = int(source), int(target)
        else:
            break
        total = mass[source] + mass[target]
        centres[target] = (centres[source] * mass[source] + centres[target] * mass[target]) / total
        mass[target] = total
        centres, mass = np.delete(centres, source, axis=0), np.delete(mass, source)
    return centres
