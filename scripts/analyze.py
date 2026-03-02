#!/usr/bin/env python3
"""
Bambu Studio AI — 3D Model Analyzer
Analyzes 3D models for printability before sending to printer.

Usage:
    python3 scripts/analyze.py <model_file> [--printer MODEL] [--material PLA] [--render]
    python3 scripts/analyze.py model.stl --printer H2D --material PETG --render

Output: JSON report with issues, warnings, suggestions, and optional rendered views.
"""

import argparse
import json
import math
import os
import sys

# Config loading (same pattern as other scripts)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

def load_config():
    config = {}
    config_path = os.path.join(SKILL_DIR, "config.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    return config

# Build volumes (with 10% safety margin)
BUILD_VOLUMES = {
    "A1 Mini": (162, 162, 162),
    "A1": (230, 230, 230),
    "P1S": (230, 230, 230),
    "P2S": (230, 230, 230),
    "X1C": (230, 230, 230),
    "X1E": (230, 230, 230),
    "H2C": (230, 230, 230),
    "H2S": (306, 288, 306),
    "H2D": (315, 288, 292),
}

# Material properties
MATERIALS = {
    "PLA":  {"min_wall": 1.2, "min_temp": 190, "max_temp": 220, "bed": 60,  "infill_deco": 15, "infill_func": 30, "enclosed": False},
    "PLA+": {"min_wall": 1.2, "min_temp": 200, "max_temp": 230, "bed": 60,  "infill_deco": 15, "infill_func": 30, "enclosed": False},
    "PETG": {"min_wall": 1.2, "min_temp": 220, "max_temp": 250, "bed": 80,  "infill_deco": 20, "infill_func": 40, "enclosed": False},
    "TPU":  {"min_wall": 1.6, "min_temp": 210, "max_temp": 240, "bed": 50,  "infill_deco": 10, "infill_func": 30, "enclosed": False},
    "ABS":  {"min_wall": 1.2, "min_temp": 230, "max_temp": 260, "bed": 100, "infill_deco": 15, "infill_func": 30, "enclosed": True},
    "ASA":  {"min_wall": 1.2, "min_temp": 230, "max_temp": 260, "bed": 100, "infill_deco": 15, "infill_func": 30, "enclosed": True},
    "PA":   {"min_wall": 1.5, "min_temp": 250, "max_temp": 280, "bed": 80,  "infill_deco": 20, "infill_func": 40, "enclosed": True},
    "PC":   {"min_wall": 1.5, "min_temp": 260, "max_temp": 300, "bed": 100, "infill_deco": 20, "infill_func": 40, "enclosed": True},
    "PEEK": {"min_wall": 2.0, "min_temp": 330, "max_temp": 350, "bed": 120, "infill_deco": 25, "infill_func": 50, "enclosed": True},
}

# Printers requiring enclosure
ENCLOSED_PRINTERS = {"P1S", "P2S", "X1C", "X1E", "H2C", "H2S", "H2D"}
HIGH_TEMP_PRINTERS = {"H2C", "H2D"}  # 350°C nozzle


def analyze_mesh(mesh, printer_model, material, purpose="general"):
    """Run all 10 printability checks + geometry analysis."""
    report = {
        "file": None,
        "printer": printer_model,
        "material": material,
        "purpose": purpose,
        "geometry": {},
        "checks": [],
        "issues": [],      # ❌ Must fix
        "warnings": [],    # ⚠️ Should review
        "suggestions": [], # 💡 Optional improvements
        "print_settings": {},
        "score": 0,
    }

    bounds = mesh.bounds
    dims = mesh.extents  # [x, y, z] dimensions in mm
    # Check if model is too complex (may be too large for printer SD card)
    if len(mesh.faces) > 500000:
        report["warnings"].append(
            f"Very high triangle count ({len(mesh.faces):,}). "
            f"Consider simplifying: open in Bambu Studio → right-click → Simplify Model, "
            f"or use: trimesh.simplify_quadric_decimation(mesh, face_count=100000)"
        )
    
    report["geometry"] = {
        "dimensions_mm": [round(d, 2) for d in dims],
        "volume_cm3": round(mesh.volume / 1000, 2),
        "surface_area_cm2": round(mesh.area / 100, 2),
        "triangle_count": len(mesh.faces),
        "is_watertight": mesh.is_watertight,
        "is_manifold": mesh.is_volume,
        "center_of_mass": [round(c, 2) for c in mesh.center_mass],
    }

    mat_props = MATERIALS.get(material, MATERIALS["PLA"])
    build_vol = BUILD_VOLUMES.get(printer_model, (230, 230, 230))
    checks_passed = 0
    total_checks = 10

    # === CHECK 1: Tolerance / Dimensions ===
    check1 = {"name": "Dimensional tolerance", "status": "pass"}
    if any(d < 2.0 for d in dims):
        check1["status"] = "warn"
        report["warnings"].append("Very small dimension detected (<2mm). Ensure tolerance of +0.2mm for mating surfaces.")
    else:
        check1["note"] = "Dimensions OK. Remember +0.2mm tolerance for snap-fit or sliding parts."
        checks_passed += 1
    report["checks"].append(check1)

    # === CHECK 2: Wall Thickness ===
    check2 = {"name": "Wall thickness", "status": "pass", "min_required": mat_props["min_wall"]}
    # Heuristic: check if any dimension is very thin relative to others
    min_dim = min(dims)
    if min_dim < mat_props["min_wall"]:
        check2["status"] = "fail"
        report["issues"].append(f"Minimum dimension ({min_dim:.1f}mm) is below minimum wall thickness ({mat_props['min_wall']}mm) for {material}.")
    else:
        checks_passed += 1
    report["checks"].append(check2)

    # === CHECK 3: Load direction vs layer lines ===
    check3 = {"name": "Load direction analysis", "status": "info"}
    aspect = max(dims) / (min(dims) + 0.001)
    if aspect > 5:
        check3["status"] = "warn"
        report["warnings"].append(f"High aspect ratio ({aspect:.1f}:1). If load-bearing, orient strongest axis along X/Y (not Z) to avoid layer delamination.")
    else:
        check3["note"] = "Aspect ratio OK for standard orientation."
        checks_passed += 1
    report["checks"].append(check3)

    # === CHECK 4: Overhang Detection ===
    check4 = {"name": "Overhang analysis", "status": "pass"}
    face_normals = mesh.face_normals
    # Faces pointing downward (Z component < -cos(45°) = -0.707)
    overhangs = (face_normals[:, 2] < -0.707).sum()
    overhang_pct = round(overhangs / len(face_normals) * 100, 1)
    check4["overhang_faces_pct"] = overhang_pct
    if overhang_pct > 20:
        check4["status"] = "fail"
        report["issues"].append(f"{overhang_pct}% faces exceed 45° overhang. Needs support material or reorientation.")
    elif overhang_pct > 5:
        check4["status"] = "warn"
        report["warnings"].append(f"{overhang_pct}% faces have >45° overhang. Consider tree supports or rotating the model.")
        checks_passed += 1
    else:
        checks_passed += 1
    report["checks"].append(check4)

    # === CHECK 5: Print Orientation ===
    check5 = {"name": "Print orientation", "status": "pass"}
    # Check if model has a flat base
    z_min_faces = (abs(face_normals[:, 2] + 1.0) < 0.1).sum()  # faces pointing straight down
    flat_base_pct = round(z_min_faces / len(face_normals) * 100, 1)
    if flat_base_pct < 1:
        check5["status"] = "warn"
        report["warnings"].append("No clear flat base detected. Model may need rotation for bed adhesion.")
    else:
        check5["note"] = f"Flat base detected ({flat_base_pct}% bottom faces). Good bed adhesion expected."
        checks_passed += 1
    report["checks"].append(check5)

    # === CHECK 5b: Floating Parts Detection ===
    check5b = {"name": "Floating/disconnected parts", "status": "pass"}
    try:
        # trimesh can split mesh into connected components
        bodies = mesh.split(only_watertight=False)
        if len(bodies) > 1:
            sizes = sorted([b.volume for b in bodies], reverse=True)
            check5b["status"] = "fail"
            check5b["components"] = len(bodies)
            report["issues"].append(
                f"Model has {len(bodies)} disconnected parts! "
                f"Floating parts will fall during printing. "
                f"Merge into single mesh or remove small floating pieces. "
                f"Largest part: {sizes[0]:.1f}mm³, smallest: {sizes[-1]:.1f}mm³."
            )
        else:
            check5b["note"] = "Single connected body — no floating parts."
            checks_passed += 1
    except Exception:
        check5b["status"] = "info"
        check5b["note"] = "Could not check connectivity."
        checks_passed += 1
    report["checks"].append(check5b)
    total_checks += 1

    # === CHECK 6: Layer Height ===
    check6 = {"name": "Layer height recommendation", "status": "pass"}
    if min_dim < 10:
        check6["recommended"] = "0.12mm (fine detail)"
        report["suggestions"].append("Small features detected. Use 0.12mm layer height for detail.")
    elif max(dims) > 200:
        check6["recommended"] = "0.28mm (fast, large model)"
        report["suggestions"].append("Large model. Consider 0.28mm layer height to save time.")
    else:
        check6["recommended"] = "0.20mm (default, good balance)"
    checks_passed += 1
    report["checks"].append(check6)

    # === CHECK 7: Infill Recommendation ===
    check7 = {"name": "Infill recommendation", "status": "pass"}
    if purpose == "decorative":
        check7["recommended"] = f"{mat_props['infill_deco']}%"
    elif purpose == "functional":
        check7["recommended"] = f"{mat_props['infill_func']}%"
    else:
        check7["recommended"] = "15-30% (ask user about purpose)"
    checks_passed += 1
    report["checks"].append(check7)

    # === CHECK 8: Wall Count ===
    check8 = {"name": "Wall count", "status": "pass"}
    check8["recommended"] = "≥3 walls (≥4 for functional parts)"
    if purpose == "functional":
        report["suggestions"].append("Functional part: use 4 walls for strength.")
    checks_passed += 1
    report["checks"].append(check8)

    # === CHECK 9: Top Layers ===
    check9 = {"name": "Top layers", "status": "pass"}
    check9["recommended"] = "≥5 top layers for clean surface"
    checks_passed += 1
    report["checks"].append(check9)

    # === CHECK 10: Material Compatibility ===
    check10 = {"name": "Material compatibility", "status": "pass"}
    if mat_props.get("enclosed") and printer_model not in ENCLOSED_PRINTERS:
        check10["status"] = "fail"
        report["issues"].append(f"{material} requires an enclosed printer. {printer_model} is open-frame.")
    elif material in ("PEEK", "PEI", "PPSU") and printer_model not in HIGH_TEMP_PRINTERS:
        check10["status"] = "fail"
        report["issues"].append(f"{material} requires 350°C nozzle. {printer_model} doesn't support it.")
    else:
        check10["note"] = f"{material} is compatible with {printer_model}."
        checks_passed += 1
    report["checks"].append(check10)

    # === MESH QUALITY ===
    if not mesh.is_watertight:
        report["issues"].append("Mesh is NOT watertight. May cause slicing errors. Try mesh repair in Bambu Studio.")
    if not mesh.is_volume:
        report["warnings"].append("Non-manifold geometry detected. Bambu Studio may auto-repair, but review in preview.")

    # === FIT CHECK ===
    for i, (dim, vol) in enumerate(zip(dims, build_vol)):
        axis = ["X", "Y", "Z"][i]
        if dim > vol:
            report["issues"].append(f"Model {axis} dimension ({dim:.1f}mm) exceeds {printer_model} build volume ({vol}mm). Scale down or split.")

    # === PRINT SETTINGS RECOMMENDATION ===
    report["print_settings"] = {
        "layer_height": check6.get("recommended", "0.20mm"),
        "infill": check7.get("recommended", "15-30%"),
        "walls": "≥3" if purpose != "functional" else "≥4",
        "top_layers": "≥5",
        "material": material,
        "nozzle_temp": f"{mat_props['min_temp']}-{mat_props['max_temp']}°C",
        "bed_temp": f"{mat_props['bed']}°C",
        "supports": "needed" if overhang_pct > 10 else "likely not needed",
    }

    # === SCORE ===
    report["score"] = round(checks_passed / total_checks * 10, 1)

    return report


def render_views(mesh, output_dir):
    """Render 4 views of the model for visual inspection."""
    try:
        import trimesh.viewer
        from PIL import Image
        import io

        views = {
            "front": [0, 0, 1],
            "side": [1, 0, 0],
            "top": [0, 0.001, 1],  # near-top
            "iso": [1, 1, 1],
        }

        rendered = []
        scene = mesh.scene()

        for name, direction in views.items():
            try:
                png = scene.save_image(resolution=(800, 600))
                path = os.path.join(output_dir, f"view_{name}.png")
                with open(path, "wb") as f:
                    f.write(png)
                rendered.append(path)
            except Exception:
                pass  # Rendering may not work headless

        return rendered
    except ImportError:
        return []


def repair_mesh(mesh, output_path=None):
    """Attempt to repair non-manifold mesh using trimesh."""
    import trimesh
    
    issues = []
    if not mesh.is_watertight:
        issues.append("not watertight")
    if not mesh.is_volume:
        issues.append("non-manifold edges")
    
    if not issues:
        print("✅ Mesh is clean — no repair needed.")
        return mesh, False
    
    print(f"🔧 Repairing mesh ({', '.join(issues)})...")
    
    # trimesh auto-repair
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fix_winding(mesh)
    trimesh.repair.fix_inversion(mesh)
    trimesh.repair.fill_holes(mesh)
    
    # Remove degenerate faces
    mesh.remove_degenerate_faces()
    mesh.remove_duplicate_faces()
    mesh.remove_unreferenced_vertices()
    
    repaired = mesh.is_watertight and mesh.is_volume
    
    if repaired:
        print(f"✅ Mesh repaired! Watertight: {mesh.is_watertight}, Manifold: {mesh.is_volume}")
    else:
        print(f"⚠️ Partial repair. Watertight: {mesh.is_watertight}, Manifold: {mesh.is_volume}")
        print(f"   For stubborn meshes, try: https://www.formware.co/onlinestlrepair")
        print(f"   Or: Bambu Studio → right-click model → Fix Model")
    
    if output_path:
        mesh.export(output_path)
        print(f"💾 Saved repaired model: {output_path}")
    
    return mesh, True


def format_report(report):
    """Format report as human-readable text."""
    lines = []
    lines.append("=" * 50)
    lines.append("🔍 3D MODEL ANALYSIS REPORT")
    lines.append("=" * 50)
    lines.append("")

    g = report["geometry"]
    lines.append(f"📐 Dimensions: {g['dimensions_mm'][0]} × {g['dimensions_mm'][1]} × {g['dimensions_mm'][2]} mm")
    lines.append(f"📦 Volume: {g['volume_cm3']} cm³")
    lines.append(f"🔺 Triangles: {g['triangle_count']:,}")
    lines.append(f"💧 Watertight: {'✅' if g['is_watertight'] else '❌'}")
    lines.append(f"🖨️ Printer: {report['printer']}")
    lines.append(f"🧵 Material: {report['material']}")
    lines.append("")

    # Score
    score = report["score"]
    emoji = "🟢" if score >= 8 else "🟡" if score >= 6 else "🔴"
    lines.append(f"{emoji} Printability Score: {score}/10")
    lines.append("")

    if report["issues"]:
        lines.append("❌ ISSUES (must fix):")
        for i, issue in enumerate(report["issues"], 1):
            lines.append(f"  {i}. {issue}")
        lines.append("")

    if report["warnings"]:
        lines.append("⚠️ WARNINGS (review):")
        for i, warn in enumerate(report["warnings"], 1):
            lines.append(f"  {i}. {warn}")
        lines.append("")

    if report["suggestions"]:
        lines.append("💡 SUGGESTIONS:")
        for i, sug in enumerate(report["suggestions"], 1):
            lines.append(f"  {i}. {sug}")
        lines.append("")

    ps = report["print_settings"]
    lines.append("⚙️ RECOMMENDED SETTINGS:")
    lines.append(f"  Layer height: {ps['layer_height']}")
    lines.append(f"  Infill: {ps['infill']}")
    lines.append(f"  Walls: {ps['walls']}")
    lines.append(f"  Top layers: {ps['top_layers']}")
    lines.append(f"  Nozzle temp: {ps['nozzle_temp']}")
    lines.append(f"  Bed temp: {ps['bed_temp']}")
    lines.append(f"  Supports: {ps['supports']}")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyze 3D model for printability")
    parser.add_argument("file", help="Path to 3D model (.3mf, .stl, .obj, .step)")
    parser.add_argument("--printer", default=None, help="Printer model (e.g., H2D, A1 Mini)")
    parser.add_argument("--material", default="PLA", help="Material (PLA, PETG, TPU, ABS, etc.)")
    parser.add_argument("--purpose", default="general", choices=["general", "decorative", "functional"],
                        help="Purpose affects infill/wall recommendations")
    parser.add_argument("--render", action="store_true", help="Render preview images")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--repair", action="store_true", help="Auto-repair non-manifold mesh before analysis")
    parser.add_argument("--output-dir", default=".", help="Directory for rendered images")
    args = parser.parse_args()

    # Load config for defaults
    config = load_config()
    printer = args.printer or config.get("model", "A1")
    material = args.material.upper()

    if material not in MATERIALS:
        print(f"⚠️ Unknown material '{material}'. Using PLA defaults.", file=sys.stderr)
        material = "PLA"

    if printer not in BUILD_VOLUMES:
        print(f"⚠️ Unknown printer '{printer}'. Using 230mm³ default volume.", file=sys.stderr)

    # Load mesh
    try:
        import trimesh
    except ImportError:
        print("ERROR: trimesh not installed. Run: pip3 install trimesh", file=sys.stderr)
        sys.exit(1)

    try:
        mesh = trimesh.load(args.file, force="mesh")
    except Exception as e:
        print(f"ERROR: Failed to load '{args.file}': {e}", file=sys.stderr)
        sys.exit(1)

    # Auto-repair if requested or if mesh has issues
    if args.repair or not mesh.is_watertight or not mesh.is_volume:
        if not args.repair and (not mesh.is_watertight or not mesh.is_volume):
            print(f"⚠️ Mesh has issues (watertight={mesh.is_watertight}, manifold={mesh.is_volume})")
            print(f"   Auto-repairing... (use --repair to always repair)")
        repair_path = os.path.splitext(args.file)[0] + "_repaired" + os.path.splitext(args.file)[1]
        mesh, was_repaired = repair_mesh(mesh, repair_path if args.repair else None)
        if was_repaired and args.repair:
            print(f"\n📁 Original: {args.file}")
            print(f"📁 Repaired: {repair_path}\n")

    # Analyze
    report = analyze_mesh(mesh, printer, material, args.purpose)
    report["file"] = args.file

    # Render views
    if args.render:
        rendered = render_views(mesh, args.output_dir)
        report["rendered_views"] = rendered

    # Output
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))


if __name__ == "__main__":
    main()
