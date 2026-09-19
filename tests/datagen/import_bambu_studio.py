"""Regenerate ``assets/materials.json`` and ``assets/filaments.json`` from Bambu Studio.

    python3 tests/datagen/import_bambu_studio.py            # show what would change
    python3 tests/datagen/import_bambu_studio.py --write    # rewrite the two files

Needs Bambu Studio installed (set ``BAMBU_STUDIO_RESOURCES`` on Linux). The editorial part
of each material (which Bambu Studio lines it stands for, aliases, notes) lives in
``MATERIALS`` below; every number comes from Bambu Studio's profiles.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make `datagen` importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datagen import bambu_studio as bs

ROOT = Path(__file__).resolve().parents[2]
PRINTERS_JSON = ROOT / "assets" / "printers.json"
MATERIALS_JSON = ROOT / "assets" / "materials.json"
FILAMENTS_JSON = ROOT / "assets" / "filaments.json"

# Two perimeters at Bambu Studio's default 0.4 mm widths (outer 0.42 + inner 0.45 mm).
MIN_WALL_MM = 0.9
ABRASIVE_HRC = 40  # Bambu Studio's required_nozzle_HRC for fibre-filled filaments

# key -> Bambu Studio lines it stands for (first one supplies the numbers), aliases, notes.
MATERIALS = {
    "PLA": (["Bambu PLA Basic"], ["PLA Basic", "PLA Matte", "PLA+"], ""),
    "PLA-CF": (["Bambu PLA-CF"], [], ""),
    "PETG": (["Bambu PETG Basic", "Bambu PETG HF"], ["PETG Basic", "PETG HF"], ""),
    "PETG-CF": (["Bambu PETG-CF"], [], ""),
    "TPU 95A": (["Bambu TPU 95A HF", "Bambu TPU 95A"], ["TPU", "TPU 95A HF"],
                "Feed from the external spool: Bambu Studio blocks every filament of type TPU in the AMS "
                "(only 'TPU for AMS' is allowed)."),
    "TPU 90A": (["Bambu TPU 90A"], [], "External spool only (not AMS)."),
    "TPU 85A": (["Bambu TPU 85A"], [],
                "External spool only (not AMS). Bambu Studio refuses it with a 0.4 mm nozzle on the H2D and "
                "H2D Pro; use 0.6 mm or larger."),
    "TPU for AMS": (["Bambu TPU for AMS"], ["TPU-AMS"], "The one TPU that Bambu Studio allows in the AMS."),
    "ABS": (["Bambu ABS"], [], ""),
    "ASA": (["Bambu ASA"], [], ""),
    "PA": (["Generic PA"], ["Nylon"], "Bambu Lab sells no unfilled PA; values are Bambu Studio's Generic PA."),
    "PA-CF": (["Bambu PAHT-CF", "Bambu PA6-CF", "Bambu PA-CF"], ["PAHT-CF", "PA6-CF"], "Dry before use."),
    "PC": (["Bambu PC"], [], ""),
    "PVA": (["Bambu PVA"], [], "Water-soluble support. Dry before use; damp PVA jams the AMS."),
    "BVOH": (["Generic BVOH"], [],
             "Water-soluble support (Bambu Studio's Generic BVOH profile marks it not soluble; it is)."),
    "Support for PLA": (["Bambu Support For PLA", "Bambu Support W"], ["Support W"],
                        "Breakaway support interface for PLA."),
    "Support for PLA/PETG": (["Bambu Support For PLA/PETG"], [], "Breakaway support interface for PLA and PETG."),
    "Support for ABS": (["Bambu Support for ABS"], [], "Breakaway support interface for ABS."),
    "Support for PA/PET": (["Bambu Support For PA/PET", "Bambu Support G"], ["Support G"],
                           "Breakaway support interface for PA and PET."),
    "PPA-CF": (["Bambu PPA-CF"], [],
               "Bambu recommends a 0.6 mm hardened nozzle and a heated chamber; Bambu Studio also ships "
               "profiles for X1/P1 printers without chamber heating."),
    "PPS-CF": (["Bambu PPS-CF"], [], "Brittle: can snap in the bent PTFE tube above the H2S toolhead."),
}
SOLUBLE_OVERRIDES = {"BVOH": True}
UNSUPPORTED = {
    name: f"{name} needs a nozzle hotter than 350 °C and a chamber far above 65 °C; no Bambu Lab printer "
          "reaches either and Bambu Studio has no profile for it."
    for name in ("PEEK", "PEI", "PPSU")
}

# Colour-table product line -> surface finish. A new line in Bambu Studio fails loudly
# here so someone decides whether it may stand in for a plain opaque colour.
FINISHES = {
    "opaque": "Solid, glossy or satin colour.",
    "matte": "Solid colour, matte surface (includes carbon- and glass-fibre filaments).",
    "silk": "Metallic sheen; the colour shifts with the viewing angle.",
    "translucent": "Lets light through; the colour depends on wall thickness.",
    "glow": "Glows in the dark.",
    "sparkle": "Contains glitter.",
    "metal": "Metal-look pigment.",
    "marble": "Speckled stone look.",
    "wood": "Contains wood fibre.",
    "foam": "Foaming lightweight filament (Aero); prints with special settings.",
    "color-changing": "Changes colour under UV light.",
}
LINE_FINISH = {
    "PLA Basic": "opaque", "PLA Lite": "opaque", "PLA Pure": "opaque", "PLA Tough": "opaque",
    "PLA Tough+": "opaque", "PLA Matte": "matte", "PLA Silk": "silk", "PLA Silk+": "silk",
    "PLA Translucent": "translucent", "PLA Glow": "glow", "PLA Galaxy": "sparkle", "PLA Sparkle": "sparkle",
    "PLA Metal": "metal", "PLA Marble": "marble", "PLA Wood": "wood", "PLA Aero": "foam",
    "PLA Dynamic": "color-changing", "PLA-CF": "matte",
    "PETG Basic": "opaque", "PETG HF": "opaque", "PETG Translucent": "translucent", "PETG-CF": "matte",
    "ABS": "opaque", "ABS-GF": "matte", "ASA": "opaque", "ASA Aero": "foam", "ASA-CF": "matte",
    "PC": "opaque", "PC FR": "opaque", "PA6-CF": "matte", "PA6-GF": "matte", "PAHT-CF": "matte",
    "PET-CF": "matte", "PPA-CF": "matte", "PPS-CF": "matte",
    "TPU 85A": "opaque", "TPU 90A": "opaque", "TPU 95A": "opaque", "TPU 95A HF": "opaque",
    "TPU for AMS": "opaque",
    "PVA": "translucent", "Support for ABS": "opaque", "Support for PA/PET": "opaque",
    "Support for PLA": "opaque", "Support for PLA/PETG": "opaque",
}
PATTERNS = {"单色": "solid", "渐变色": "gradient", "多拼色": "multicolor"}


def _first(profile, key):
    value = profile[key]
    return value[0] if isinstance(value, list) else value


def _printer_keys(res, lines):
    """Model keys of the printers that have a Bambu Studio profile for any of these lines."""
    families = set()
    for line in lines:
        families |= bs.compatible_machines(bs.filament_variants(res, line))
    printers = json.loads(PRINTERS_JSON.read_text(encoding="utf-8"))["printers"]
    return [key for key, p in printers.items() if p["machine"] in families]


def _ams_prohibited(rules, profile):
    kind, vendor = _first(profile, "filament_type"), _first(profile, "filament_vendor")
    for rule in rules:
        if rule.get("slot") != "ams" or rule.get("action") != "prohibition":
            continue
        if rule.get("type") == kind and rule.get("vendor", vendor) == vendor:
            return True
    return False


def build_materials(res):
    rules = bs.blacklist(res)
    out = {}
    for key, (lines, aliases, notes) in MATERIALS.items():
        variants = [v for line in lines for v in bs.filament_variants(res, line)]
        base = variants[0]
        chambers = [int(_first(v, "chamber_temperatures")) for v in variants]
        heated = [c for c in chambers if c > 0]
        out[key] = {
            "studio_profiles": lines,
            "aliases": aliases,
            "filament_type": _first(base, "filament_type"),
            "nozzle_c": [int(_first(base, "nozzle_temperature_range_low")),
                         int(_first(base, "nozzle_temperature_range_high"))],
            "bed_c": int(_first(base, "textured_plate_temp")),
            "chamber_c": max(heated) if heated else None,
            "needs_enclosure": bool(heated),
            "needs_heated_chamber": bool(heated) and len(heated) == len(chambers),
            "abrasive": any(int(_first(v, "required_nozzle_HRC")) >= ABRASIVE_HRC for v in variants),
            "ams_compatible": not _ams_prohibited(rules, base),
            "soluble": SOLUBLE_OVERRIDES.get(key, _first(base, "filament_soluble") == "1"),
            "support": _first(base, "filament_is_support") == "1",
            "min_wall_mm": MIN_WALL_MM,
            "printers": _printer_keys(res, lines),
            "notes": notes,
        }
    return out


def materials_document(res):
    version = bs.versions(res)
    return {
        "schema": 1,
        "about": (
            "Filament materials the skill knows, derived from Bambu Studio's system filament profiles by "
            "tests/datagen/import_bambu_studio.py. nozzle_c is the profile's allowed range; bed_c its "
            "Textured PEI plate temperature; chamber_c the highest chamber temperature any of its profiles "
            "sets. needs_enclosure: Bambu Studio heats the chamber for it where the printer can (warping "
            "risk on open printers; Bambu Studio still ships some open-printer profiles). "
            "needs_heated_chamber: every profile heats the chamber. abrasive: the profile requires a "
            "hardened nozzle (HRC 40). ams_compatible: not prohibited in the AMS by "
            "Resources/printers/filaments_blacklist.json. printers: printers with a Bambu Studio profile "
            "for it. min_wall_mm: two perimeters with a 0.4 mm nozzle at Bambu Studio's default line widths."
        ),
        "bambu_studio": {"app_version": version["app"], "profiles_version": version["profiles"]},
        "retrieved": datetime.date.today().isoformat(),
        "materials": build_materials(res),
        "unsupported": UNSUPPORTED,
    }


def _filament_types(res):
    """Bambu filament_id (``GFA00``) -> (filament_type, is_support) from the @base profiles."""
    folder = res / "profiles" / "BBL" / "filament"
    types = {}
    for name in bs._profiles_by_name(folder):
        if name.endswith("@base"):
            profile = bs.flatten(folder, name)
            fid = profile.get("filament_id")
            if isinstance(fid, str):
                types.setdefault(fid, (_first(profile, "filament_type"), _first(profile, "filament_is_support") == "1"))
    return types


def build_filaments(res):
    types = _filament_types(res)
    lines, colors = {}, []
    for row in bs.color_table(res):
        line = row["fila_type"]
        if line not in LINE_FINISH:
            raise SystemExit(f"New Bambu product line {line!r}: add it to LINE_FINISH")
        material, support = types[row["fila_id"]]
        lines.setdefault(line, {"filament_id": row["fila_id"], "material": material,
                                "finish": LINE_FINISH[line], "support": support})
        rgba = [c.upper() for c in row["fila_color"]]
        color = {"line": line, "name": row["fila_color_name"]["en"].strip(), "hex": rgba[0][:7],
                 "finish": "translucent" if any(c[7:] != "FF" for c in rgba) else LINE_FINISH[line],
                 "pattern": PATTERNS[row["fila_color_type"]], "code": row["fila_color_code"]}
        if len(rgba) > 1:
            color["hexes"] = [c[:7] for c in rgba]
        colors.append(color)
    return lines, colors


def filaments_document(res):
    version = bs.versions(res)
    lines, colors = build_filaments(res)
    return {
        "schema": 1,
        "about": (
            "Bambu Lab's filament colour table as shipped in Bambu Studio "
            "(Resources/profiles/BBL/filament/filaments_color_codes.json), converted by "
            "tests/datagen/import_bambu_studio.py. hex is the first colour of the spool; gradient and "
            "multicolor spools list all of them in hexes. A colour whose alpha is below FF is marked "
            "translucent. code is Bambu's colour code (the 5 digits in the product SKU)."
        ),
        "bambu_studio": {"app_version": version["app"], "profiles_version": version["profiles"]},
        "retrieved": datetime.date.today().isoformat(),
        "finishes": FINISHES,
        "lines": lines,
        "colors": colors,
    }


def dump(document, one_line_key=None):
    """JSON with a 2-space indent; items of ``one_line_key`` (the last key) one per line, for short diffs."""
    if one_line_key is None:
        return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    head = json.dumps({k: v for k, v in document.items() if k != one_line_key}, ensure_ascii=False, indent=2)
    rows = ",\n".join("    " + json.dumps(item, ensure_ascii=False) for item in document[one_line_key])
    return head[: -len("\n}")] + f',\n  "{one_line_key}": [\n{rows}\n  ]\n}}\n'


def _same_data(path, document):
    """Compare everything but the retrieval date."""
    if not path.exists():
        return False
    old = json.loads(path.read_text(encoding="utf-8"))
    return {**old, "retrieved": None} == {**document, "retrieved": None}


def main(argv):
    res = bs.resources_dir()
    if res is None:
        print("Bambu Studio not found; set BAMBU_STUDIO_RESOURCES to its Resources folder.", file=sys.stderr)
        return 2
    outputs = [(MATERIALS_JSON, materials_document(res), None),
               (FILAMENTS_JSON, filaments_document(res), "colors")]
    stale = [(path, doc, keys) for path, doc, keys in outputs if not _same_data(path, doc)]
    for path, doc, keys in stale:
        if "--write" in argv:
            path.write_text(dump(doc, keys), encoding="utf-8")
        print(f"{'wrote' if '--write' in argv else 'out of date'}: {path.relative_to(ROOT)}")
    if not stale:
        print("assets/materials.json and assets/filaments.json match Bambu Studio")
    return 1 if stale and "--write" not in argv else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
