#!/usr/bin/env python3
"""
Slice a model with the Bambu Studio command line and report print time and filament.

Uses the Bambu Studio installed on this computer and its own printer profiles, so the
sliced 3MF keeps the printer's real start sequence (bed levelling, vibration
compensation, AMS loading) and opens in Bambu Studio ready to print. The time is the
slicer's own estimate, including that start sequence.

Usage:
  python3 scripts/slice.py model.stl                     # configured printer, 0.4 nozzle, its default PLA
  python3 scripts/slice.py model.3mf --printer P1S --quality fine
  python3 scripts/slice.py model.stl --material PETG --layer-height 0.16 -o out.3mf
  python3 scripts/slice.py model.stl --json              # one JSON document on stdout
  python3 scripts/slice.py --list-profiles --printer A1  # nozzles, qualities, materials

Exit codes: 0 ok · 1 slicing failed · 2 bad arguments / printer not configured ·
3 Bambu Studio not installed.
"""

import argparse
import json
import sys
from pathlib import Path

from bambu_studio_ai.slicing import (
    GUI_ONLY_SUFFIXES,
    MODEL_SUFFIXES,
    PRINTER_FAMILIES,
    QUALITIES,
    PrintRequest,
    ProfileChoice,
    ProfileError,
    ProfileLibrary,
    ResolveError,
    SliceError,
    SliceJob,
    SliceResult,
    find_cli,
    find_profiles_dir,
    printer_key,
    resolve_profiles,
    run_slice,
)
from bambu_studio_ai.slicing.resolve import (
    compatible,
    find_filament,
    find_machine,
    find_process,
    layer_heights,
    machines_by_nozzle,
    material_types,
)
from common import get_config, load_config, use_utf8_stdio

EXIT_OK, EXIT_FAILED, EXIT_CONFIG, EXIT_DEPENDENCY = 0, 1, 2, 3

INSTALL_HINT = (
    "Bambu Studio not found. Install it from https://bambulab.com/en/download/studio "
    "(02.05.02 or newer) and start it once. If it is installed somewhere unusual, set "
    "BAMBU_STUDIO_CLI to its executable and BAMBU_STUDIO_PROFILES to the folder holding BBL.json."
)

REMOVED_FLAGS = {
    "--filament": "`--filament` was renamed to `--material`. It takes a type (PLA, PETG, TPU) "
                  "or a Bambu Studio filament name, e.g. --material \"Bambu PETG HF\".",
    "--orient": "slice.py no longer re-orients models: it slices them as placed, so the "
                "orientation chosen by `analyze.py --orient` or in Bambu Studio is what prints.",
    "--arrange": "slice.py no longer arranges the plate: Bambu Studio centres a single model "
                 "on the plate, and a 3MF keeps its own arrangement.",
    "--no-detect": "slice.py no longer asks the printer what it is. It uses --printer, or the "
                   "configured model (python3 scripts/configure.py set model P1S).",
}
REMOVED_VALUES = {
    ("--quality", "extra"): "`--quality extra` was removed: the qualities are now the printer's "
                            "own Draft, Standard and Fine presets. For finer layers ask for a "
                            "height, e.g. --layer-height 0.08 (see --list-profiles).",
}


def removed_option(argv: list[str]) -> str | None:
    """Return the explanation for a removed flag or flag value in argv, if any."""
    for index, arg in enumerate(argv):
        flag, has_value, value = arg.partition("=")
        if flag in REMOVED_FLAGS:
            return REMOVED_FLAGS[flag]
        if not has_value and index + 1 < len(argv):
            value = argv[index + 1]
        if (flag, value.lower()) in REMOVED_VALUES:
            return REMOVED_VALUES[flag, value.lower()]
    return None


def millimetres(text: str) -> float:
    """argparse type for "0.4" / "0.4mm"."""
    try:
        value = float(text.lower().removesuffix("mm").strip())
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a size in mm: {text!r}") from None
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Slice a model with Bambu Studio's command line and its own printer "
                    "profiles; report print time and filament.",
        epilog="The printer defaults to the configured model (configure.py set model P1S).",
    )
    parser.add_argument("model", nargs="?", help="model to slice: " + ", ".join(MODEL_SUFFIXES))
    parser.add_argument("--printer", metavar="MODEL", help="printer model: " + ", ".join(PRINTER_FAMILIES))
    parser.add_argument("--nozzle", type=millimetres, default=0.4, metavar="MM",
                        help="nozzle diameter in mm (default: 0.4)")
    parser.add_argument("--material", metavar="MATERIAL", help="PLA, PETG, TPU, ABS, … or a Bambu Studio filament name "
                                           "(default: the printer's default, Bambu PLA Basic)")
    layers = parser.add_mutually_exclusive_group()
    layers.add_argument("--quality", choices=QUALITIES, default="standard",
                        help="draft ≈ 0.6 × nozzle, standard = the printer's default, fine ≈ 0.3 × nozzle")
    layers.add_argument("--layer-height", type=millimetres, metavar="MM",
                        help="an exact layer height that has a Bambu Studio preset, e.g. 0.16")
    parser.add_argument("-o", "--output", metavar="OUT.3mf",
                        help="sliced 3MF to write (default: <model>_sliced.3mf next to the model)")
    parser.add_argument("--timeout", type=float, default=300.0, metavar="SECONDS",
                        help="seconds to allow Bambu Studio (default: 300)")
    parser.add_argument("--json", action="store_true", help="print one JSON document")
    parser.add_argument("--list-profiles", action="store_true",
                        help="list printers, nozzles, qualities and materials instead of slicing")
    return parser


