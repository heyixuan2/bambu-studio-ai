"""Bambu Lab printers and filament materials: volumes, temperature limits, compatibility.

The data lives in ``assets/printers.json`` and ``assets/materials.json`` (sourced from
Bambu Studio's own profiles; see the ``about`` field of each file). This module loads it
once, on first use, into typed records and answers the questions the scripts ask:
which printer is "x1 carbon", how big a part fits, and whether a material suits a printer.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from bambu_studio_ai import _json

Volume = tuple[float, float, float]
"""Width (X), depth (Y) and height (Z) in millimetres."""

#: Clearance kept free on each side of the plate by :func:`usable_volume`: Bambu Studio's
#: default brim width, so a part that fits still fits once a brim is added.
DEFAULT_MARGIN_MM = 5.0

_CHAMBER = re.compile(r"^(none|passive|heated (\d+) °C)$")
_HARDENED = "hardened_steel"


class UnknownHardwareError(LookupError):
    """No printer or material by that name."""


class UnsupportedMaterialError(UnknownHardwareError):
    """A material that no Bambu Lab printer can print, such as PEEK."""


@dataclass(frozen=True)
class Extruder:
    """One nozzle of a multi-nozzle printer."""

    name: str
    """``left``/``right`` (H2 series) or ``main``/``auxiliary`` (X2D)."""
    drive: str
    """``direct drive`` or ``bowden``."""
    max_hotends: int
    """Hotends this nozzle can switch between (the H2C's Vortek changer holds 6)."""
    volume_mm: Volume


@dataclass(frozen=True)
class AmsSupport:
    """Which AMS units a printer takes, and how many filament slots they add up to."""

    types: tuple[str, ...]
    max_slots: int
    """AMS slots only; the external spool holder is one more feed per nozzle."""
    notes: str


@dataclass(frozen=True)
class Printer:
    """A printer model. Volumes are Bambu Studio's printable volumes, without margin."""

    key: str
    """The name used in config and on the command line, e.g. ``"X1C"``."""
    name: str
    machine: str
    """Bambu Studio's machine name, e.g. ``"Bambu Lab X1 Carbon"``."""
    model_ids: tuple[str, ...]
    """Codes the printer reports about itself, e.g. ``"BL-P001"``."""
    aliases: tuple[str, ...]
    build_volume_mm: Volume
    """The whole plate. On two-nozzle printers only both nozzles together reach all of it."""
    spec_volume_mm: Volume | None
    """The manufacturer's headline figure, where it differs from what Bambu Studio accepts."""
    dual_nozzle_volume_mm: Volume | None
    """The region every nozzle reaches: the limit for one object printed with both."""
    extruders: tuple[Extruder, ...]
    max_nozzle_c: int
    max_bed_c: int
    chamber: str
    """``"none"``, ``"passive"`` (enclosed, not heated) or ``"heated <N> °C"``."""
    enclosed: bool
    nozzle: str
    """Nozzle fitted at the factory: ``hardened_steel`` or ``stainless_steel``."""
    ams: AmsSupport
    status: str
    """``"current"`` or ``"discontinued <YYYY-MM-DD>"``."""
    sources: tuple[str, ...]
    retrieved: str
    notes: str

    @property
    def chamber_max_c(self) -> int | None:
        """Highest chamber temperature the printer can hold, or None without chamber heating."""
        match = _CHAMBER.match(self.chamber)
        return int(match.group(2)) if match and match.group(2) else None

    @property
    def discontinued(self) -> bool:
        """Whether Bambu Lab has stopped making this model."""
        return self.status.startswith("discontinued")

    @property
    def volumes(self) -> dict[str, Volume]:
        """Every printable region by name: ``plate``, each extruder, and ``dual_nozzle``."""
        regions = {"plate": self.build_volume_mm}
        regions.update((e.name, e.volume_mm) for e in self.extruders)
        if self.dual_nozzle_volume_mm is not None:
            regions["dual_nozzle"] = self.dual_nozzle_volume_mm
        return regions

    @property
    def fit_region(self) -> str:
        """The region a part fits whichever nozzles print it (the most restrictive one)."""
        return "plate" if self.dual_nozzle_volume_mm is None else "dual_nozzle"


@dataclass(frozen=True)
class Material:
    """A filament material, with the values Bambu Studio's profiles use for it."""

    key: str
    filament_type: str
    """Bambu Studio's ``filament_type``, e.g. ``"PLA"`` or ``"TPU-AMS"``."""
    studio_profiles: tuple[str, ...]
    aliases: tuple[str, ...]
    nozzle_c: tuple[int, int]
    bed_c: int
    """On the Textured PEI plate."""
    chamber_c: int | None
    needs_enclosure: bool
    needs_heated_chamber: bool
    abrasive: bool
    """Needs a hardened-steel nozzle."""
    ams_compatible: bool
    soluble: bool
    support: bool
    min_wall_mm: float
    """Thinnest wall that still gets two perimeters with a 0.4 mm nozzle."""
    printers: tuple[str, ...]
    """Printer keys Bambu Studio ships a profile for this material for."""
    notes: str


# ─── Lookup ───────────────────────────────────────────────────────────


def normalize_name(name: str) -> str:
    """Lookup form of a printer or material name: ``"Bambu Lab X1-Carbon"`` → ``"x1carbon"``."""
    lowered = re.sub(r"^bambu\s*(lab)?\s*", "", name.strip().lower())
    return re.sub(r"[^a-z0-9+]", "", lowered)


def printers() -> Mapping[str, Printer]:
    """All known printers by key, in the order of ``assets/printers.json``."""
    return _printer_table()[0]


def printer(name: str) -> Printer:
    """Find a printer by key, name, alias or model id, ignoring case, spaces and hyphens.

    Raises:
        UnknownHardwareError: nothing matches.
    """
    table, index = _printer_table()
    key = index.get(normalize_name(name))
    if key is None:
        raise UnknownHardwareError(f"Unknown printer {name!r}. Known printers: {', '.join(table)}")
    return table[key]


def materials() -> Mapping[str, Material]:
    """All known materials by key."""
    return _material_table()[0]


def unsupported_materials() -> Mapping[str, str]:
    """Materials no Bambu Lab printer can print, with the reason."""
    return _material_table()[2]


def material(name: str) -> Material:
    """Find a material by key or alias, ignoring case, spaces and hyphens.

    Raises:
        UnsupportedMaterialError: a known material that no Bambu printer can print.
        UnknownHardwareError: nothing matches.
    """
    table, index, unsupported = _material_table()
    key = index.get(normalize_name(name))
    if key is not None:
        return table[key]
    for bad, reason in unsupported.items():
        if normalize_name(bad) == normalize_name(name):
            raise UnsupportedMaterialError(
                f"{bad} can't be printed on a Bambu Lab printer: {reason}"
            )
    raise UnknownHardwareError(f"Unknown material {name!r}. Known materials: {', '.join(table)}")


# ─── Questions ────────────────────────────────────────────────────────


def usable_volume(
    printer: Printer, margin_mm: float = DEFAULT_MARGIN_MM, *, region: str | None = None
) -> Volume:
    """The box a part must fit in, keeping ``margin_mm`` free on every side of the plate.

    The margin comes off both sides in X and Y (room for a brim and the plate edge) but
    not off the height: nothing is added above a part, and Bambu Studio's printable
    height is already the usable height.

    Args:
        printer: The printer.
        margin_mm: Clearance per side, in millimetres.
        region: A key of :attr:`Printer.volumes`. Defaults to :attr:`Printer.fit_region`,
            which fits whichever nozzles print the part.

    Raises:
        ValueError: unknown region, or a margin that leaves no room.
    """
    regions = printer.volumes
    chosen = region or printer.fit_region
    if chosen not in regions:
        raise ValueError(
            f"The {printer.name} has no {chosen!r} region; use one of {', '.join(regions)}"
        )
    if margin_mm < 0:
        raise ValueError("margin_mm must not be negative")
    width, depth, height = regions[chosen]
    usable = (width - 2 * margin_mm, depth - 2 * margin_mm, height)
    if min(usable) <= 0:
        raise ValueError(f"A {margin_mm} mm margin leaves no room on the {printer.name}")
    return usable


def material_issues(printer: Printer, material: Material) -> list[str]:
    """Reasons ``material`` is a poor or impossible choice on ``printer``; empty if it suits."""
    issues: list[str] = []
    low, high = material.nozzle_c
    if low > printer.max_nozzle_c:
        issues.append(
            f"{material.key} prints at {low}-{high} °C; the {printer.name} nozzle reaches "
            f"{printer.max_nozzle_c} °C."
        )
    if material.needs_heated_chamber and printer.chamber_max_c is None:
        issues.append(f"{material.key} needs a heated chamber; the {printer.name} has none.")
    elif material.needs_enclosure and not printer.enclosed:
        issues.append(
            f"{material.key} needs an enclosed printer; the {printer.name} is open-frame."
        )
    if material.abrasive and printer.nozzle != _HARDENED:
        issues.append(
            f"{material.key} is abrasive: fit a hardened-steel nozzle (the {printer.name} ships "
            "with stainless steel)."
        )
    if printer.key not in material.printers:
        issues.append(f"Bambu Studio has no {material.key} profile for the {printer.name}.")
    return issues


# ─── Loading ──────────────────────────────────────────────────────────


def _add_names(index: dict[str, str], key: str, names: tuple[str, ...], where: str) -> None:
    for name in names:
        normalized = normalize_name(name)
        if index.setdefault(normalized, key) != key:
            raise _json.DataFileError(f"{where}: {name!r} also names {index[normalized]!r}")


@functools.cache
def _printer_table() -> tuple[Mapping[str, Printer], dict[str, str]]:
    data = _json.load_asset("printers.json")
    table: dict[str, Printer] = {}
    index: dict[str, str] = {}
    for key, raw in _json.obj(_json.field(data, "printers", "printers.json"), "printers").items():
        entry = _parse_printer(key, _json.obj(raw, key))
        table[key] = entry
        names = (key, entry.name, entry.machine, *entry.aliases, *entry.model_ids)
        _add_names(index, key, names, f"printers.json {key}")
    return MappingProxyType(table), index


def _volume(data: _json.JsonObject, key: str, where: str) -> Volume:
    width, depth, height = _json.numbers(data, key, where, 3)
    return (width, depth, height)


def _optional_volume(data: _json.JsonObject, key: str, where: str) -> Volume | None:
    return None if data.get(key) is None else _volume(data, key, where)


def _parse_printer(key: str, data: _json.JsonObject) -> Printer:
    chamber = _json.text(data, "chamber", key)
    if not _CHAMBER.match(chamber):
        raise _json.DataFileError(
            f"{key}.chamber: {chamber!r} is not none, passive or 'heated <N> °C'"
        )
    ams = _json.obj(_json.field(data, "ams", key), f"{key}.ams")
    extruders = tuple(
        Extruder(
            name=_json.text(e, "name", f"{key}.extruders"),
            drive=_json.text(e, "drive", f"{key}.extruders"),
            max_hotends=_json.integer(e, "max_hotends", f"{key}.extruders"),
            volume_mm=_volume(e, "volume_mm", f"{key}.extruders"),
        )
        for e in (
            _json.obj(x, f"{key}.extruders") for x in _json.items(data.get("extruders", []), key)
        )
    )
    return Printer(
        key=key,
        name=_json.text(data, "name", key),
        machine=_json.text(data, "machine", key),
        model_ids=_json.texts(data, "model_ids", key),
        aliases=_json.texts(data, "aliases", key),
        build_volume_mm=_volume(data, "build_volume_mm", key),
        spec_volume_mm=_optional_volume(data, "spec_volume_mm", key),
        dual_nozzle_volume_mm=_optional_volume(data, "dual_nozzle_volume_mm", key),
        extruders=extruders,
        max_nozzle_c=_json.integer(data, "max_nozzle_c", key),
        max_bed_c=_json.integer(data, "max_bed_c", key),
        chamber=chamber,
        enclosed=_json.flag(data, "enclosed", key),
        nozzle=_json.text(data, "nozzle", key),
        ams=AmsSupport(
            types=_json.texts(ams, "types", f"{key}.ams"),
            max_slots=_json.integer(ams, "max_slots", f"{key}.ams"),
            notes=_json.text(ams, "notes", f"{key}.ams"),
        ),
        status=_json.text(data, "status", key),
        sources=_json.texts(data, "sources", key),
        retrieved=_json.text(data, "retrieved", key),
        notes=_json.text(data, "notes", key),
    )


@functools.cache
def _material_table() -> tuple[Mapping[str, Material], dict[str, str], Mapping[str, str]]:
    data = _json.load_asset("materials.json")
    table: dict[str, Material] = {}
    index: dict[str, str] = {}
    for key, raw in _json.obj(
        _json.field(data, "materials", "materials.json"), "materials"
    ).items():
        entry = _parse_material(key, _json.obj(raw, key))
        table[key] = entry
        _add_names(index, key, (key, *entry.aliases), f"materials.json {key}")
    unsupported = _json.obj(data.get("unsupported", {}), "unsupported")
    reasons = {name: _json.text(unsupported, name, "unsupported") for name in unsupported}
    return MappingProxyType(table), index, MappingProxyType(reasons)


def _parse_material(key: str, data: _json.JsonObject) -> Material:
    low, high = _json.numbers(data, "nozzle_c", key, 2)
    return Material(
        key=key,
        filament_type=_json.text(data, "filament_type", key),
        studio_profiles=_json.texts(data, "studio_profiles", key),
        aliases=_json.texts(data, "aliases", key),
        nozzle_c=(int(low), int(high)),
        bed_c=_json.integer(data, "bed_c", key),
        chamber_c=_json.optional_integer(data, "chamber_c", key),
        needs_enclosure=_json.flag(data, "needs_enclosure", key),
        needs_heated_chamber=_json.flag(data, "needs_heated_chamber", key),
        abrasive=_json.flag(data, "abrasive", key),
        ams_compatible=_json.flag(data, "ams_compatible", key),
        soluble=_json.flag(data, "soluble", key),
        support=_json.flag(data, "support", key),
        min_wall_mm=_json.number(_json.field(data, "min_wall_mm", key), f"{key}.min_wall_mm"),
        printers=_json.texts(data, "printers", key),
        notes=_json.text(data, "notes", key),
    )
