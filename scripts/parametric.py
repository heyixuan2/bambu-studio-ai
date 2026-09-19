#!/usr/bin/env python3
"""
Parametric 3D Model Generator — CSG modeling via manifold3d

Guarantees watertight, manifold output suitable for FDM printing.
Use for functional/precision parts where exact dimensions matter.

Usage:
  python3 scripts/parametric.py box 30 20 10 -o plate.stl
  python3 scripts/parametric.py cylinder --radius 5 --height 20 -o post.stl
  python3 scripts/parametric.py sphere --radius 10 -o ball.stl
  python3 scripts/parametric.py bracket --width 30 --height 40 --thickness 3 --hole-diameter 3.2
  python3 scripts/parametric.py plate-with-holes --width 60 --depth 40 --thickness 3 --holes 4 --hole-diameter 3.2 --hole-spacing 25
  python3 scripts/parametric.py enclosure --width 60 --depth 40 --height 30 --wall 2 --lid
  python3 scripts/parametric.py csg spec.json -o assembly.stl
"""

import argparse
import json
import os
import sys
import math
import numpy as np
from common import use_utf8_stdio

try:
    import manifold3d as m3d
except ImportError:
    print("ERROR: manifold3d not installed. Run: pip install manifold3d", file=sys.stderr)
    sys.exit(1)

try:
    import trimesh
except ImportError:
    print("ERROR: trimesh not installed. Run: pip install trimesh", file=sys.stderr)
    sys.exit(1)

# Gap per side for parts that slide together (lid rim into its opening). Screw-hole and
# heat-set-insert sizes are in references/manifold-examples.md.
SLIP_FIT_GAP_MM = 0.2


def _manifold_to_trimesh(manifold: m3d.Manifold) -> trimesh.Trimesh:
    """Convert a Manifold to a trimesh object for export."""
    mesh = manifold.to_mesh()
    verts = np.array(mesh.vert_properties[:, :3])
    faces = np.array(mesh.tri_verts)
    return trimesh.Trimesh(vertices=verts, faces=faces)


def _export(manifold: m3d.Manifold, output_path: str) -> str:
    """Export a Manifold to STL (or other trimesh-supported format).

    Refuses to write an empty or invalid solid: a clockwise polygon, a subtraction that removes
    everything, or bad geometry would otherwise produce a 0-triangle file reported as watertight.
    """
    if manifold.status() != m3d.Error.NoError:
        raise SystemExit(f"❌ Invalid geometry ({manifold.status()}). Nothing was written.")
    if manifold.is_empty():
        raise SystemExit("❌ The result is empty (no solid left). Check subtractions and polygon points. "
                         "Nothing was written.")
    t = _manifold_to_trimesh(manifold)
    t.export(output_path)
    vol = manifold.volume()
    sa = manifold.surface_area()
    bb = manifold.bounding_box()
    dims = [bb[i + 3] - bb[i] for i in range(3)]
    print(f"Exported: {os.path.basename(output_path)}")
    print(f"  Dimensions: {dims[0]:.2f} x {dims[1]:.2f} x {dims[2]:.2f} mm")
    print(f"  Volume: {vol:.2f} mm³  |  Surface area: {sa:.2f} mm²")
    print(f"  Triangles: {manifold.num_tri():,}  |  Vertices: {manifold.num_vert():,}")
    print("  Watertight: YES (checked: valid, non-empty manifold)")
    bodies = manifold.decompose() if hasattr(manifold, "decompose") else []
    if len(bodies) > 1:
        print(f"  ⚠️ {len(bodies)} separate bodies — they don't touch. Check translate/rotate "
              f"values unless this is intentional (e.g. enclosure + lid).")
    return output_path


def _default_output(args, fallback_name: str) -> str:
    if hasattr(args, "output") and args.output:
        return args.output
    return fallback_name


# ---------------------------------------------------------------------------
# Primitive Builders
# ---------------------------------------------------------------------------

