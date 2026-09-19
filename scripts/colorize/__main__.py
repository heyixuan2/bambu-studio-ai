#!/usr/bin/env python3
"""
Turn a textured model into a Bambu Studio project painted with up to 8 filaments.

Reads the model's base-colour texture (GLB, glTF or OBJ), picks a palette, gives every
triangle one filament and writes a Bambu Studio project 3MF in which the filaments
are already set up. Pure Python: no Blender needed.

Usage:
  python3 scripts/colorize model.glb --height 60
  python3 scripts/colorize model.glb --height 60 --max-colors 6 --json
  python3 scripts/colorize model.glb --colors "#FFFFFF,#1A1A1A,#E0301E"
  python3 scripts/colorize model.glb --format obj        # vertex-colour OBJ instead

Exit codes: 0 ok · 1 failed (no colours in the model, a colour would be lost,
unreadable model, write error) · 2 bad arguments or input not found.
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # scripts/, for the library

from bambu_studio_ai.color import (  # noqa: E402
    DEFAULT_MAX_COLORS,
    DEFAULT_MIN_AREA,
    DEFAULT_SMOOTH_PASSES,
    MAX_COLORS,
    METRIC,
    TEMPLATE_PRINTER,
    ColorizeOptions,
    ColorsLostError,
    Filament,
    ModelLoadError,
    NoColourError,
    Palette,
    build_obj,
    build_project,
    colorize,
    nearest_filaments,
    render_preview,
)
from bambu_studio_ai.filaments import filament_colors  # noqa: E402
from colorize.bambu_map import load_bambu_palette  # noqa: E402
from common import use_utf8_stdio  # noqa: E402

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
FORMATS = ("3mf", "obj")

# Flags of the Blender pipeline that have no meaning any more: accepted, noted, ignored.
REMOVED_FLAGS = {
    "--no-merge": "colour families are gone; similar colours merge by CIEDE2000",
    "--method": "there is one palette method now (k-means in CIELAB, no scikit-learn)",
    "--subdivide": "paint is per triangle in the 3MF, so the mesh is never subdivided",
    "--island-size": "speckle is smoothed on the mesh (--smooth), not in the texture",
    "--no-geometry-protect": "the curvature protection was removed (it protected UV seams)",
    "--bambu-map": "filament suggestions are always included now",
}
_FLAGS_WITH_VALUE = {"--method", "--subdivide", "--island-size"}


def build_parser():
    parser = argparse.ArgumentParser(
        prog="colorize",
        description="Turn a textured model (GLB/glTF/OBJ) into a Bambu Studio project "
        f"painted with up to {MAX_COLORS} filaments.",
        epilog="Open the .3mf in Bambu Studio: the filaments are already listed; map them to "
        "your AMS slots there.",
    )
    parser.add_argument("input", help="textured model: .glb, .gltf or .obj")
    parser.add_argument("-o", "--output", help="output file (default: <input>_multicolor.3mf)")
    parser.add_argument("--max-colors", type=int, default=DEFAULT_MAX_COLORS,
                        help=f"most filaments to use, 1-{MAX_COLORS} (default {DEFAULT_MAX_COLORS})")
    parser.add_argument("--max_colors", "-n", dest="max_colors", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--colors", "-c",
                        help='use these filament colours instead of detecting them: "#RRGGBB,#RRGGBB,..."')
    parser.add_argument("--min-area", type=float, default=DEFAULT_MIN_AREA,
                        help="smallest share of the surface that gets its own filament, as a "
                        f"fraction (default {DEFAULT_MIN_AREA} = {DEFAULT_MIN_AREA * 100:g} %%)")
    parser.add_argument("--min-pct", dest="min_area", type=lambda v: float(v) / 100,
                        help=argparse.SUPPRESS)
    parser.add_argument("--height", type=float, help="scale the model to this height in mm")
    parser.add_argument("--smooth", type=int, default=DEFAULT_SMOOTH_PASSES,
                        help=f"speckle-removal passes over the mesh, 0 = off (default {DEFAULT_SMOOTH_PASSES})")
    parser.add_argument("--format", choices=FORMATS,
                        help="3mf: Bambu Studio project with painted triangles (default); "
                        "obj: vertex-colour OBJ (Bambu Studio asks you to map its colours)")
    parser.add_argument("--bambu-finish", default="opaque,matte", metavar="FINISHES",
                        help="filament finishes the suggestions may use, comma-separated "
                        "(opaque, matte, silk, translucent, …) or 'all' (default: opaque,matte)")
    parser.add_argument("--json", action="store_true", help="print one JSON object on stdout")
    return parser


def finishes(value):
    """--bambu-finish as a set of finish names, or an error message."""
    known = {c.finish for c in filament_colors()}
    if value.strip().lower() == "all":
        return known, None
    wanted = {f.strip().lower() for f in value.split(",") if f.strip()}
    unknown = wanted - known
    if unknown or not wanted:
        return None, (f"--bambu-finish: unknown finish {', '.join(sorted(unknown)) or '(none)'}; "
                      f"choose from {', '.join(sorted(known))} or 'all'")
    return wanted, None


def split_removed_flags(argv):
    """Pull removed flags (and their values) out of argv; return (argv, notes)."""
    kept, notes, skip = [], [], False
    for index, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        flag = arg.split("=", 1)[0]
        if flag in REMOVED_FLAGS:
            notes.append(f"note: {flag} was removed: {REMOVED_FLAGS[flag]}; ignoring it")
            has_value = flag in _FLAGS_WITH_VALUE and "=" not in arg
            skip = has_value and index + 1 < len(argv) and not argv[index + 1].startswith("-")
            continue
        kept.append(arg)
    return kept, notes


def fail(message, code, *, as_json, kind, **extra):
    """Report an error on stderr (and as JSON on stdout with --json); return the exit code."""
    if as_json:
        print(json.dumps({"error": {"type": kind, "message": message, **extra}}))
    print(f"❌ {message}", file=sys.stderr)
    return code


def check_arguments(args, colours):
    """Return an error message for invalid arguments, or None."""
    if not 1 <= args.max_colors <= MAX_COLORS:
        return f"--max-colors must be between 1 and {MAX_COLORS}"
    if not 0 <= args.min_area < 1:
        return "--min-area is a fraction between 0 and 1 (0.002 = 0.2 %)"
    if args.height is not None and args.height <= 0:
        return "--height must be a positive number of millimetres"
    if args.smooth < 0:
        return "--smooth must be 0 or more"
    if args.colors is not None:
        try:
            Palette.from_hex(list(colours))
        except ValueError as exc:
            return f"--colors: {exc}"
    return None


def output_path(args):
    """Resolve (path, format) from --output and --format."""
    source = Path(args.input)
    if args.output:
        path = Path(args.output)
        suffix = path.suffix.lower().lstrip(".")
        fmt = args.format or (suffix if suffix in FORMATS else "3mf")
        return path, fmt
    fmt = args.format or "3mf"
    return source.with_name(f"{source.stem}_multicolor.{fmt}"), fmt


def filament_catalogue(allowed_finishes):
    """Bambu filament colours of the allowed finishes (see colorize/bambu_map.py)."""
    return [Filament(entry["line"], entry["name"], entry["hex"])
            for entry in load_bambu_palette(allowed_finishes)]


def run(args, notes):
    as_json = args.json
    for note in notes:
        print(note, file=sys.stderr)
    colours = tuple(c.strip() for c in args.colors.split(",") if c.strip()) if args.colors else ()
    allowed_finishes, problem = finishes(args.bambu_finish)
    problem = problem or check_arguments(args, colours)
    if problem:
        return fail(problem, EXIT_USAGE, as_json=as_json, kind="bad_arguments")
    source = Path(args.input)
    if not source.is_file():
        return fail(f"file not found: {source}", EXIT_USAGE, as_json=as_json, kind="not_found")
    target, fmt = output_path(args)
    options = ColorizeOptions(max_colors=args.max_colors, min_area=args.min_area, colors=colours,
                              height_mm=args.height, smooth_passes=args.smooth)
    try:
        result = colorize(source, options)
    except ColorsLostError as exc:
        return fail(str(exc), EXIT_FAILED, as_json=as_json, kind="colors_lost",
                    lost=exc.lost, kept=exc.kept)
    except NoColourError as exc:
        return fail(str(exc), EXIT_FAILED, as_json=as_json, kind="no_colour")
    except ModelLoadError as exc:
        return fail(str(exc), EXIT_FAILED, as_json=as_json, kind="unreadable")
    except ValueError as exc:
        return fail(str(exc), EXIT_FAILED, as_json=as_json, kind="failed")

    palette = result.palette.hex
    preview = target.with_name(f"{target.stem}_preview.png")
    try:
        if fmt == "3mf":
            target.write_bytes(build_project(result.vertices, result.faces, result.labels, palette, source.stem))
        else:
            target.write_text(build_obj(result.vertices, result.faces, result.labels, result.palette.rgb),
                              encoding="utf-8")
        image = render_preview(result.vertices, result.faces, result.palette.rgb[result.labels])
        Image.fromarray(image).save(preview)
    except OSError as exc:
        return fail(f"could not write {target}: {exc}", EXIT_FAILED, as_json=as_json, kind="write_failed")

    matches = nearest_filaments(palette, filament_catalogue(allowed_finishes))
    report = {
        "schema": 1,
        "output_file": str(target.resolve()),
        "format": fmt,
        "preview_file": str(preview.resolve()),
        "printer_profile": TEMPLATE_PRINTER if fmt == "3mf" else None,
        "size_mm": [round(v, 2) for v in result.size_mm],
        "triangles": len(result.faces),
        "metric": METRIC,
        "colors": [
            {
                "filament": index + 1,
                "hex": colour,
                "area_pct": round(float(result.area_share[index]) * 100, 2),
                "suggested_filament": None if match is None else {
                    "line": match.filament.line, "name": match.filament.name,
                    "hex": match.filament.hex, "delta_e": match.delta_e,
                },
            }
            for index, (colour, match) in enumerate(zip(palette, matches))
        ],
        "warnings": list(result.warnings),
    }
    if as_json:
        print(json.dumps(report))
        for warning in result.warnings:
            print(f"⚠️ {warning}", file=sys.stderr)
    else:
        print(format_report(source, report))
    return EXIT_OK


def format_report(source, report):
    size = " x ".join(f"{v:g}" for v in report["size_mm"])
    lines = [f"🎨 {source.name}: {len(report['colors'])} filaments, {size} mm, "
             f"{report['triangles']:,} triangles"]
    for colour in report["colors"]:
        match = colour["suggested_filament"]
        hint = f"  ≈ {match['line']} {match['name']} {match['hex']} (ΔE {match['delta_e']})" if match else ""
        lines.append(f"  {colour['filament']}. {colour['hex']}  {colour['area_pct']:5.1f} %{hint}")
    lines.append(f"Suggestions use {report['metric']}: under ~3 looks the same, over ~10 is visibly different.")
    lines += [f"⚠️ {warning}" for warning in report["warnings"]]
    if report["format"] == "3mf":
        lines.append(f"Open it in Bambu Studio: the {len(report['colors'])} filaments are already "
                     "listed; map them to your AMS slots there.")
    else:
        lines.append("Bambu Studio will ask you to map the OBJ's colours to filaments on import.")
    lines.append(f"Preview: {report['preview_file']}")
    lines.append(f"➡️ Use this file: {report['output_file']}")
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    argv, notes = split_removed_flags(argv)
    args = build_parser().parse_args(argv)
    return run(args, notes)


if __name__ == "__main__":
    use_utf8_stdio()
    sys.exit(main())
