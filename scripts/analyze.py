#!/usr/bin/env python3
"""
Check a 3D model for printability on a Bambu Lab printer, fixing what is safe to fix.

Usage:
  python3 scripts/analyze.py model.stl [--printer A1] [--material PLA] [--json]
  python3 scripts/analyze.py model.3mf --orient --repair --height 60

Steps run in this order; each one that changes the model writes a file named after the
previous step's file (STL, OBJ, GLB and 3MF keep their format, anything else becomes STL):
  unit conversion / --height  -> _scaled
  repair                      -> _repaired  (holes and flipped faces by default; --repair for more)
  --keep-main                 -> _cleaned
  --orient                    -> _oriented
The last file written is the one to use: it is reported as output_file and on the
final "Use this file" line.

Exit codes: 0 analysed · 1 file unreadable or not writable · 2 bad arguments ·
3 missing dependency.
"""

import argparse
import json
import math
import sys
from pathlib import Path

from bambu_studio_ai.mesh import (
    MM_PER_UNIT,
    MaterialProfile,
    MeshLoadError,
    MeshSaveError,
    PrinterProfile,
    analyze,
    decide_units,
    derived_path,
    diagnose,
    keep_largest_body,
    load_mesh,
    orient_for_printing,
    repair_mesh,
    save_mesh,
)
from common import (
    BUILD_VOLUMES, ENCLOSED_PRINTERS, HIGH_TEMP_PRINTERS, MATERIALS,
    get_config, load_config, use_utf8_stdio,
)

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_DEPENDENCY = 0, 1, 2, 3
DEFAULT_PRINTER = "A1"
DEFAULT_MATERIAL = "PLA"
MIN_HEIGHT_MM = 0.01  # a model flatter than this cannot be scaled to a height
SCHEMA = 1

REMOVED_FLAGS = {
    "--render": "ignored the view direction and needed pyglet, so it rendered nothing useful. "
                "Use scripts/preview.py for images.",
    "--output-dir": "only chose where --render put its images. Derived models are written "
                    "next to the input.",
    "--no-clean": "did nothing: loose parts are only ever removed with --keep-main.",
    "--no-simplify": "switched off a simplification step that never worked (it called trimesh "
                     "with the wrong arguments and needed a package that is not installed). "
                     "To simplify, use Bambu Studio: right-click the model, Simplify Model.",
}
REMOVED_MESSAGE = "`analyze.py {flag}` was removed in v2.1: it {why}\n"
STATUS_MARK = {"pass": "✅", "warn": "⚠️", "fail": "❌", "skipped": "➖"}


class UsageError(Exception):
    """Bad command-line input (exit 2)."""


def build_parser():
    parser = argparse.ArgumentParser(
        description="Check a 3D model for printability, repair it, and orient it for printing.",
        epilog="Each step that changes the model writes a new file; the last one is printed at the end.",
    )
    parser.add_argument("file", help="model file (.stl, .3mf, .obj, .glb, .ply)")
    parser.add_argument("--printer", help="printer model, e.g. 'A1 Mini' (default: configured printer, else A1)")
    parser.add_argument("--material", default=DEFAULT_MATERIAL, help="filament: " + ", ".join(MATERIALS))
    parser.add_argument("--purpose", default="general", choices=["general", "decorative", "functional"],
                        help="changes the infill and wall suggestions (not the score)")
    parser.add_argument("--unit", default="auto", choices=["auto", *MM_PER_UNIT],
                        help="unit of the file's coordinates (default: auto, see the report)")
    parser.add_argument("--height", type=float, help="scale uniformly so the model is this many mm tall")
    parser.add_argument("--orient", action="store_true",
                        help="put the model on a flat base on the plate (kept if it already has one)")
    parser.add_argument("--repair", action="store_true",
                        help="also fill large holes and, with pymeshlab installed, fix non-manifold edges")
    parser.add_argument("--no-auto-repair", action="store_true",
                        help="don't fix small holes and flipped faces automatically")
    parser.add_argument("--keep-main", action="store_true",
                        help="keep only the largest body (refused when no body clearly dominates)")
    parser.add_argument("--json", action="store_true", help="print one JSON document on stdout")
    return parser