def fail(message, code, *, as_json, kind):
    """Report an error on stderr (and as JSON on stdout with --json); return the exit code."""
    if as_json:
        print(json.dumps({"error": {"type": kind, "message": message}}))
    print(f"❌ {message}", file=sys.stderr)
    return code


def configured_printer(requested):
    """(model key, error kind, error message): from --printer, else the configured model."""
    name = requested or get_config("BAMBU_MODEL", load_config(), "model")
    valid = ", ".join(PRINTER_FAMILIES)
    if not name:
        return None, "not_configured", (
            f"No printer given and none configured. Pass --printer ({valid}) "
            "or run: python3 scripts/configure.py set model <model>")
    key = printer_key(name)
    if key is None:
        return None, "unknown_printer", f"Unknown printer {name!r}. Use one of: {valid}"
    return key, "", ""


def load_library(*, as_json):
    """(cli, library, exit code): the installed Bambu Studio and its profiles."""
    cli = find_cli()
    root = find_profiles_dir(cli=cli)
    if cli is None or root is None:
        return None, None, fail(INSTALL_HINT, EXIT_DEPENDENCY, as_json=as_json, kind="dependency")
    try:
        return cli, ProfileLibrary(root), EXIT_OK
    except ProfileError as exc:
        return None, None, fail(f"Bambu Studio's profiles are unreadable: {exc}", EXIT_FAILED,
                                as_json=as_json, kind="profiles")


def check_model(path, *, as_json):
    """Exit code for a model file that can't be sliced, or None if it can."""
    suffix = path.suffix.lower()
    if not path.is_file():
        return fail(f"File not found: {path}", EXIT_CONFIG, as_json=as_json, kind="not_found")
    if suffix in GUI_ONLY_SUFFIXES:
        return fail("Bambu Studio's command line can't read STEP files (the app can). Export an "
                    "STL or 3MF from your CAD tool, or open the STEP with `python3 scripts/bambu.py "
                    "open` and slice it in Bambu Studio.",
                    EXIT_CONFIG, as_json=as_json, kind="unsupported_format")
    if suffix not in MODEL_SUFFIXES:
        return fail(f"Can't slice {suffix or 'files without an extension'}. Use one of: "
                    + ", ".join(MODEL_SUFFIXES), EXIT_CONFIG, as_json=as_json, kind="unsupported_format")
    return None


def output_path(model, requested):
    if requested:
        return Path(requested).expanduser().resolve()
    return model.with_name(f"{model.stem}_sliced.3mf")


def format_duration(seconds):
    minutes = max(1, round(seconds / 60))
    hours, mins = divmod(minutes, 60)
    return f"{hours} h {mins} min" if hours else f"{mins} min"


def slice_report(choice: ProfileChoice, result: SliceResult, *, model, cli, library):
    """The --json document for a finished slice."""
    estimate = result.estimate
    return {
        "schema": 1,
        "output_file": str(result.output_file),
        "input_file": str(model),
        "printer": choice.printer,
        "nozzle_mm": float(choice.nozzle),
        "layer_height_mm": choice.layer_height_mm,
        "material": choice.material,
        "machine_profile": choice.machine,
        "process_profile": choice.process,
        "filament_profiles": [choice.filament],
        "plate": choice.bed_type or None,
        # total_predication: what the printer shows, start sequence included
        "print_time_s": round(estimate.print_time_s),
        "print_time_includes_start_sequence": True,
        "filament_g": round(estimate.filament_g, 2),
        "filaments": [
            {"slot": use.slot, "filament_id": use.filament_id, "grams": round(use.grams, 2),
             "profile": choice.filament if use.slot == 1 else None}
            for use in estimate.filaments
        ],
        "plates": estimate.plates,
        "estimate_source": estimate.source,
        "warnings": list(estimate.warnings),
        "bambu_studio": {"version": result.bambu_studio_version, "cli": " ".join(cli),
                         "profiles_dir": str(library.root), "profiles_version": library.version},
        "slice_seconds": round(result.seconds, 2),
    }


def print_slice(choice: ProfileChoice, result: SliceResult):
    estimate = result.estimate
    version = f" {result.bambu_studio_version}" if result.bambu_studio_version else ""
    print(f"🖨️ {choice.printer} · {choice.nozzle} mm nozzle · {choice.layer_height_mm:g} mm layers · "
          f"{choice.material}")
    print(f"   Profiles: {choice.machine} | {choice.process} | {choice.filament}")
    if choice.bed_type:
        print(f"   Plate: {choice.bed_type} (the printer's default)")
    print(f"✅ Sliced with Bambu Studio{version} in {result.seconds:.1f} s")
    for warning in estimate.warnings:
        print(f"⚠️ {warning}")
    print(f"≈ {format_duration(estimate.print_time_s)} incl. start sequence · "
          f"{estimate.filament_g:.1f} g {choice.material}")
    print(f"➡️ Use this file: {result.output_file}")


