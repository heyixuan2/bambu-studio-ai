#!/usr/bin/env python3
"""
🎨 Multi-Color Converter — GLB to OBJ+MTL for Bambu Lab AMS

Pipeline: GLB texture → Delight → CIELAB K-means → Texture smoothing → Face sampling → Cleanup → OBJ+MTL

Requires: Blender 4.0+ (brew install --cask blender)

Usage:
  # Recommended (most models):
  python3 colorize.py model.glb --colors "#FFFF00,#000000,#FF0000,#FFFFFF" --height 80

  # High precision:
  python3 colorize.py model.glb --colors "#FFFF00,#000000,#FF0000,#FFFFFF" --height 80 \
    --subdivide 3 --min_island 80 --tex_smooth 11 --tex_smooth_passes 8

  # Vinyl toy / cartoon style (less shadow removal needed):
  python3 colorize.py model.glb --colors "#FFFF00,#000000" --height 50 --delight_floor 0.5
"""

import os
import sys
import json
import argparse
import subprocess
import tempfile

_skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BLENDER_PATHS = [
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "blender",
]

BLENDER_SCRIPT = r'''
import bpy
import bmesh
import numpy as np
import sys
import os
import colorsys
from collections import defaultdict, deque

argv = sys.argv
argv = argv[argv.index("--") + 1:]

import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--colors", required=True)
parser.add_argument("--height", type=float, default=0)
parser.add_argument("--subdivide", type=int, default=2)
parser.add_argument("--min_island", type=int, default=50)
parser.add_argument("--cleanup", type=int, default=3)
parser.add_argument("--clusters", type=int, default=16)
parser.add_argument("--tex_smooth", type=int, default=9)
parser.add_argument("--tex_smooth_passes", type=int, default=5)
parser.add_argument("--delight_floor", type=float, default=0.7)
parser.add_argument("--delight_bright", type=float, default=2.0)
parser.add_argument("--delight_sat", type=float, default=1.5)
args = parser.parse_args(argv)

# ─── Parse filament colors ───
def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

filament_colors = [hex_to_rgb(c) for c in args.colors.split(",")]
n_colors = len(filament_colors)
print(f"Filament colors: {n_colors}")

# ─── RGB ↔ CIELAB conversion ───
def rgb_to_lab(r, g, b):
    """Convert sRGB [0,1] to CIELAB."""
    # sRGB → linear RGB
    def linearize(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    rl, gl, bl = linearize(r), linearize(g), linearize(b)
    # Linear RGB → XYZ (D65)
    x = rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041
    # XYZ → Lab
    xn, yn, zn = 0.95047, 1.0, 1.08883
    def f(t):
        return t ** (1/3) if t > 0.008856 else 7.787 * t + 16/116
    fx, fy, fz = f(x/xn), f(y/yn), f(z/zn)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    b_val = 200 * (fy - fz)
    return (L, a, b_val)

filament_lab = [rgb_to_lab(*c) for c in filament_colors]

def delta_e(lab1, lab2):
    """CIE76 color difference."""
    return sum((a - b) ** 2 for a, b in zip(lab1, lab2)) ** 0.5

def nearest_filament(lab):
    """Find nearest filament color index by deltaE."""
    best_i = 0
    best_d = float('inf')
    for i, flab in enumerate(filament_lab):
        d = delta_e(lab, flab)
        if d < best_d:
            best_d = d
            best_i = i
    return best_i

# ─── Import model ───
bpy.ops.wm.read_factory_settings(use_empty=True)

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

# ─── Scale to target height ───
if args.height > 0:
    bbox = [obj.matrix_world @ v.co for v in obj.data.vertices]
    z_min = min(v.z for v in bbox)
    z_max = max(v.z for v in bbox)
    current_h = (z_max - z_min) * 1000
    if current_h > 0:
        scale = args.height / current_h
        obj.scale *= scale
        bpy.ops.object.transform_apply(scale=True)
        bbox2 = [obj.matrix_world @ v.co for v in obj.data.vertices]
        z_min2 = min(v.z for v in bbox2)
        obj.location.z -= z_min2

# ─── Subdivide ───
if args.subdivide > 0:
    mod = obj.modifiers.new("Subdivide", 'SUBSURF')
    mod.levels = args.subdivide
    mod.render_levels = args.subdivide
    bpy.ops.object.modifier_apply(modifier=mod.name)

print(f"Mesh: {len(obj.data.polygons)} faces, {len(obj.data.vertices)} verts")

# ─── Get texture ───
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
    print("WARNING: No texture found — single color mode")
    mat = bpy.data.materials.new("Color_01")
    r, g, b = filament_colors[0]
    mat.diffuse_color = (r, g, b, 1.0)
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for poly in obj.data.polygons:
        poly.material_index = 0
else:
    pixels = np.array(image.pixels[:]).reshape(-1, 4)[:, :3]
    w, h = image.size
    print(f"Texture: {w}x{h} ({len(pixels)} pixels)")

    # ─── Step 1: Delight (remove baked shadows) ───
    print(f"\n🔆 Step 1: Delight (floor={args.delight_floor}, bright={args.delight_bright}, sat={args.delight_sat})")
    delit = pixels.copy()
    for i in range(len(delit)):
        r, g, b = delit[i]
        h_val, s, v = colorsys.rgb_to_hsv(r, g, b)
        # Boost brightness and saturation, clamp
        v = min(max(v * args.delight_bright, args.delight_floor), 1.0)
        s = min(s * args.delight_sat, 1.0)
        delit[i] = colorsys.hsv_to_rgb(h_val, s, v)
    print(f"   Delight applied to {len(delit)} pixels")

    # ─── Step 2: CIELAB K-means clustering ───
    print(f"\n🎯 Step 2: K-means clustering ({args.clusters} clusters in CIELAB)")

    # Convert delit pixels to Lab
    pixel_lab = np.zeros((len(delit), 3))
    for i in range(len(delit)):
        pixel_lab[i] = rgb_to_lab(*delit[i])

    # Simple K-means (no sklearn dependency)
    n_clusters = min(args.clusters, len(set(map(tuple, delit.round(2)))))
    # Init centroids: random sample
    rng = np.random.RandomState(42)
    idx = rng.choice(len(pixel_lab), size=n_clusters, replace=False)
    centroids = pixel_lab[idx].copy()

    labels = np.zeros(len(pixel_lab), dtype=np.int32)
    for iteration in range(20):
        # Assign
        for i in range(len(pixel_lab)):
            best_c = 0
            best_d = float('inf')
            for c in range(n_clusters):
                d = sum((pixel_lab[i][j] - centroids[c][j]) ** 2 for j in range(3))
                if d < best_d:
                    best_d = d
                    best_c = c
            labels[i] = best_c
        # Update centroids
        new_centroids = np.zeros_like(centroids)
        counts = np.zeros(n_clusters)
        for i in range(len(pixel_lab)):
            new_centroids[labels[i]] += pixel_lab[i]
            counts[labels[i]] += 1
        changed = 0
        for c in range(n_clusters):
            if counts[c] > 0:
                new_c = new_centroids[c] / counts[c]
                if sum((new_c[j] - centroids[c][j]) ** 2 for j in range(3)) > 0.01:
                    changed += 1
                centroids[c] = new_c
        if changed == 0:
            break
    print(f"   K-means converged in {iteration+1} iterations")

    # Map each cluster to nearest filament
    cluster_to_filament = {}
    for c in range(n_clusters):
        cluster_to_filament[c] = nearest_filament(tuple(centroids[c]))

    # Quantize: pixel → cluster → filament
    quantized = np.array([cluster_to_filament[l] for l in labels], dtype=np.int32)

    # Count per filament
    for fi in range(n_colors):
        count = np.sum(quantized == fi)
        pct = count / len(quantized) * 100
        print(f"   Filament {fi+1}: {count} pixels ({pct:.1f}%)")

    # ─── Step 3: Texture-space smoothing (mode filter) ───
    print(f"\n🔄 Step 3: Texture smoothing (window={args.tex_smooth}, passes={args.tex_smooth_passes})")
    q_2d = quantized.reshape(h, w)
    half = args.tex_smooth // 2

    for pass_i in range(args.tex_smooth_passes):
        new_q = q_2d.copy()
        changed = 0
        for y in range(h):
            for x in range(w):
                y0, y1 = max(0, y - half), min(h, y + half + 1)
                x0, x1 = max(0, x - half), min(w, x + half + 1)
                window = q_2d[y0:y1, x0:x1].flatten()
                votes = np.bincount(window, minlength=n_colors)
                winner = np.argmax(votes)
                if winner != q_2d[y, x]:
                    new_q[y, x] = winner
                    changed += 1
        q_2d = new_q
        print(f"   Pass {pass_i+1}: {changed} pixels changed")
        if changed == 0:
            break

    quantized = q_2d.flatten()

    # ─── Step 4: Face-level sampling ───
    print(f"\n📐 Step 4: Face-level UV sampling")

    uv_layer = obj.data.uv_layers.active
    if not uv_layer:
        print("WARNING: No UV layer — single color")
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

        face_colors = np.zeros(len(obj.data.polygons), dtype=np.int32)

        for fi, poly in enumerate(obj.data.polygons):
            votes = defaultdict(int)
            uvs = [uv_layer.data[li].uv for li in poly.loop_indices]

            # Sample at vertices
            for uv in uvs:
                px = int(uv.x * (w - 1)) % w
                py = int(uv.y * (h - 1)) % h
                idx = py * w + px
                if 0 <= idx < len(quantized):
                    votes[quantized[idx]] += 1

            # Sample at centroid (2x weight)
            cx = sum(uv.x for uv in uvs) / len(uvs)
            cy = sum(uv.y for uv in uvs) / len(uvs)
            px = int(cx * (w - 1)) % w
            py = int(cy * (h - 1)) % h
            idx = py * w + px
            if 0 <= idx < len(quantized):
                votes[quantized[idx]] += 2

            # Sample at edge midpoints
            for i_uv in range(len(uvs)):
                j_uv = (i_uv + 1) % len(uvs)
                mx = (uvs[i_uv].x + uvs[j_uv].x) / 2
                my = (uvs[i_uv].y + uvs[j_uv].y) / 2
                px = int(mx * (w - 1)) % w
                py = int(my * (h - 1)) % h
                idx = py * w + px
                if 0 <= idx < len(quantized):
                    votes[quantized[idx]] += 1

            face_colors[fi] = max(votes, key=votes.get) if votes else 0
            poly.material_index = face_colors[fi]

        # ─── Step 5: Neighbor cleanup ───
        print(f"\n🧹 Step 5: Neighbor cleanup ({args.cleanup} rounds)")
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
            print(f"   Round {round_i+1}: {changed} faces changed")
            if changed == 0:
                break

        # ─── Island elimination ───
        if args.min_island > 0:
            print(f"\n🏝️ Island cleanup (min={args.min_island} faces)")
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
            print(f"   {merged} faces merged from small islands")

# ─── Export ───
bpy.ops.wm.obj_export(
    filepath=args.output,
    export_selected_objects=False,
    export_materials=True,
    export_normals=True,
    export_uv=True
)

mat_counts = defaultdict(int)
for poly in obj.data.polygons:
    mat_counts[poly.material_index] += 1
print(f"\n✅ Export complete: {args.output}")
print(f"   Total faces: {len(obj.data.polygons)}")
print(f"   Materials: {len(obj.data.materials)}")
for i, mat in enumerate(obj.data.materials):
    pct = mat_counts.get(i, 0) / len(obj.data.polygons) * 100
    print(f"   {mat.name}: {mat_counts.get(i, 0)} faces ({pct:.1f}%)")
print(f"\n📋 Next: Import OBJ into Bambu Studio → map each Color_XX to AMS slot")
'''