def resolve_printer(requested, config, notes):
    """PrinterProfile for --printer, the configured printer or the A1; None if unknown."""
    by_name = {name.lower(): name for name in BUILD_VOLUMES}
    if requested:
        name = by_name.get(requested.lower().removeprefix("bambu lab ").strip())
        if name is None:
            raise UsageError(f"unknown printer '{requested}'. Known: {', '.join(BUILD_VOLUMES)}")
    else:
        configured = get_config("BAMBU_MODEL", config, "model")
        name = by_name.get(str(configured).lower()) if configured else DEFAULT_PRINTER
        if name is None:
            notes.append(f"Configured printer '{configured}' is not in the printer table, so the "
                         "build volume and material were not checked. Pass --printer.")
            return None
        if not configured:
            notes.append(f"No printer configured: checked against the {DEFAULT_PRINTER} (pass --printer).")
    x, y, z = BUILD_VOLUMES[name]
    return PrinterProfile(name, (float(x), float(y), float(z)), name in ENCLOSED_PRINTERS,
                          name in HIGH_TEMP_PRINTERS)


def resolve_material(requested, notes):
    name = requested.upper()
    if name not in MATERIALS:
        notes.append(f"Unknown material '{requested}': used {DEFAULT_MATERIAL} values. "
                     f"Known: {', '.join(MATERIALS)}.")
        name = DEFAULT_MATERIAL
    data = MATERIALS[name]
    return MaterialProfile(
        name=name, min_wall_mm=float(data["min_wall"]), nozzle_min_c=int(data["min_temp"]),
        nozzle_max_c=int(data["max_temp"]), bed_c=int(data["bed"]),
        infill_decorative_pct=int(data["infill_deco"]), infill_functional_pct=int(data["infill_func"]),
        needs_enclosure=bool(data["enclosed"]),
    )


def prepare(args, log, notes):
    """Load the model and run the requested steps. Returns (mesh, steps, units, written)."""
    source = Path(args.file)
    loaded = load_mesh(source)
    mesh, current, written, steps = loaded.mesh, source, [], {}

    def record(name, entry):
        steps[name] = entry
        log(entry["summary"])

    def write(suffix):
        nonlocal current
        current = derived_path(current, suffix)
        save_mesh(mesh, current)
        written.append(str(current))
        log(f"💾 {current}")
        return str(current)

    units = decide_units(float(max(mesh.extents)), declared=loaded.declared_unit,
                         requested=None if args.unit == "auto" else args.unit)
    # --height sets the final size directly, so the unit guess only matters without it.
    factor, reason = units.scale, f"{units.unit} to mm"
    if args.height and mesh.extents[2] >= MIN_HEIGHT_MM:
        factor, reason = args.height / float(mesh.extents[2]), f"to {args.height:g} mm tall"
    else:
        log(units.note)
        if args.height:
            notes.append("--height ignored: the model is flat along Z.")
        elif units.doubtful:
            notes.append(units.note)
    if not math.isclose(factor, 1.0):
        mesh.apply_scale(factor)
        record("scale", {"factor": round(factor, 6), "summary": f"Scaled x{factor:.4g} ({reason}).",
                         "file": write("_scaled")})

    tier = diagnose(mesh).repair_tier
    if tier != "none":
        if args.repair or (tier == "minor" and not args.no_auto_repair):
            mesh, repair = repair_mesh(mesh, thorough=args.repair)
            summary = ("Repaired: " + "; ".join(repair.steps) + ".") if repair.changed else "Repair changed nothing."
            record("repair", {"applied": True, "tier": tier, "summary": summary, **repair.to_dict(),
                              "file": write("_repaired") if repair.changed else None})
            notes.extend(repair.notes)
        else:
            why = "--no-auto-repair was given" if tier == "minor" else "non-manifold edges need --repair"
            record("repair", {"applied": False, "tier": tier, "summary": f"Not repaired: {why}."})

    if args.keep_main:
        mesh, kept = keep_largest_body(mesh)
        record("keep_main", {**vars(kept), "summary": f"--keep-main: {kept.note}.",
                             "file": write("_cleaned") if kept.removed else None})

    if args.orient:
        mesh, orient = orient_for_printing(mesh)
        record("orient", {**orient.to_dict(), "summary": f"--orient: {orient.reason}.",
                          "file": write("_oriented") if orient.moved else None})
        if orient.rotated and args.height:
            notes.append(f"--height {args.height:g} was applied before --orient turned the model; "
                         f"it now stands {float(mesh.extents[2]):.1f} mm tall on the plate.")
    return mesh, steps, units, written