def cmd_slice(args):
    as_json = args.json
    model = Path(args.model).expanduser().resolve()
    code = check_model(model, as_json=as_json)
    if code is not None:
        return code
    printer, kind, problem = configured_printer(args.printer)
    if printer is None:
        return fail(problem, EXIT_CONFIG, as_json=as_json, kind=kind)
    output = output_path(model, args.output)
    if output.suffix.lower() != ".3mf" or output == model:
        return fail("-o must name a new .3mf file (not the input)", EXIT_CONFIG,
                    as_json=as_json, kind="bad_output")
    cli, library, code = load_library(as_json=as_json)
    if library is None:
        return code
    request = PrintRequest(printer=printer, nozzle_mm=args.nozzle, material=args.material,
                           quality=args.quality, layer_height_mm=args.layer_height)
    try:
        choice = resolve_profiles(library, request)
        job = SliceJob(model=model, output=output, timeout_s=args.timeout, bed_type=choice.bed_type,
                       machine=library.flatten("machine", choice.machine),
                       process=library.flatten("process", choice.process),
                       filament=library.flatten("filament", choice.filament))
    except ResolveError as exc:
        return fail(str(exc), EXIT_CONFIG, as_json=as_json, kind="no_profile")
    except ProfileError as exc:
        return fail(f"Bambu Studio's profiles are inconsistent: {exc}", EXIT_FAILED,
                    as_json=as_json, kind="profiles")
    if not as_json:
        print(f"Slicing {model.name} for {printer}…", file=sys.stderr)
    try:
        result = run_slice(cli, job)
    except (SliceError, OSError) as exc:
        return fail(f"Slicing failed: {exc}", EXIT_FAILED, as_json=as_json, kind="slice_failed")
    if as_json:
        print(json.dumps(slice_report(choice, result, model=model, cli=cli, library=library)))
    else:
        print_slice(choice, result)
    return EXIT_OK


def printer_options(library, printer, nozzle):
    """Qualities, layer heights and materials for one printer and nozzle."""
    machine = find_machine(library, PRINTER_FAMILIES[printer], nozzle)
    processes = compatible(library, "process", machine[0])
    filaments = compatible(library, "filament", machine[0])
    return {
        "printer": printer,
        "machine_profile": machine[0],
        "qualities": {q: find_process(library, machine, q)[0] for q in QUALITIES},
        "layer_heights_mm": [float(h) for h in layer_heights(processes)],
        "materials": material_types(filaments),
        "default_filament": find_filament(library, machine, None)[0],
    }


def cmd_list(args):
    as_json = args.json
    cli, library, code = load_library(as_json=as_json)
    if library is None:
        return code
    printers = [{"printer": key, "machine_family": family,
                 "nozzles_mm": [float(n) for n in machines_by_nozzle(library, family)]}
                for key, family in PRINTER_FAMILIES.items()]
    printer, kind, problem = configured_printer(args.printer)
    if kind == "unknown_printer":
        return fail(problem, EXIT_CONFIG, as_json=as_json, kind=kind)
    selected = None
    if printer is not None:
        try:
            selected = printer_options(library, printer, args.nozzle)
        except ResolveError as exc:
            return fail(str(exc), EXIT_CONFIG, as_json=as_json, kind="no_profile")
        except ProfileError as exc:
            return fail(f"Bambu Studio's profiles are inconsistent: {exc}", EXIT_FAILED,
                        as_json=as_json, kind="profiles")
    if as_json:
        print(json.dumps({"schema": 1, "profiles_dir": str(library.root),
                          "profiles_version": library.version, "printers": printers,
                          "qualities": list(QUALITIES), "selected": selected}))
        return EXIT_OK
    print(f"Bambu Studio profiles {library.version}: {library.root}")
    print("Printers (--printer) and nozzles (--nozzle):")
    for entry in printers:
        nozzles = ", ".join(f"{n:g}" for n in entry["nozzles_mm"]) or "none in this Bambu Studio"
        print(f"  {entry['printer']:8} {entry['machine_family']:22} {nozzles}")
    if selected is None:
        print("Add --printer MODEL to see its qualities and materials.")
        return EXIT_OK
    print(f"\n{selected['machine_profile']}:")
    for quality, process in selected["qualities"].items():
        print(f"  --quality {quality:8} → {process}")
    print("  --layer-height " + ", ".join(f"{h:g}" for h in selected["layer_heights_mm"]))
    print("  --material " + ", ".join(selected["materials"]))
    print(f"  default filament: {selected['default_filament']}")
    return EXIT_OK


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    removed = removed_option(argv)
    if removed:
        print(removed, file=sys.stderr)
        return EXIT_CONFIG
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_profiles:
        return cmd_list(args)
    if not args.model:
        parser.error("give a model file to slice, or --list-profiles")
    return cmd_slice(args)


if __name__ == "__main__":
    use_utf8_stdio()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