def find_blender():
    for path in BLENDER_PATHS:
        if os.path.exists(path):
            return path
        result = subprocess.run(["which", path], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    return None


def colorize(input_path, output_path, colors, height=0, subdivide=2,
             min_island=50, cleanup=3, clusters=16, tex_smooth=9,
             tex_smooth_passes=5, delight_floor=0.7, delight_bright=2.0,
             delight_sat=1.5):
    """Convert GLB to multi-color OBJ+MTL using full pipeline."""
    blender = find_blender()
    if not blender:
        print("❌ Blender not found.")
        print("   Install: brew install --cask blender")
        return None

    if not os.path.exists(input_path):
        print(f"❌ Input file not found: {input_path}")
        return None

    script_file = os.path.join(tempfile.gettempdir(), "bambu_colorize.py")
    with open(script_file, "w") as f:
        f.write(BLENDER_SCRIPT)

    n = len(colors.split(','))
    print(f"🎨 Multi-color pipeline ({n} colors)")
    print(f"   Input:    {input_path}")
    print(f"   Output:   {output_path}")
    print(f"   Colors:   {colors}")
    print(f"   Pipeline: Delight → CIELAB K-means({clusters}) → Tex smooth({tex_smooth}×{tex_smooth_passes}) → Subdivide({subdivide}) → Sample → Clean")
    print()

    cmd = [
        blender, "--background", "--python", script_file, "--",
        "--input", os.path.abspath(input_path),
        "--output", os.path.abspath(output_path),
        "--colors", colors,
        "--height", str(height),
        "--subdivide", str(subdivide),
        "--min_island", str(min_island),
        "--cleanup", str(cleanup),
        "--clusters", str(clusters),
        "--tex_smooth", str(tex_smooth),
        "--tex_smooth_passes", str(tex_smooth_passes),
        "--delight_floor", str(delight_floor),
        "--delight_bright", str(delight_bright),
        "--delight_sat", str(delight_sat),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line and (line.startswith(('Mesh:', 'Texture:', 'Filament', '✅', '📋', '📐', '🔆', '🎯', '🔄', '🧹', '🏝', '  ')) or 'ERROR' in line or 'WARNING' in line):
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
        print("⚠️ Timeout (10 min). Try --subdivide 1 or simplify the model.")
        return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="🎨 Multi-color converter for Bambu Lab AMS (GLB → OBJ+MTL)",
        epilog="Pipeline: Delight → CIELAB K-means → Texture smooth → Face sample → Cleanup → OBJ+MTL"
    )
    parser.add_argument("input", help="Input model (GLB/GLTF/OBJ/FBX/STL)")
    parser.add_argument("--output", "-o", help="Output OBJ path")
    parser.add_argument("--colors", "-c", required=True, help="AMS filament hex colors, comma-separated")
    parser.add_argument("--height", type=float, default=0, help="Target height mm (0=keep)")
    parser.add_argument("--subdivide", type=int, default=2, choices=[0, 1, 2, 3], help="Subdivision (0=raw, 2=recommended, 3=max)")
    parser.add_argument("--min_island", type=int, default=50, help="Min faces per color island")
    parser.add_argument("--cleanup", type=int, default=3, help="Neighbor cleanup rounds")
    parser.add_argument("--clusters", type=int, default=16, help="K-means color clusters")
    parser.add_argument("--tex_smooth", type=int, default=9, help="Texture smoothing window size")
    parser.add_argument("--tex_smooth_passes", type=int, default=5, help="Texture smoothing passes")
    parser.add_argument("--delight_floor", type=float, default=0.7, help="Min brightness after delight (0-1)")
    parser.add_argument("--delight_bright", type=float, default=2.0, help="Brightness multiplier")
    parser.add_argument("--delight_sat", type=float, default=1.5, help="Saturation multiplier")

    args = parser.parse_args()
    if not args.output:
        args.output = os.path.splitext(args.input)[0] + "_multicolor.obj"

    colorize(args.input, args.output, args.colors, args.height, args.subdivide,
             args.min_island, args.cleanup, args.clusters, args.tex_smooth,
             args.tex_smooth_passes, args.delight_floor, args.delight_bright,
             args.delight_sat)


if __name__ == "__main__":
    main()