def cmd_box(args):
    """Create a box / rectangular prism."""
    m = m3d.Manifold.cube([args.width, args.depth, args.height])
    if args.center:
        m = m.translate([-args.width / 2, -args.depth / 2, -args.height / 2])
    return _export(m, _default_output(args, "box.stl"))


def cmd_cylinder(args):
    """Create a cylinder (optionally a cone with --radius-top)."""
    r_top = args.radius_top if args.radius_top is not None else args.radius
    segments = args.segments or 0
    if segments:
        m3d.set_circular_segments(segments)
    m = m3d.Manifold.cylinder(args.height, args.radius, r_top)
    if args.center:
        m = m.translate([0, 0, -args.height / 2])
    return _export(m, _default_output(args, "cylinder.stl"))


def cmd_sphere(args):
    """Create a sphere."""
    segments = args.segments or 0
    if segments:
        m3d.set_circular_segments(segments)
    m = m3d.Manifold.sphere(args.radius)
    return _export(m, _default_output(args, "sphere.stl"))


def cmd_extrude(args):
    """Extrude a 2D polygon (JSON array of [x,y] points) into 3D."""
    if args.polygon_file:
        with open(args.polygon_file, encoding="utf-8") as f:
            points = json.load(f)
    else:
        points = json.loads(args.polygon)
    # NonZero fill: a clockwise outline is still a solid (the default Positive rule drops it).
    cs = m3d.CrossSection([points], m3d.FillRule.NonZero)
    m = m3d.Manifold.extrude(cs, args.height)
    return _export(m, _default_output(args, "extrude.stl"))


# ---------------------------------------------------------------------------
# High-Level Part Helpers
# ---------------------------------------------------------------------------

def cmd_bracket(args):
    """L-bracket: a base arm on the build plate and an upright arm, optional holes and fillet.

    X = width, base arm runs along +Y (length --depth), upright rises along +Z (--height).
    """
    w, h, t = args.width, args.height, args.thickness
    d = args.depth or h
    if d <= t or h <= t:
        raise SystemExit("❌ --height and --depth must be larger than --thickness")

    base = m3d.Manifold.cube([w, d, t])
    upright = m3d.Manifold.cube([w, t, h])
    bracket = base + upright

    if args.fillet > 0:
        # Fill the inner corner: a square block minus a cylinder leaves a concave fillet.
        r = min(args.fillet, d - t, h - t)
        block = m3d.Manifold.cube([w, r, r]).translate([0, t, t])
        cyl = m3d.Manifold.cylinder(w, r, r).rotate([0, 90, 0]).translate([0, t + r, t + r])
        bracket = bracket + (block - cyl)

    if args.hole_diameter > 0:
        hole_r = args.hole_diameter / 2
        # Base arm: vertical hole (along Z), centred on the part of the arm beyond the upright
        base_hole = m3d.Manifold.cylinder(t + 1, hole_r).translate([w / 2, t + (d - t) / 2, -0.5])
        # Upright arm: horizontal hole (along Y), centred on the part above the base
        # rotate(-90° about X) turns the cylinder's +Z axis into +Y
        upright_hole = (m3d.Manifold.cylinder(t + 1, hole_r).rotate([-90, 0, 0])
                        .translate([w / 2, -0.5, t + (h - t) / 2]))
        bracket = bracket - base_hole - upright_hole

    return _export(bracket, _default_output(args, "bracket.stl"))