def format_report(doc):
    geometry, lines = doc["geometry"], []
    size = " x ".join(f"{value:g}" for value in geometry["dimensions_mm"])
    volume = f"{geometry['volume_cm3']:g} cm3" if geometry["volume_cm3"] is not None else "no volume (open mesh)"
    lines.append(f"🔍 {Path(doc['file']).name}: {doc['printer'] or 'unknown printer'}, {doc['material']}")
    bodies = "1 body" if geometry["bodies"] == 1 else f"{geometry['bodies']} bodies"
    lines.append(f"Size {size} mm · {volume} · {geometry['triangles']:,} triangles · {bodies}")
    rubric = doc["score_rubric"]
    detail = [f"{d['check']} {d['points']:g}" for d in rubric["deductions"] if d["points"]]
    detail += [f"capped at {c['limit']:g}: {c['rule']}" for c in rubric["caps"] if c["applied"]]
    lines.append(f"Score {doc['score']:g}/10" + (f" ({'; '.join(detail)})" if detail else ""))
    lines.append("")
    lines.extend(f"{STATUS_MARK[c['status']]} {c['name']}: {c['summary']}" for c in doc["checks"])
    changes = [step["summary"] for step in doc["steps"].values()]
    for title, items in (("Changes", changes), ("Notes", doc["notes"]), ("Suggestions", doc["suggestions"])):
        if items:
            lines.extend(["", f"{title}:"] + [f"  - {item}" for item in items])
    settings = doc["print_settings"]
    lines += ["", "Settings: " + " · ".join(f"{key.replace('_', ' ')} {value}" for key, value in settings.items())]
    return "\n".join(lines)


def fail(message, code, *, as_json, kind):
    if as_json:
        print(json.dumps({"error": {"type": kind, "message": message}}))
    print(f"❌ {message}", file=sys.stderr)
    return code


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    for arg in argv:
        flag = arg.split("=", 1)[0]
        if flag in REMOVED_FLAGS:
            print(REMOVED_MESSAGE.format(flag=flag, why=REMOVED_FLAGS[flag]), file=sys.stderr)
            return EXIT_USAGE
    args = build_parser().parse_args(argv)
    as_json, notes = args.json, []

    def log(message):
        print(message, file=sys.stderr)

    try:
        if args.height is not None and args.height <= 0:
            raise UsageError("--height must be a positive number of millimetres")
        if not Path(args.file).is_file():
            raise UsageError(f"file not found: {args.file}")
        printer = resolve_printer(args.printer, load_config(), notes)
        material = resolve_material(args.material, notes)
        mesh, steps, units, written = prepare(args, log, notes)
    except UsageError as exc:
        return fail(str(exc), EXIT_USAGE, as_json=as_json, kind="usage")
    except (MeshLoadError, MeshSaveError) as exc:
        return fail(str(exc), EXIT_FAILED, as_json=as_json, kind="file")
    except ImportError as exc:
        return fail(f"missing Python package '{exc.name}': pip install -r requirements.txt",
                    EXIT_DEPENDENCY, as_json=as_json, kind="dependency")

    analysis = analyze(mesh, material=material, printer=printer, purpose=args.purpose)
    output_file = written[-1] if written else str(Path(args.file))
    doc = {"schema": SCHEMA, "file": str(Path(args.file)), "output_file": output_file,
           "written_files": written, "printer": printer.name if printer else None,
           "material": material.name, "purpose": args.purpose, "units": units.to_dict(),
           "steps": steps, **analysis.to_dict(), "notes": notes}
    if as_json:
        print(json.dumps(doc, indent=2, allow_nan=False, ensure_ascii=False))
    else:
        print(format_report(doc))
    print(f"\n➡️ Use this file: {output_file}", file=sys.stderr if as_json else sys.stdout)
    return EXIT_OK


if __name__ == "__main__":
    use_utf8_stdio()
    sys.exit(main())
