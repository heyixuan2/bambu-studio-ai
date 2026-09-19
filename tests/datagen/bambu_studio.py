"""Read printer, filament and colour data from an installed Bambu Studio.

Bambu Studio keeps two kinds of data we use:

- ``Resources/profiles/BBL/`` — slicer profiles. Machine profiles give the printable
  area and height (per extruder on two-nozzle printers); filament profiles give
  temperatures, the nozzle hardness a filament needs and which printers it has a
  profile for; ``filament/filaments_color_codes.json`` is Bambu's colour table.
- ``Resources/printers/`` — device capabilities: rated nozzle, bed and chamber
  temperatures, whether the printer is enclosed, and the AMS/nozzle blacklist.

Profiles inherit from each other (``"inherits"``); :func:`flatten` resolves the chain.
"""

from __future__ import annotations

import functools
import json
import os
import plistlib
import sys
from pathlib import Path

_DEFAULT_RESOURCES = {
    "darwin": ["/Applications/BambuStudio.app/Contents/Resources"],
    "win32": [os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"), "Bambu Studio", "resources")],
}


def resources_dir():
    """Bambu Studio's ``Resources`` directory, or None when Bambu Studio isn't installed.

    ``BAMBU_STUDIO_RESOURCES`` overrides the platform default (use it on Linux, where the
    AppImage and Flatpak keep their resources in a mount or sandbox).
    """
    candidates = [os.environ.get("BAMBU_STUDIO_RESOURCES", "")] + _DEFAULT_RESOURCES.get(sys.platform, [])
    for candidate in candidates:
        if candidate and (Path(candidate) / "profiles" / "BBL" / "machine").is_dir():
            return Path(candidate)
    return None


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def versions(res):
    """``{"app": "02.07.01.62" or None, "profiles": "02.07.00.08"}``."""
    app = None
    plist = res.parent / "Info.plist"
    if plist.is_file():
        with open(plist, "rb") as f:
            app = plistlib.load(f).get("CFBundleShortVersionString")
    return {"app": app, "profiles": _read(res / "profiles" / "BBL.json")["version"]}


@functools.lru_cache(maxsize=None)
def _profiles_by_name(folder):
    """Profile ``name`` → file. Names can differ from file names (``/`` becomes ``-``)."""
    index = {}
    for path in folder.rglob("*.json"):  # filament/P1P/ holds P1P-only profiles
        name = _read(path).get("name")
        if isinstance(name, str):
            index[name] = path
    return index


def flatten(folder, name):
    """A profile with its ``inherits`` chain merged in (child values win)."""
    data = _read(_profiles_by_name(folder).get(name) or folder / f"{name}.json")
    parent = data.get("inherits")
    if not parent:
        return data
    merged = flatten(folder, parent)
    merged.update(data)
    return merged


# ─── Machines ─────────────────────────────────────────────────────────


def _box(points):
    """(x0, x1, width, depth) of a printable-area polygon given as ``["0x0", "350x0", ...]``."""
    xs, ys = [], []
    for point in points:
        x, y = point.strip().split("x")
        xs.append(float(x))
        ys.append(float(y))
    return min(xs), max(xs), max(xs) - min(xs), max(ys) - min(ys)


def _num(value):
    number = float(value)
    return int(number) if number.is_integer() else number


def machine_volumes(res, machine_name):
    """Printable volumes of a machine family from its 0.4 mm nozzle profile.

    Returns ``{"plate": [W, D, H], "extruders": [[W, D, H], ...], "dual_nozzle": [W, D, H] or None}``.
    ``extruders`` follows Bambu Studio's extruder order; ``dual_nozzle`` is the region every
    extruder can reach (the limit for one object printed with both nozzles).
    """
    profile = flatten(res / "profiles" / "BBL" / "machine", f"{machine_name} 0.4 nozzle")
    _, _, width, depth = _box(profile["printable_area"])
    plate = [_num(width), _num(depth), _num(profile["printable_height"])]
    areas = profile.get("extruder_printable_area") or []
    heights = profile.get("extruder_printable_height") or []
    extruders, spans = [], []
    for area, height in zip(areas, heights):
        x0, x1, w, d = _box(area.split(","))
        extruders.append([_num(w), _num(d), _num(height)])
        spans.append((x0, x1, d, float(height)))
    dual = None
    if len(spans) > 1:
        x0 = max(s[0] for s in spans)
        x1 = min(s[1] for s in spans)
        dual = [_num(x1 - x0), _num(min(s[2] for s in spans)), _num(min(s[3] for s in spans))]
    return {
        "plate": plate,
        "extruders": extruders or [plate],
        "dual_nozzle": dual,
        "extruder_types": profile.get("extruder_type", []),
        "max_hotends": [int(n) for n in profile.get("extruder_max_nozzle_count", ["1"])],
        "nozzle_type": profile.get("nozzle_type", [""])[0],
    }


def capabilities(res):
    """Device capabilities keyed by Bambu Studio display name (``"Bambu Lab H2D"``)."""
    caps = {}
    for path in sorted((res / "printers").glob("*.json")):
        data = _read(path)
        base = data.get("00.00.00.00")
        if not isinstance(base, dict):
            continue  # filaments_blacklist.json and similar
        prnt = base.get("print", {})
        bed = prnt.get("bed_temp_range", [0, prnt.get("bed_temperature_limit")])[1]
        chamber = prnt.get("support_chamber_temp_edit_range", [0, None])[1] if prnt.get("support_chamber_temp_edit") else None
        entry = caps.setdefault(base["display_name"], {"model_ids": []})
        entry["model_ids"].append(base["model_id"])
        entry.update(
            max_nozzle_c=prnt.get("nozzle_temp_range", [0, None])[1],
            max_bed_c=bed,
            chamber_max_c=chamber,
            enclosed=bool(base.get("printer_is_enclosed", False)),
        )
    return caps


def blacklist(res):
    """Bambu Studio's filament rules (``prohibition``/``warning`` per type, slot and printer)."""
    return _read(res / "printers" / "filaments_blacklist.json")["blacklist"]


# ─── Filaments ────────────────────────────────────────────────────────


def filament_variants(res, line):
    """Every system profile of a filament line (``"Bambu PLA Basic"``), flattened, @base first."""
    folder = res / "profiles" / "BBL" / "filament"
    names = sorted(n for n in _profiles_by_name(folder) if n.startswith(f"{line} @"))
    names.sort(key=lambda n: not n.endswith("@base"))
    return [flatten(folder, n) for n in names]


def compatible_machines(variants):
    """Machine families (``"Bambu Lab X1 Carbon"``) that have a profile for this filament."""
    families = set()
    for variant in variants:
        for machine in variant.get("compatible_printers", []):
            families.add(machine.rsplit(" ", 2)[0] if machine.endswith(" nozzle") else machine)
    return families


def color_table(res):
    """Rows of Bambu Studio's ``filaments_color_codes.json``."""
    return _read(res / "profiles" / "BBL" / "filament" / "filaments_color_codes.json")["data"]