def hole_positions(width, depth, n_holes, spacing):
    """Hole centres for plate-with-holes, all centred on the plate.

    1 hole: the centre. 2: a row along the width, `spacing` apart. 4: a square with side
    `spacing`. Any other count: a bolt circle where neighbouring holes are `spacing` apart.
    """
    cx, cy = width / 2, depth / 2
    if n_holes == 1:
        return [(cx, cy)]
    if n_holes == 2:
        return [(cx - spacing / 2, cy), (cx + spacing / 2, cy)]
    if n_holes == 4:
        h = spacing / 2
        return [(cx - h, cy - h), (cx + h, cy - h), (cx - h, cy + h), (cx + h, cy + h)]
    radius = spacing / (2 * math.sin(math.pi / n_holes))
    return [(cx + radius * math.cos(2 * math.pi * i / n_holes),
             cy + radius * math.sin(2 * math.pi * i / n_holes)) for i in range(n_holes)]


def cmd_plate_with_holes(args):
    """Rectangular plate with mounting holes (see hole_positions for the layout)."""
    if args.holes < 1:
        raise SystemExit("❌ --holes must be at least 1")
    plate = m3d.Manifold.cube([args.width, args.depth, args.thickness])
    hole_r = args.hole_diameter / 2
    edge = hole_r + 1.0  # keep at least 1 mm of material between a hole and the plate edge
    positions = hole_positions(args.width, args.depth, args.holes, args.hole_spacing)
    for x, y in positions:
        if not (edge <= x <= args.width - edge and edge <= y <= args.depth - edge):
            raise SystemExit(f"❌ A hole at ({x:.1f}, {y:.1f}) would cut the plate edge. "
                             "Reduce --hole-spacing or enlarge the plate.")
    for x, y in positions:
        hole = m3d.Manifold.cylinder(args.thickness + 1, hole_r, hole_r, 64).translate([x, y, -0.5])
        plate = plate - hole

    return _export(plate, _default_output(args, "plate.stl"))


def cmd_enclosure(args):
    """Rectangular enclosure (box with hollow interior), optionally with a lid."""
    w, d, h, wall = args.width, args.depth, args.height, args.wall

    outer = m3d.Manifold.cube([w, d, h])
    inner = m3d.Manifold.cube([w - 2 * wall, d - 2 * wall, h - wall])
    inner = inner.translate([wall, wall, wall])
    body = outer - inner

    out_path = _default_output(args, "enclosure.stl")

    if args.lid:
        # Lid printed flat side down, with a rim on top that plugs into the opening when the lid
        # is flipped over: the rim's outside is the opening minus a slip-fit gap on each side.
        gap = SLIP_FIT_GAP_MM
        rim_h = min(3.0, h - wall - 1.0)
        rim_w, rim_d = w - 2 * wall - 2 * gap, d - 2 * wall - 2 * gap
        if rim_h <= 0 or rim_w <= 2 * wall or rim_d <= 2 * wall:
            raise SystemExit("❌ The enclosure is too small for a plug-in lid; drop --lid or make it larger")
        plate = m3d.Manifold.cube([w, d, wall])
        rim = (m3d.Manifold.cube([rim_w, rim_d, rim_h])
               - m3d.Manifold.cube([rim_w - 2 * wall, rim_d - 2 * wall, rim_h]).translate([wall, wall, 0]))
        lid = plate + rim.translate([wall + gap, wall + gap, wall])
        # Beside the body on the build plate (not above it, where it would print in mid-air)
        lid = lid.translate([w + 5, 0, 0])
        return _export(body + lid, out_path)

    return _export(body, out_path)


# ---------------------------------------------------------------------------
# CSG from JSON Spec
# ---------------------------------------------------------------------------

