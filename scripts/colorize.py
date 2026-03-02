#!/usr/bin/env python3
"""
🎨 Multi-Color Converter — GLB to OBJ+MTL for Bambu Lab AMS

Converts AI-generated GLB models (with textures) to OBJ+MTL format
with color-quantized materials matching your AMS filament colors.

Requires: Blender 4.0+ (brew install --cask blender)

Usage:
  python3 colorize.py model.glb --colors "#FFFF00,#000000,#FF0000,#FFFFFF" --height 80
  python3 colorize.py model.glb --colors "#FFFF00,#000000" --subdivide 2 --min_island 80
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile

_skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Blender paths (macOS / Linux)
BLENDER_PATHS = [
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "blender",  # PATH fallback
]

# Embedded Blender script for color quantization
BLENDER_SCRIPT = r'''
import bpy
import bmesh
import numpy as np
import sys
import os
import colorsys
from collections import defaultdict

argv = sys.argv
argv = argv[argv.index("--") + 1:]

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--colors", required=True, help="Comma-separated hex colors")
parser.add_argument("--height", type=float, default=0, help="Target height in mm (0=no scale)")
parser.add_argument("--subdivide", type=int, default=1, help="Subdivision level (0-2)")
parser.add_argument("--min_island", type=int, default=50, help="Min faces per color island")
parser.add_argument("--cleanup", type=int, default=3, help="Neighbor cleanup rounds")
args = parser.parse_args(argv)

# Parse colors
def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

def rgb_to_hsv(r, g, b):
    return colorsys.rgb_to_hsv(r, g, b)

filament_colors = [hex_to_rgb(c) for c in args.colors.split(",")]
filament_hsv = [rgb_to_hsv(*c) for c in filament_colors]
n_colors = len(filament_colors)

# Clear scene
bpy.ops.wm.read_factory_settings(use_empty=True)

# Import model
ext = os.path.splitext(args.input)[1].lower()
if ext in ['.glb', '.gltf']:
    bpy.ops.import_scene.gltf(filepath=args.input)
elif ext == '.obj':
    bpy.ops.wm.obj_import(filepath=args.input)
elif ext == '.fbx':
    bpy.ops.import_scene.fbx(filepath=args.input)
elif ext == '.stl':
    bpy.ops.wm.stl_import(filepath=args.input)
else:
    print(f"ERROR: Unsupported format: {ext}")
    sys.exit(1)

# Join all mesh objects
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    print("ERROR: No mesh objects found")
    sys.exit(1)

bpy.context.view_layer.objects.active = meshes[0]
for o in meshes:
    o.select_set(True)
if len(meshes) > 1:
    bpy.ops.object.join()

obj = bpy.context.active_object

# Scale to target height
if args.height > 0:
    bbox = [obj.matrix_world @ v.co for v in obj.data.vertices]
    z_min = min(v.z for v in bbox)
    z_max = max(v.z for v in bbox)
    current_h = (z_max - z_min) * 1000  # to mm
    if current_h > 0:
        scale = args.height / current_h
        obj.scale *= scale
        bpy.ops.object.transform_apply(scale=True)
        # Drop to floor
        bbox2 = [obj.matrix_world @ v.co for v in obj.data.vertices]
        z_min2 = min(v.z for v in bbox2)
        obj.location.z -= z_min2

# Subdivide for color precision
if args.subdivide > 0:
    mod = obj.modifiers.new("Subdivide", 'SUBSURF')
    mod.levels = args.subdivide
    mod.render_levels = args.subdivide
    bpy.ops.object.modifier_apply(modifier=mod.name)

print(f"Mesh: {len(obj.data.polygons)} faces, {len(obj.data.vertices)} verts")

# Get texture image
image = None
for mat in obj.data.materials:
    if mat and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                image = node.image
                break
    if image:
        break

if not image:
    print("WARNING: No texture found — assigning all faces to first color")
    # Single color fallback
    mat = bpy.data.materials.new("Color_01")
    r, g, b = filament_colors[0]
    mat.diffuse_color = (r, g, b, 1.0)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.material_index = 0
else:
    # Quantize texture pixels to nearest filament color (HSV, hue-priority)
    pixels = np.array(image.pixels[:]).reshape(-1, 4)[:, :3]  # RGB only
    w, h = image.size

    def nearest_color_idx(r, g, b):
        hsv = rgb_to_hsv(r, g, b)
        best = 0
        best_dist = float('inf')
        for i, fhsv in enumerate(filament_hsv):
            # Hue is circular, weight it heavily
            dh = min(abs(hsv[0] - fhsv[0]), 1.0 - abs(hsv[0] - fhsv[0]))
            ds = abs(hsv[1] - fhsv[1])
            dv = abs(hsv[2] - fhsv[2])
            dist = dh * 3.0 + ds * 1.0 + dv * 0.5
            if dist < best_dist:
                best_dist = dist
                best = i
        return best

    # Pre-quantize full texture
    quantized = np.zeros(len(pixels), dtype=np.int32)
    for i in range(len(pixels)):
        quantized[i] = nearest_color_idx(*pixels[i])

    # UV sample each face (multi-point voting)
    uv_layer = obj.data.uv_layers.active
    if not uv_layer:
        print("WARNING: No UV layer — assigning first color")
        mat = bpy.data.materials.new("Color_01")
        r, g, b = filament_colors[0]
        mat.diffuse_color = (r, g, b, 1.0)
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    else:
        # Create materials
        obj.data.materials.clear()
        for i in range(n_colors):
            mat = bpy.data.materials.new(f"Color_{i+1:02d}")
            r, g, b = filament_colors[i]
            mat.diffuse_color = (r, g, b, 1.0)
            obj.data.materials.append(mat)

        # Assign faces by UV sampling
        face_colors = np.zeros(len(obj.data.polygons), dtype=np.int32)
        for fi, poly in enumerate(obj.data.polygons):
            votes = defaultdict(int)
            for li in poly.loop_indices:
                uv = uv_layer.data[li].uv
                px = int(uv.x * (w - 1)) % w
                py = int(uv.y * (h - 1)) % h
                idx = py * w + px
                if 0 <= idx < len(quantized):
                    votes[quantized[idx]] += 1
            face_colors[fi] = max(votes, key=votes.get) if votes else 0
            poly.material_index = face_colors[fi]

        # Neighbor cleanup
        edge_faces = defaultdict(list)
        for fi, poly in enumerate(obj.data.polygons):
            for ek in poly.edge_keys:
                edge_faces[ek].append(fi)

        for round_i in range(args.cleanup):
            changed = 0
            for fi, poly in enumerate(obj.data.polygons):
                neighbors = []
                for ek in poly.edge_keys:
                    for nf in edge_faces[ek]:
                        if nf != fi:
                            neighbors.append(face_colors[nf])
                if neighbors:
                    votes = defaultdict(int)
                    for nc in neighbors:
                        votes[nc] += 1
                    dominant = max(votes, key=votes.get)
                    if votes[dominant] / len(neighbors) > 0.6 and dominant != face_colors[fi]:
                        face_colors[fi] = dominant
                        poly.material_index = dominant
                        changed += 1
            print(f"  Cleanup round {round_i+1}: {changed} faces changed")
            if changed == 0:
                break

        # Island elimination
        if args.min_island > 0:
            from collections import deque
            visited = set()
            islands = []
            for fi in range(len(face_colors)):
                if fi in visited:
                    continue
                color = face_colors[fi]
                queue = deque([fi])
                island = []
                while queue:
                    f = queue.popleft()
                    if f in visited:
                        continue
                    visited.add(f)
                    if face_colors[f] == color:
                        island.append(f)
                        poly = obj.data.polygons[f]
                        for ek in poly.edge_keys:
                            for nf in edge_faces[ek]:
                                if nf not in visited and face_colors[nf] == color:
                                    queue.append(nf)
                if len(island) < args.min_island:
                    islands.append((island, color))

            merged = 0
            for island, color in islands:
                neighbor_colors = defaultdict(int)
                for fi in island:
                    poly = obj.data.polygons[fi]
                    for ek in poly.edge_keys:
                        for nf in edge_faces[ek]:
                            if face_colors[nf] != color:
                                neighbor_colors[face_colors[nf]] += 1
                if neighbor_colors:
                    new_color = max(neighbor_colors, key=neighbor_colors.get)
                    for fi in island:
                        face_colors[fi] = new_color
                        obj.data.polygons[fi].material_index = new_color
                        merged += 1
            print(f"  Island cleanup: {merged} faces merged (threshold: {args.min_island})")

# Export OBJ
out_path = args.output
bpy.ops.wm.obj_export(
    filepath=out_path,
    export_selected_objects=False,
    export_materials=True,
    export_normals=True,
    export_uv=True
)

# Count faces per material
mat_counts = defaultdict(int)
for poly in obj.data.polygons:
    mat_counts[poly.material_index] += 1
print(f"\n✅ Export complete: {out_path}")
print(f"   Materials: {len(obj.data.materials)}")
for i, mat in enumerate(obj.data.materials):
    pct = mat_counts.get(i, 0) / len(obj.data.polygons) * 100
    print(f"   {mat.name}: {mat_counts.get(i, 0)} faces ({pct:.1f}%)")
print(f"\n📋 Import into Bambu Studio → map each Color_XX to AMS slot")
'''


def find_blender():
    """Find Blender binary."""
    for path in BLENDER_PATHS:
        if os.path.exists(path):
            return path
        # Check PATH
        result = subprocess.run(["which", path], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    return None


def colorize(input_path, output_path, colors, height=0, subdivide=1, min_island=50, cleanup=3):
    """Convert GLB to multi-color OBJ+MTL."""
    blender = find_blender()
    if not blender:
        print("❌ Blender not found.")
        print("   Install: brew install --cask blender")
        return None

    if not os.path.exists(input_path):
        print(f"❌ Input file not found: {input_path}")
        return None

    # Write Blender script to temp file
    script_file = os.path.join(tempfile.gettempdir(), "bambu_colorize.py")
    with open(script_file, "w") as f:
        f.write(BLENDER_SCRIPT)

    cmd = [
        blender, "--background", "--python", script_file, "--",
        "--input", os.path.abspath(input_path),
        "--output", os.path.abspath(output_path),
        "--colors", colors,
        "--height", str(height),
        "--subdivide", str(subdivide),
        "--min_island", str(min_island),
        "--cleanup", str(cleanup),
    ]

    print(f"🎨 Converting to multi-color OBJ ({len(colors.split(','))} colors)...")
    print(f"   Input:  {input_path}")
    print(f"   Output: {output_path}")
    print(f"   Colors: {colors}")
    print(f"   Height: {height}mm, Subdivide: {subdivide}, Min island: {min_island}")
    print()

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        # Filter Blender output for our messages
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line and (line.startswith(('Mesh:', '✅', '📋', '  ')) or 'Cleanup' in line or 'Island' in line or 'WARNING' in line or 'ERROR' in line):
                print(line)

        if result.returncode != 0:
            print(f"\n⚠️ Blender error:")
            for line in result.stderr.split('\n')[-10:]:
                if line.strip():
                    print(f"   {line.strip()}")
            return None

        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"\n📁 Output: {output_path} ({size // 1024} KB)")
            mtl_path = os.path.splitext(output_path)[0] + ".mtl"
            if os.path.exists(mtl_path):
                print(f"📁 MTL:    {mtl_path}")
            return output_path
        else:
            print("❌ Output file not created")
            return None

    except subprocess.TimeoutExpired:
        print("⚠️ Blender timed out (5 min). Model may be too complex.")
        print("   Try --subdivide 0 or simplify the input model.")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="🎨 Convert GLB to multi-color OBJ for Bambu Lab AMS",
        epilog="Output: OBJ+MTL → Import into Bambu Studio → Map colors to AMS slots"
    )
    parser.add_argument("input", help="Input model (GLB/GLTF/OBJ/FBX/STL)")
    parser.add_argument("--output", "-o", help="Output OBJ path (default: input_multicolor.obj)")
    parser.add_argument("--colors", "-c", required=True, help="AMS filament colors (hex, comma-separated). Example: '#FFFF00,#000000,#FF0000,#FFFFFF'")
    parser.add_argument("--height", type=float, default=0, help="Target height in mm (0=keep original)")
    parser.add_argument("--subdivide", type=int, default=1, choices=[0, 1, 2], help="Subdivision level (0=original, 1=recommended, 2=high detail)")
    parser.add_argument("--min_island", type=int, default=50, help="Min faces per color island (small clusters get merged)")
    parser.add_argument("--cleanup", type=int, default=3, help="Neighbor cleanup rounds")

    args = parser.parse_args()

    if not args.output:
        base = os.path.splitext(args.input)[0]
        args.output = f"{base}_multicolor.obj"

    colorize(args.input, args.output, args.colors, args.height, args.subdivide, args.min_island, args.cleanup)


if __name__ == "__main__":
    main()
