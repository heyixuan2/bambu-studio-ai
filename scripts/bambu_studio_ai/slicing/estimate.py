"""Read Bambu Studio's print-time and filament estimates from a finished slice.

The command line writes them to ``result.json``. If that file is missing, the same
numbers are in the header of each plate's G-code inside the sliced 3MF.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*([dhms])")
_SECONDS = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0}
_TOTAL_TIME = re.compile(r"total estimated time:\s*([^;\n]+)")
_WEIGHTS = re.compile(r"^; total filament weight \[g\]\s*:\s*(.+)$")
_FILAMENT_IDS = re.compile(r"^; filament_ids = (.*)$")
_PLATE_GCODE = re.compile(r"^Metadata/plate_\d+\.gcode$")
_HEADER_END = "; CONFIG_BLOCK_END"


class EstimateError(ValueError):
    """The slice produced no readable estimate."""


@dataclass(frozen=True)
class FilamentUse:
    """How much of one project filament the print uses."""

    slot: int
    """The filament's number in the project (1 = first filament)."""
    filament_id: str
    """Bambu's filament id, e.g. ``"GFA00"`` for Bambu PLA Basic; empty when unknown."""
    grams: float


@dataclass(frozen=True)
class Estimate:
    """Print time and filament use, summed over the sliced plates."""

    print_time_s: float
    """What the printer will show: includes Bambu's start sequence (heating, bed
    levelling, vibration compensation, purge), several minutes on most machines."""
    filaments: tuple[FilamentUse, ...]
    plates: int
    source: str
    """``"result.json"`` or ``"gcode"`` (the fallback)."""
    warnings: tuple[str, ...] = ()

    @property
    def filament_g(self) -> float:
        """Total filament weight in grams."""
        return sum(use.grams for use in self.filaments)


def parse_duration(text: str) -> float:
    """Seconds in a Bambu duration such as ``"1d 2h 14m 58s"``.

    Raises:
        EstimateError: the text holds no duration.
    """
    parts = _DURATION_PART.findall(text)
    if not parts:
        raise EstimateError(f"not a duration: {text!r}")
    return sum(float(value) * _SECONDS[unit] for value, unit in parts)


def parse_result_json(document: Mapping[str, object]) -> Estimate:
    """Build the estimate from the command line's ``result.json``.

    Uses ``total_predication``, the time including the start sequence; Bambu Studio
    shows the same number as "total estimated time" in the G-code header.

    Raises:
        EstimateError: the document has no sliced plates or no time estimate.
    """
    plates = [_as_dict(plate) for plate in _as_list(document.get("sliced_plates"))]
    if not plates:
        raise EstimateError("result.json lists no sliced plates")
    total = 0.0
    grams: dict[int, float] = {}
    ids: dict[int, str] = {}
    warnings: list[str] = []
    for plate in plates:
        seconds = plate.get("total_predication")
        if not isinstance(seconds, (int, float)):
            raise EstimateError("result.json has no total_predication for a plate")
        total += float(seconds)
        for entry in _as_list(plate.get("filaments")):
            item = _as_dict(entry)
            slot, used = item.get("id"), item.get("total_used_g")
            if isinstance(slot, int) and isinstance(used, (int, float)):
                grams[slot] = grams.get(slot, 0.0) + float(used)
                filament_id = item.get("filament_id")
                ids[slot] = filament_id if isinstance(filament_id, str) else ""
        message = plate.get("warning_message")
        if isinstance(message, str) and message.strip():
            warnings.append(message.strip())
    return Estimate(
        print_time_s=total,
        filaments=_uses(grams, ids),
        plates=len(plates),
        source="result.json",
        warnings=tuple(warnings),
    )


def parse_gcode_header(lines: Iterable[str]) -> Estimate:
    """Build the estimate of one plate from the start of its G-code.

    Reads up to the end of the config block, where Bambu Studio writes
    ``; total estimated time: …``, ``; total filament weight [g] : …`` and
    ``; filament_ids = …``.

    Raises:
        EstimateError: the header has no total estimated time.
    """
    seconds: float | None = None
    weights: list[float] = []
    filament_ids: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line.startswith(_HEADER_END):
            break
        if (time_match := _TOTAL_TIME.search(line)) and line.startswith(";"):
            seconds = parse_duration(time_match.group(1))
        elif weight_match := _WEIGHTS.match(line):
            weights = [float(w) for w in re.split(r"[,;]", weight_match.group(1)) if w.strip()]
        elif id_match := _FILAMENT_IDS.match(line):
            filament_ids = [i.strip() for i in re.split(r"[,;]", id_match.group(1))]
    if seconds is None:
        raise EstimateError("the G-code header has no total estimated time")
    grams = dict(enumerate(weights, start=1))
    ids = {slot: filament_ids[slot - 1] for slot in grams if slot <= len(filament_ids)}
    return Estimate(print_time_s=seconds, filaments=_uses(grams, ids), plates=1, source="gcode")


def estimate_from_3mf(path: Path) -> Estimate:
    """Sum the G-code header estimates of every plate in a sliced 3MF.

    Raises:
        EstimateError: the 3MF holds no plate G-code, or a header has no estimate.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            members = sorted(n for n in archive.namelist() if _PLATE_GCODE.match(n))
            if not members:
                raise EstimateError(f"{path.name} contains no plate G-code")
            estimates: list[Estimate] = []
            for member in members:
                with archive.open(member) as raw:
                    stream = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                    estimates.append(parse_gcode_header(stream))
    except (OSError, zipfile.BadZipFile) as exc:
        raise EstimateError(f"cannot read {path}: {exc}") from exc
    return _combine(estimates)


def _combine(estimates: Sequence[Estimate]) -> Estimate:
    grams: dict[int, float] = {}
    ids: dict[int, str] = {}
    for estimate in estimates:
        for use in estimate.filaments:
            grams[use.slot] = grams.get(use.slot, 0.0) + use.grams
            ids[use.slot] = ids.get(use.slot) or use.filament_id
    return Estimate(
        print_time_s=sum(e.print_time_s for e in estimates),
        filaments=_uses(grams, ids),
        plates=len(estimates),
        source="gcode",
    )


def _uses(grams: Mapping[int, float], ids: Mapping[int, str]) -> tuple[FilamentUse, ...]:
    return tuple(
        FilamentUse(slot=slot, filament_id=ids.get(slot, ""), grams=grams[slot])
        for slot in sorted(grams)
    )


def _as_list(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _as_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}