def _build_primitive(op: dict) -> m3d.Manifold:
    """Build a single primitive from a JSON op dict."""
    t = op["type"]
    # Round primitives: "segments" sets the polygon count (default 0 = manifold3d's
    # auto, which is coarse: a 4.2 mm hole gets 16 sides and prints ~0.1 mm undersize).
    segments = int(op.get("segments", 0))
    if t == "cube":
        m = m3d.Manifold.cube(op["size"])
    elif t == "cylinder":
        r_top = op.get("radius_top", op.get("radius", 1))
        m = m3d.Manifold.cylinder(op["height"], op["radius"], r_top, segments)
    elif t == "sphere":
        m = m3d.Manifold.sphere(op["radius"], segments)
    elif t == "extrude":
        cs = m3d.CrossSection([op["polygon"]], m3d.FillRule.NonZero)
        m = m3d.Manifold.extrude(cs, op["height"])
    elif t == "revolve":
        cs = m3d.CrossSection([op["polygon"]], m3d.FillRule.NonZero)
        m = m3d.Manifold.revolve(cs, op.get("segments", 0))
    else:
        raise ValueError(f"Unknown primitive type: {t}")

    # Order: scale → rotate → translate, all about the primitive's own origin.
    # (Rotating after translating would swing the shape around the world origin.)
    if "scale" in op:
        s = op["scale"]
        if isinstance(s, (int, float)):
            s = [s, s, s]
        m = m.scale(s)
    if "rotate" in op:
        m = m.rotate(op["rotate"])
    if "translate" in op:
        m = m.translate(op["translate"])
    return m


