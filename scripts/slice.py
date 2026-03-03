#!/usr/bin/env python3
"""
Bambu Lab Slicer — CLI slicing via OrcaSlicer with auto profile merging.

Resolves Bambu Studio profile inheritance chains, fixes known compatibility
issues, and produces print-ready 3MF files with embedded G-code.

Usage:
  python3 scripts/slice.py model.stl                          # Slice with defaults (H2D, 0.20mm, PLA)
  python3 scripts/slice.py model.stl --quality fine            # 0.12mm layer height
  python3 scripts/slice.py model.stl --quality draft           # 0.28mm layer height
  python3 scripts/slice.py model.stl --orient --arrange        # Auto-orient + arrange
  python3 scripts/slice.py model.stl --filament "Bambu PETG Basic"
  python3 scripts/slice.py model.stl --output /path/to/out.3mf
  python3 scripts/slice.py --list-profiles                     # Show available profiles
"""

import os, sys, json, subprocess, argparse, shutil, tempfile, glob, re

# ─── Paths ───
_skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cfg = {}
for _p in [os.path.join(_skill_dir, "config.json"), os.path.join(_skill_dir, ".secrets.json")]:
    if os.path.exists(_p):
        with open(_p) as _f:
            _cfg.update(json.load(_f))

# Slicer discovery
ORCA_PATHS = [
    "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer",
    os.path.expanduser("~/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
]
BS_PATHS = [
    "/Applications/BambuStudio.app/Contents/Resources/profiles/BBL",
    os.path.expanduser("~/Library/Application Support/BambuStudio/system/BBL"),
]

def find_slicer():
    for p in ORCA_PATHS:
        if os.path.exists(p):
            return p
    print("❌ OrcaSlicer not found. Install from https://github.com/SoftFever/OrcaSlicer")
    sys.exit(1)

def find_profiles_dir():
    for p in BS_PATHS:
        if os.path.isdir(p):
            return p
    print("❌ Bambu Studio profiles not found. Install Bambu Studio first.")
    sys.exit(1)

# ─── Profile Merger ───

def load_profile(name, subdir, profiles_dir):
    """Load a profile JSON, resolving inheritance + includes recursively."""
    if os.path.isabs(name):
        path = name
    else:
        path = os.path.join(profiles_dir, subdir, name)
        if not path.endswith(".json"):
            path += ".json"

    if not os.path.exists(path):
        raise FileNotFoundError(f"Profile not found: {path}")

    with open(path) as f:
        data = json.load(f)

    # Resolve parent inheritance
    parent_name = data.get("inherits")
    if parent_name:
        try:
            parent = load_profile(parent_name, subdir, profiles_dir)
            merged = {**parent, **data}
        except FileNotFoundError:
            merged = data
    else:
        merged = data

    # Resolve includes (template gcode files)
    includes = data.get("include", [])
    for inc in includes:
        try:
            inc_data = load_profile(inc, subdir, profiles_dir)
            merged.update(inc_data)
        except FileNotFoundError:
            pass

    return merged

def fix_machine_profile(profile, machine_name=""):
    """Fix known issues in machine profiles for OrcaSlicer CLI compatibility."""
    # 1. nozzle_volume_type from default
    if "nozzle_volume_type" not in profile and "default_nozzle_volume_type" in profile:
        profile["nozzle_volume_type"] = profile["default_nozzle_volume_type"]

    # 2. Ensure 'from' field
    if not profile.get("from"):
        profile["from"] = "system"

    # 3. printer_technology
    if not profile.get("printer_technology"):
        profile["printer_technology"] = "FFF"

    # 4. Fix name and setting_id (overwritten by last include template)
    # Must match compatible_printers in process profiles
    if machine_name:
        profile["name"] = machine_name
        profile["setting_id"] = machine_name

    # 5. G92 E0 in layer_change_gcode (required for relative E)
    lgc = profile.get("layer_change_gcode", "")
    if "G92 E0" not in lgc:
        profile["layer_change_gcode"] = "G92 E0\n" + lgc

    # 6. Simplify gcode templates containing BS 2.5+ syntax
    for gcode_key in ["machine_start_gcode", "change_filament_gcode"]:
        gc = profile.get(gcode_key, "")
        # Check for variables OrcaSlicer doesn't know
        unknown_patterns = [
            "initial_no_support_extruder", "overall_chamber_temperature",
            "min_vitrification_temperature", "cooling_filter_enabled",
            "flush_volumetric_speeds", "retraction_distances_when_cut",
            "first_non_support_filaments", "filament_map",
            "has_tpu_in_first_layer", "long_retraction_when_ec",
            "is_all_bbl_filament", "adaptive_pressure_advance",
        ]
        if any(p in gc for p in unknown_patterns):
            if gcode_key == "machine_start_gcode":
                profile[gcode_key] = _simplify_start_gcode(gc, profile)
            else:
                # For change_filament, use minimal version
                profile[gcode_key] = "; tool change handled by firmware"

    return profile

def _simplify_start_gcode(gcode, profile):
    """Strip BS 2.5.0 start gcode and use OrcaSlicer-compatible version.
    
    BS 2.5.0 uses many variables OrcaSlicer doesn't know (overall_chamber_temperature,
    initial_no_support_extruder, cooling_filter_enabled, flush_volumetric_speeds, etc.).
    Rather than whitelist hundreds of variables, we use a minimal but functional
    start gcode that works with all OrcaSlicer versions.
    
    NOTE: This produces valid G-code for slicing. The actual printer start sequence
    is handled by the printer firmware, so the simplified version is safe.
    """
    return """;===== Bambu Lab start (OrcaSlicer-compatible) =====
G28 ; home all axes
G90 ; absolute positioning
M83 ; relative extruder
M140 S[bed_temperature_initial_layer_single] ; set bed temp
M104 S[nozzle_temperature_initial_layer] ; set nozzle temp
M190 S[bed_temperature_initial_layer_single] ; wait bed
M109 S[nozzle_temperature_initial_layer] ; wait nozzle
G28 Z ; home Z after heating
G1 Z5 F3000
G1 X10 Y10 F6000 ; move to start
G1 Z0.3 F1500 ; lower
G1 X100 E20 F600 ; prime line
G1 X150 E5 F1200
G92 E0 ; reset extruder
;===== start gcode end =====
"""

def fix_process_profile(profile):
    """Fix known issues in process profiles."""
    if not profile.get("from"):
        profile["from"] = "system"

    # Fix values that OrcaSlicer uses but Bambu Studio doesn't recognize
    compat_fixes = {
        "ensure_vertical_shell_thickness": ("ensure_all", {"enabled": "ensure_all"}),
        "ironing_pattern": ("rectilinear", {"zig-zag": "rectilinear"}),
        "support_ironing_pattern": ("rectilinear", {"zig-zag": "rectilinear"}),
    }
    for key, (default, mapping) in compat_fixes.items():
        val = profile.get(key)
        if val in mapping:
            profile[key] = mapping[val]

    # Fix out-of-range defaults
    range_fixes = {
        "prime_tower_brim_width": ("0", 0, None),
        "solid_infill_filament": ("1", 1, None),
        "sparse_infill_filament": ("1", 1, None),
        "wall_filament": ("1", 1, None),
        "tree_support_wall_count": ("0", 0, 2),
    }
    for key, (default, minv, maxv) in range_fixes.items():
        val = profile.get(key)
        if val is not None:
            try:
                ival = int(val) if isinstance(val, str) else val
                if minv is not None and ival < minv:
                    profile[key] = default
                if maxv is not None and ival > maxv:
                    profile[key] = default
            except (ValueError, TypeError):
                pass

    return profile

def fix_filament_profile(profile):
    if not profile.get("from"):
        profile["from"] = "system"
    return profile


def detect_printer_info():
    """Query printer for hardware info (model, nozzle, filaments)."""
    script = os.path.join(os.path.dirname(__file__), "bambu.py")
    try:
        r = subprocess.run(
            ["python3", script, "info", "--json"],
            capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return json.loads(r.stdout)
    except:
        pass
    return None

# ─── Printer Model Mapping ───

PRINTER_PROFILES = {
    "A1 Mini":  {"machine": "Bambu Lab A1 mini", "process_suffix": "A1M"},
    "A1":       {"machine": "Bambu Lab A1",      "process_suffix": "A1"},
    "P1S":      {"machine": "Bambu Lab P1S",     "process_suffix": "X1C"},
    "P2S":      {"machine": "Bambu Lab P1S",     "process_suffix": "X1C"},  # P2S uses P1S profiles
    "X1C":      {"machine": "Bambu Lab X1 Carbon", "process_suffix": "X1C"},
    "X1E":      {"machine": "Bambu Lab X1E",     "process_suffix": "X1E"},
    "H2C":      {"machine": "Bambu Lab H2C",     "process_suffix": "H2C"},
    "H2S":      {"machine": "Bambu Lab H2S",     "process_suffix": "H2S"},
    "H2D":      {"machine": "Bambu Lab H2D",     "process_suffix": "H2D"},
}

QUALITY_MAP = {
    "draft":    "0.24mm",
    "standard": "0.20mm",
    "fine":     "0.12mm",
    "extra":    "0.08mm",
}

def resolve_profiles(printer_model, nozzle, quality, filament_name, profiles_dir):
    """Resolve profile names for a given printer/quality/filament combo."""
    info = PRINTER_PROFILES.get(printer_model)
    if not info:
        print(f"❌ Unknown printer: {printer_model}")
        print(f"   Supported: {', '.join(PRINTER_PROFILES.keys())}")
        sys.exit(1)

    machine_base = info["machine"]
    proc_suffix = info["process_suffix"]

    # Machine profile
    machine_name = f"{machine_base} {nozzle} nozzle"

    # Process profile — try quality@suffix, fall back
    layer = QUALITY_MAP.get(quality, quality)
    process_candidates = [
        f"{layer} Standard @BBL {proc_suffix}",
        f"{layer} Fine @BBL {proc_suffix}",
        f"{layer} Balanced Quality @BBL {proc_suffix}",
    ]

    process_name = None
    for cand in process_candidates:
        path = os.path.join(profiles_dir, "process", cand + ".json")
        if os.path.exists(path):
            process_name = cand
            break

    if not process_name:
        # Broader search
        pattern = os.path.join(profiles_dir, "process", f"{layer}*@BBL {proc_suffix}*.json")
        matches = glob.glob(pattern)
        if matches:
            process_name = os.path.splitext(os.path.basename(matches[0]))[0]
        else:
            print(f"❌ No process profile found for {layer} @ {proc_suffix}")
            sys.exit(1)

    # Filament profile — match to printer
    fil_candidates = [
        f"{filament_name} @BBL {proc_suffix}",
        f"{filament_name} @BBL {machine_base.split()[-1]}",
    ]
    filament_resolved = None
    for cand in fil_candidates:
        path = os.path.join(profiles_dir, "filament", cand + ".json")
        if os.path.exists(path):
            filament_resolved = cand
            break

    if not filament_resolved:
        pattern = os.path.join(profiles_dir, "filament", f"{filament_name}*@BBL*{proc_suffix}*.json")
        matches = glob.glob(pattern)
        if not matches:
            pattern = os.path.join(profiles_dir, "filament", f"{filament_name}*.json")
            matches = glob.glob(pattern)
        if matches:
            filament_resolved = os.path.splitext(os.path.basename(matches[0]))[0]
        else:
            print(f"❌ No filament profile found for: {filament_name}")
            sys.exit(1)

    return machine_name, process_name, filament_resolved

# ─── Main Slice ───


def _fix_3mf_compat(path):
    """Patch 3MF config to use BS 2.5.0 compatible values."""
    import zipfile, shutil, tempfile
    
    # Values that OrcaSlicer writes but BS considers outdated
    replacements = {
        '"ensure_vertical_shell_thickness": "ensure_all"': '"ensure_vertical_shell_thickness": "enabled"',
        '"ironing_pattern": "rectilinear"': '"ironing_pattern": "zig-zag"',
        '"support_ironing_pattern": "rectilinear"': '"support_ironing_pattern": "zig-zag"',
    }
    
    tmppath = path + ".tmp"
    changed = False
    with zipfile.ZipFile(path, 'r') as zin, zipfile.ZipFile(tmppath, 'w') as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith('.config') or item.filename.endswith('.json'):
                text = data.decode('utf-8', errors='replace')
                for old_val, new_val in replacements.items():
                    if old_val in text:
                        text = text.replace(old_val, new_val)
                        changed = True
                data = text.encode('utf-8')
            zout.writestr(item, data)
    
    if changed:
        shutil.move(tmppath, path)
        print("   🔧 Patched OrcaSlicer→BS compat values")
    else:
        os.remove(tmppath)

def slice_model(stl_path, output_path=None, printer_model="H2D", nozzle="0.4",
                quality="standard", filament="Bambu PLA Basic",
                orient=False, arrange=False):
    """Slice an STL file and produce a 3MF with embedded G-code."""

    if not os.path.exists(stl_path):
        # Try adding common extensions
        for ext in [".stl", ".obj", ".3mf"]:
            if os.path.exists(stl_path + ext):
                stl_path = stl_path + ext
                break
        else:
            print(f"❌ File not found: {stl_path}")
            sys.exit(1)

    # Resolve to absolute (relative paths break 3MF post-processing)
    stl_path = os.path.abspath(stl_path)
    if output_path:
        output_path = os.path.abspath(output_path)

    slicer = find_slicer()
    profiles_dir = find_profiles_dir()

    print(f"🔧 Slicer: {os.path.basename(slicer)}")
    print(f"🖨️ Printer: {printer_model} ({nozzle}mm nozzle)")
    print(f"📐 Quality: {quality} ({QUALITY_MAP.get(quality, quality)})")
    print(f"🧵 Filament: {filament}")

    # Resolve profile names
    machine_name, process_name, filament_name = resolve_profiles(
        printer_model, nozzle, quality, filament, profiles_dir)

    print(f"\n📋 Profiles:")
    print(f"   Machine:  {machine_name}")
    print(f"   Process:  {process_name}")
    print(f"   Filament: {filament_name}")

    # Build merged profiles
    tmpdir = tempfile.mkdtemp(prefix="bambu_slice_")

    try:
        # Machine
        machine = load_profile(f"{machine_name}.json", "machine", profiles_dir)
        machine = fix_machine_profile(machine, machine_name=machine_name)
        machine_path = os.path.join(tmpdir, "machine.json")
        with open(machine_path, "w") as f:
            json.dump(machine, f, indent=2)

        # Process
        process = load_profile(f"{process_name}.json", "process", profiles_dir)
        process = fix_process_profile(process)
        process_path = os.path.join(tmpdir, "process.json")
        with open(process_path, "w") as f:
            json.dump(process, f, indent=2)

        # Filament
        fil = load_profile(f"{filament_name}.json", "filament", profiles_dir)
        fil = fix_filament_profile(fil)
        fil_path = os.path.join(tmpdir, "filament.json")
        with open(fil_path, "w") as f:
            json.dump(fil, f, indent=2)

        # Determine number of extruders
        nozzle_dia = machine.get("nozzle_diameter", ["0.4"])
        num_extruders = len(nozzle_dia) if isinstance(nozzle_dia, list) else 1
        fil_list = ";".join([fil_path] * num_extruders)

        # Output path
        if not output_path:
            base = os.path.splitext(os.path.basename(stl_path))[0]
            output_path = os.path.join(os.path.dirname(stl_path) or ".", f"{base}_sliced.3mf")

        # Build command
        cmd = [slicer,
               "--load-settings", f"{machine_path};{process_path}",
               "--load-filaments", fil_list,
               "--slice", "0",
               "--export-3mf", output_path]

        if orient:
            cmd.extend(["--orient", "1"])
        if arrange:
            cmd.extend(["--arrange", "1"])

        cmd.append(stl_path)

        print(f"\n⚙️ Slicing...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        # Filter out harmless OpenGL errors
        stderr_lines = [l for l in result.stderr.split("\n")
                       if l.strip() and "gl_FragColor" not in l
                       and "shader" not in l.lower()
                       and "Unable to load" not in l
                       and "Unable to compile" not in l
                       and "can not get shader" not in l]

        errors = [l for l in stderr_lines if "error" in l.lower() and "calc_exclude" not in l]

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            size = os.path.getsize(output_path)
            size_str = f"{size/1024/1024:.1f}MB" if size > 1024*1024 else f"{size/1024:.0f}KB"
            print(f"\n✅ Sliced successfully!")
            print(f"   📦 Output: {output_path} ({size_str})")

            # Post-process 3MF: fix OrcaSlicer values that BS flags as outdated
            try:
                import zipfile
                _fix_3mf_compat(output_path)
            except Exception as e:
                print(f"   ⚠️ Post-process warning: {e}")

            # Quick 3MF validation
            try:
                import zipfile
                with zipfile.ZipFile(output_path) as z:
                    has_gcode = any("gcode" in n.lower() for n in z.namelist())
                    print(f"   🔧 G-code: {'✅' if has_gcode else '❌ missing'}")
            except:
                pass

            return output_path
        else:
            print(f"\n❌ Slicing failed")
            for line in errors:
                print(f"   {line}")
            if result.stdout.strip():
                print(f"\nStdout: {result.stdout[-500:]}")
            sys.exit(1)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

def list_profiles():
    """List available profiles."""
    profiles_dir = find_profiles_dir()

    print("🖨️ Supported Printers:")
    for name, info in PRINTER_PROFILES.items():
        machine = info["machine"]
        nozzles = []
        for n in ["0.2", "0.4", "0.6", "0.8"]:
            if os.path.exists(os.path.join(profiles_dir, "machine", f"{machine} {n} nozzle.json")):
                nozzles.append(n)
        print(f"  {name:8s} — nozzles: {', '.join(nozzles) or 'default'}")

    print(f"\n📐 Quality Presets:")
    for name, layer in QUALITY_MAP.items():
        print(f"  {name:10s} → {layer} layer height")

    print(f"\n🧵 Filaments (sample):")
    fils = glob.glob(os.path.join(profiles_dir, "filament", "Bambu PLA*.json"))
    seen = set()
    for f in sorted(fils)[:10]:
        base = os.path.splitext(os.path.basename(f))[0]
        # Extract filament name (before @)
        name = base.split("@")[0].strip()
        if name not in seen:
            print(f"  {name}")
            seen.add(name)

def main():
    parser = argparse.ArgumentParser(description="Bambu Lab CLI Slicer")
    parser.add_argument("model", nargs="?", help="STL/OBJ file to slice")
    parser.add_argument("--output", "-o", help="Output 3MF path")
    parser.add_argument("--printer", default=None,
                       help="Printer model (default: auto-detect from printer)")
    parser.add_argument("--nozzle", default=None, help="Nozzle size (default: auto-detect)")
    parser.add_argument("--no-detect", action="store_true",
                       help="Skip printer auto-detection")
    parser.add_argument("--quality", default="standard",
                       choices=["draft", "standard", "fine", "extra"],
                       help="Print quality (default: standard)")
    parser.add_argument("--filament", default="Bambu PLA Basic",
                       help="Filament name (default: Bambu PLA Basic)")
    parser.add_argument("--orient", action="store_true", help="Auto-orient model")
    parser.add_argument("--arrange", action="store_true", help="Auto-arrange on plate")
    parser.add_argument("--list-profiles", action="store_true", help="List available profiles")

    args = parser.parse_args()

    if args.list_profiles:
        list_profiles()
        return

    if not args.model:
        parser.print_help()
        sys.exit(1)

    # Auto-detect printer info
    printer = args.printer
    nozzle = args.nozzle
    filament = args.filament

    if not args.no_detect and (not printer or not nozzle):
        print("🔍 Detecting printer info...")
        info = detect_printer_info()
        if info:
            if not printer:
                printer = info.get("model") or _cfg.get("model", "H2D")
                print(f"   🖨️ Printer: {printer}")
            if not nozzle:
                nd = info.get("nozzle_diameter")
                if nd:
                    # Normalize: could be float, string, or list
                    if isinstance(nd, list):
                        nd = nd[0]
                    nozzle = str(nd)
                    print(f"   🔧 Nozzle: {nozzle}mm")
            # Show AMS filaments
            fils = info.get("filaments", [])
            if fils:
                print(f"   🧵 AMS ({len(fils)} slots):")
                for f in fils:
                    ftype = f.get("type", "")
                    fname = f.get("name", "")
                    color = f.get("color", "")
                    if ftype or fname:
                        print(f"      Slot {f.get('slot','?')}: {ftype} {fname} #{color}")
        else:
            print("   ⚠️ Could not reach printer, using config defaults")

    printer = printer or _cfg.get("model", "H2D")
    nozzle = nozzle or "0.4"

    slice_model(
        stl_path=args.model,
        output_path=args.output,
        printer_model=printer,
        nozzle=nozzle,
        quality=args.quality,
        filament=filament,
        orient=args.orient,
        arrange=args.arrange,
    )

if __name__ == "__main__":
    main()
