"""Turn the printer's raw MQTT ``print`` report into typed, JSON-ready values.

Field names follow the report format documented by the OpenBambuAPI project
(https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md). Models differ in which
fields they send, so every field here is optional and unknown values become ``None``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, cast

#: ``spd_lvl`` values, named as in Bambu Studio.
SPEED_LEVELS = {1: "silent", 2: "standard", 3: "sport", 4: "ludicrous"}

#: ``gcode_state`` values that mean a job is loaded on the printer.
ACTIVE_STATES = frozenset({"PREPARE", "SLICING", "RUNNING", "PAUSE"})

_EXTERNAL_SPOOL_ID = 254
_FIRST_AMS_HT_ID = 128  # AMS HT units report ids from 128 and hold a single spool
_SLOTS_PER_AMS = 4
_UNKNOWN_REMAINING = 100  # values above 100 % mean 'unknown'


@dataclass(frozen=True)
class Tray:
    """A loaded filament slot: an AMS tray or the external spool holder."""

    unit: int | None
    """AMS unit id, or ``None`` for the external spool."""
    slot: int
    material: str
    """Filament type as reported, e.g. ``"PLA"`` or ``"PETG-CF"``."""
    name: str
    """Product name from the RFID tag, e.g. ``"PLA Basic"``; empty for untagged spools."""
    color: str
    """``"#RRGGBB"``, or empty when unknown."""
    remaining_pct: int | None
    active: bool
    """Whether the printer is currently feeding from this slot."""


@dataclass(frozen=True)
class PrinterStatus:
    """A snapshot of what the printer is doing."""

    state: str
    """``gcode_state``: IDLE, PREPARE, RUNNING, PAUSE, FINISH, FAILED or UNKNOWN."""
    active: bool
    progress_pct: int | None
    remaining_min: int | None
    layer: int | None
    total_layers: int | None
    file: str
    nozzle_temp: float | None
    nozzle_target: float | None
    bed_temp: float | None
    bed_target: float | None
    chamber_temp: float | None
    speed: str | None
    light: str | None
    print_error: str | None
    """Printer error code as 8 hex digits, or ``None`` when there is no error."""
    hms: tuple[str, ...]
    """Active health-management (HMS) codes, formatted like ``0300_0100_0001_0007``."""
    trays: tuple[Tray, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


def parse_status(report: Mapping[str, Any]) -> PrinterStatus:
    """Build a status from the ``print`` section of a printer report."""
    state = str(report.get("gcode_state") or "UNKNOWN").upper()
    return PrinterStatus(
        state=state,
        active=state in ACTIVE_STATES,
        progress_pct=_count(report.get("mc_percent")),
        remaining_min=_count(report.get("mc_remaining_time")),
        layer=_count(report.get("layer_num")),
        total_layers=_count(report.get("total_layer_num")),
        file=str(report.get("subtask_name") or report.get("gcode_file") or ""),
        nozzle_temp=_float(report.get("nozzle_temper")),
        nozzle_target=_float(report.get("nozzle_target_temper")),
        bed_temp=_float(report.get("bed_temper")),
        bed_target=_float(report.get("bed_target_temper")),
        chamber_temp=_float(report.get("chamber_temper")),
        speed=SPEED_LEVELS.get(_count(report.get("spd_lvl")) or 0),
        light=_chamber_light(report.get("lights_report")),
        print_error=_error_code(report.get("print_error")),
        hms=tuple(code for code in map(_hms_code, _mappings(report.get("hms"))) if code),
        trays=tuple(parse_trays(report)),
    )


def parse_trays(report: Mapping[str, Any]) -> list[Tray]:
    """List the loaded AMS trays and the external spool, in slot order."""
    ams = _mapping(report.get("ams"))
    feeding = _count(ams.get("tray_now"))
    trays: list[Tray] = []
    for unit in _mappings(ams.get("ams")):
        unit_id = _count(unit.get("id"))
        if unit_id is None:
            continue
        for raw in _mappings(unit.get("tray")):
            slot = _count(raw.get("id"))
            if slot is None or not raw.get("tray_type"):
                continue  # empty slot
            feed_id = unit_id if unit_id >= _FIRST_AMS_HT_ID else unit_id * _SLOTS_PER_AMS + slot
            trays.append(_tray(raw, unit_id, slot, active=feeding == feed_id))
    external = _mapping(report.get("vt_tray"))
    if external.get("tray_type"):
        trays.append(_tray(external, None, 0, active=feeding == _EXTERNAL_SPOOL_ID))
    return trays


def _tray(raw: Mapping[str, Any], unit: int | None, slot: int, *, active: bool) -> Tray:
    remaining = _count(raw.get("remain"))
    return Tray(
        unit=unit,
        slot=slot,
        material=str(raw.get("tray_type") or ""),
        name=str(raw.get("tray_sub_brands") or ""),
        color=_hex_color(raw.get("tray_color")),
        remaining_pct=remaining
        if remaining is not None and remaining <= _UNKNOWN_REMAINING
        else None,
        active=active,
    )


def _count(value: object) -> int | None:
    """Parse a non-negative integer; the printer uses -1 and "" for 'unknown'."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = int(value)
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        number = int(value.strip())
    else:
        return None
    return number if number >= 0 else None


def _float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return round(float(value), 1)
    if isinstance(value, str):
        try:
            return round(float(value), 1)
        except ValueError:
            return None
    return None


def _hex_color(value: object) -> str:
    """``"FF6A13FF"`` (RRGGBBAA) -> ``"#FF6A13"``."""
    text = str(value or "")
    if len(text) in (6, 8) and all(c in "0123456789abcdefABCDEF" for c in text):
        return "#" + text[:6].upper()
    return ""


def _chamber_light(value: object) -> str | None:
    for light in _mappings(value):
        if light.get("node") == "chamber_light":
            return str(light.get("mode") or "") or None
    return None


def _error_code(value: object) -> str | None:
    code = _count(value)
    return f"{code:08X}" if code else None


def _hms_code(entry: Mapping[str, Any]) -> str:
    attr, code = _count(entry.get("attr")), _count(entry.get("code"))
    if attr is None or code is None:
        return ""
    return f"{attr >> 16:04X}_{attr & 0xFFFF:04X}_{code >> 16:04X}_{code & 0xFFFF:04X}"


def _mapping(value: object) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", value) if isinstance(value, Mapping) else {}


def _mappings(value: object) -> list[Mapping[str, Any]]:
    items = cast("list[object]", value) if isinstance(value, list) else []
    return [mapping for mapping in map(_mapping, items) if mapping]