def cmd_csg(args):
    """Build a model from a JSON CSG spec file."""
    with open(args.spec_file, encoding="utf-8") as f:
        spec = json.load(f)

    ops = spec.get("ops", spec.get("operations", []))
    registry: dict[str, m3d.Manifold] = {}

    result = None
    for op in ops:
        t = op["type"]

        if t in ("cube", "cylinder", "sphere", "extrude", "revolve"):
            m = _build_primitive(op)
            if "id" in op:
                registry[op["id"]] = m
            result = m

        elif t in ("add", "union"):
            a = registry[op["a"]]
            b = registry[op["b"]]
            result = a + b
            if "id" in op:
                registry[op["id"]] = result

        elif t in ("subtract", "difference"):
            a = registry[op["a"]]
            b = registry[op["b"]]
            result = a - b
            if "id" in op:
                registry[op["id"]] = result

        elif t in ("intersect", "intersection"):
            a = registry[op["a"]]
            b = registry[op["b"]]
            result = a ^ b
            if "id" in op:
                registry[op["id"]] = result

        elif t == "hull":
            parts = [registry[pid] for pid in op["parts"]]
            result = m3d.Manifold.batch_hull(parts)
            if "id" in op:
                registry[op["id"]] = result

        elif t == "compose":
            parts = [registry[pid] for pid in op["parts"]]
            result = m3d.Manifold.compose(parts)
            if "id" in op:
                registry[op["id"]] = result

        else:
            raise ValueError(f"Unknown CSG operation: {t}")

    if result is None:
        print("ERROR: spec produced no geometry", file=sys.stderr)
        sys.exit(1)

    return _export(result, _default_output(args, "csg_output.stl"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="parametric.py",
        description="Parametric 3D model generator (manifold3d). Watertight output guaranteed.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- box ---
    p = sub.add_parser("box", help="Rectangular prism")
    p.add_argument("width", type=float, help="X dimension (mm)")
    p.add_argument("depth", type=float, help="Y dimension (mm)")
    p.add_argument("height", type=float, help="Z dimension (mm)")
    p.add_argument("--center", action="store_true", help="Center at origin")
    p.add_argument("-o", "--output", default="", help="Output file (default: box.stl)")

    # --- cylinder ---
    p = sub.add_parser("cylinder", help="Cylinder or cone")
    p.add_argument("--radius", type=float, required=True, help="Base radius (mm)")
    p.add_argument("--height", type=float, required=True, help="Height (mm)")
    p.add_argument("--radius-top", type=float, default=None, help="Top radius for cone (default: same as radius)")
    p.add_argument("--segments", type=int, default=0, help="Circular segments (0=auto)")
    p.add_argument("--center", action="store_true", help="Center vertically")
    p.add_argument("-o", "--output", default="", help="Output file")

    # --- sphere ---
    p = sub.add_parser("sphere", help="Sphere")
    p.add_argument("--radius", type=float, required=True, help="Radius (mm)")
    p.add_argument("--segments", type=int, default=0, help="Circular segments (0=auto)")
    p.add_argument("-o", "--output", default="", help="Output file")

    # --- extrude ---
    p = sub.add_parser("extrude", help="Extrude a 2D polygon into 3D")
    p.add_argument("--polygon", default=None, help='JSON array of [x,y] points, e.g. "[[0,0],[10,0],[10,5],[0,5]]"')
    p.add_argument("--polygon-file", default=None, help="JSON file containing polygon points")
    p.add_argument("--height", type=float, required=True, help="Extrusion height (mm)")
    p.add_argument("-o", "--output", default="", help="Output file")

    # --- bracket ---
    p = sub.add_parser("bracket", help="L-bracket with optional mounting holes")
    p.add_argument("--width", type=float, required=True, help="Width / length along X (mm)")
    p.add_argument("--height", type=float, required=True, help="Vertical arm height (mm)")
    p.add_argument("--thickness", type=float, required=True, help="Material thickness (mm)")
    p.add_argument("--depth", type=float, default=0, help="Base arm length along Y (mm), default = --height")
    p.add_argument("--hole-diameter", type=float, default=0, help="Mounting hole diameter (mm), 0=no holes")
    p.add_argument("--fillet", type=float, default=0, help="Inner fillet radius (mm), 0=sharp corner")
    p.add_argument("-o", "--output", default="", help="Output file")

    # --- plate-with-holes ---
    p = sub.add_parser("plate-with-holes", help="Rectangular plate with mounting holes")
    p.add_argument("--width", type=float, required=True, help="Plate width X (mm)")
    p.add_argument("--depth", type=float, required=True, help="Plate depth Y (mm)")
    p.add_argument("--thickness", type=float, default=3.0, help="Plate thickness Z (mm)")
    p.add_argument("--holes", type=int, default=4,
                   help="Number of holes: 1 centre, 2 in a row, 4 in a square, others on a bolt circle")
    p.add_argument("--hole-diameter", type=float, default=3.2, help="Hole diameter (mm, default: M3 clearance)")
    p.add_argument("--hole-spacing", type=float, required=True,
                   help="Centre-to-centre distance between neighbouring holes (mm)")
    p.add_argument("-o", "--output", default="", help="Output file")

    # --- enclosure ---
    p = sub.add_parser("enclosure", help="Hollow rectangular enclosure with optional lid")
    p.add_argument("--width", type=float, required=True, help="Outer width X (mm)")
    p.add_argument("--depth", type=float, required=True, help="Outer depth Y (mm)")
    p.add_argument("--height", type=float, required=True, help="Outer height Z (mm)")
    p.add_argument("--wall", type=float, default=2.0, help="Wall thickness (mm)")
    p.add_argument("--lid", action="store_true", help="Generate a matching lid (placed next to the body)")
    p.add_argument("-o", "--output", default="", help="Output file")

    # --- csg ---
    p = sub.add_parser("csg", help="Build from JSON CSG spec file")
    p.add_argument("spec_file", help="Path to JSON spec file")
    p.add_argument("-o", "--output", default="", help="Output file")

    return parser


COMMANDS = {
    "box": cmd_box,
    "cylinder": cmd_cylinder,
    "sphere": cmd_sphere,
    "extrude": cmd_extrude,
    "bracket": cmd_bracket,
    "plate-with-holes": cmd_plate_with_holes,
    "enclosure": cmd_enclosure,
    "csg": cmd_csg,
}


def main():
    parser = build_parser()
    args = parser.parse_args()
    fn = COMMANDS.get(args.command)
    if not fn:
        parser.print_help()
        sys.exit(1)
    out = fn(args)
    print(f"\nDone. Output: {out}")


if __name__ == "__main__":
    use_utf8_stdio()
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Cancelled.")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"❌ Parametric error: {e}", file=sys.stderr)
        sys.exit(1)
