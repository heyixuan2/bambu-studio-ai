#!/usr/bin/env python3
"""
🎨 Multi-Color Converter — GLB to OBJ+MTL for Bambu Lab AMS

Pipeline: GLB texture → [Optional AO Delight] → CIELAB nearest-neighbor → Shadow border vote → Texture smoothing → Face sampling → Cleanup → OBJ+MTL

Requires: Blender 4.0+ (brew install --cask blender)

Usage:
  # Recommended (most models):
  python3 scripts/colorize.py model.glb --colors "#FFFF00,#000000,#FF0000,#FFFFFF" --height 80

  # High precision:
  python3 scripts/colorize.py model.glb --colors "#FFFF00,#000000,#FF0000,#FFFFFF" --height 80 \
    --subdivide 3 --min_island 80 --tex_smooth 11 --tex_smooth_passes 8

  # Vinyl toy / cartoon style (less shadow removal needed):
  python3 scripts/colorize.py model.glb --colors "#FFFF00,#000000" --height 50 --delight_floor 0.5
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
parser.add_argument("--tex_smooth", type=int, default=9)
parser.add_argument("--tex_smooth_passes", type=int, default=5)
parser.add_argument("--delight_floor", type=float, default=0.7)
parser.add_argument("--delight_bright", type=float, default=2.0)
parser.add_argument("--no_delight", action="store_true", help="Skip delight entirely")
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

# ─── Pre-subdivide decimation (prevent giant OBJ files) ───
face_count = len(obj.data.polygons)
if face_count > 200000 and args.subdivide >= 2:
    target_ratio = 100000 / face_count
    print(f"\n⚡ Pre-decimation: {face_count:,} faces → ~100K (prevents >500MB output)")
    mod = obj.modifiers.new('Decimate', 'DECIMATE')
    mod.ratio = target_ratio
    bpy.ops.object.modifier_apply(modifier=mod.name)
    print(f"   Result: {len(obj.data.polygons):,} faces")

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

    # ─── Step 1: Mesh-aware AO delighting ───
    # Bake AO map from mesh geometry, then divide texture by AO to remove geometric shadows
    # This knows "dark because of geometry concavity" vs "dark because it's a dark color"
    if getattr(args, 'no_delight', False):
        print(f"\n🔆 Step 1: Delight SKIPPED (--no_delight)")
        delit = pixels.copy()
        effective_floor = 0.01
        ao_pixels = np.ones(len(pixels))  # Dummy AO — no shadow detection
    else:
        dark_filaments = [i for i, c in enumerate(filament_colors) if max(c) < 0.3]
        effective_floor = min(args.delight_floor, 0.3) if dark_filaments else args.delight_floor
        dark_note = " (dark filament detected)" if dark_filaments else ""
        print(f"\n🔆 Step 1: Mesh-aware AO delight{dark_note}")

        # Step 1a: Bake AO map using Blender's Cycles renderer
        ao_image = None
        try:
            bpy.context.scene.render.engine = 'CYCLES'
            bpy.context.scene.cycles.device = 'CPU'
            bpy.context.scene.cycles.samples = 32  # Fast but good enough

            # Create AO bake target image (same size as texture)
            ao_image = bpy.data.images.new("AO_Bake", width=w, height=h, alpha=False)

            # Set up material for AO baking
            mat = obj.data.materials[0]
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            # Add image texture node for AO target
            ao_node = nodes.new('ShaderNodeTexImage')
            ao_node.image = ao_image
            ao_node.name = "AO_Target"
            # Make it the active node (Blender bakes to active image node)
            nodes.active = ao_node

            # Bake AO
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            print(f"   Baking AO map ({w}x{h}, 32 samples)...")
            bpy.ops.object.bake(type='AO', margin=2)

            # Read AO pixels
            ao_pixels = np.array(ao_image.pixels[:]).reshape(-1, 4)[:, 0]  # AO is grayscale, take R channel
            print(f"   AO range: {ao_pixels.min():.3f} - {ao_pixels.max():.3f}")

            # Clean up bake nodes
            nodes.remove(ao_node)

            # Step 1b: Divide texture by AO to recover albedo
            # albedo = texture / max(ao, floor)
            # Where AO is dark (concavity), we brighten; where AO is bright (exposed), minimal change
            ao_clamped = np.clip(ao_pixels, effective_floor, 1.0)
            delit = pixels / ao_clamped[:, np.newaxis]

            # Step 1c: Mild additional brightness/saturation boost for remaining shadows
            r_ch, g_ch, b_ch = delit[:, 0], delit[:, 1], delit[:, 2]
            maxc = np.maximum(np.maximum(r_ch, g_ch), b_ch)
            minc = np.minimum(np.minimum(r_ch, g_ch), b_ch)
            v = maxc
            s = np.where(maxc > 0, (maxc - minc) / (maxc + 1e-10), 0)
            # Gentler boost now that AO is removed (1.3x instead of 2.0x)
            mild_bright = min(args.delight_bright, 1.3)
            v = np.clip(v * mild_bright, 0, 1.0)
            old_v = maxc + 1e-10
            ratio = v / old_v
            delit = delit * ratio[:, np.newaxis]
            delit = np.clip(delit, 0, 1)

            print(f"   ✅ AO-based delight applied ({len(delit)} pixels)")

        except Exception as e:
            print(f"   ⚠️ AO bake failed ({e}), falling back to HSV delight")
            # Fallback: original HSV-based delight
            delit = pixels.copy()
            r_ch, g_ch, b_ch = delit[:, 0], delit[:, 1], delit[:, 2]
            maxc = np.maximum(np.maximum(r_ch, g_ch), b_ch)
            minc = np.minimum(np.minimum(r_ch, g_ch), b_ch)
            v = maxc
            s = np.where(maxc > 0, (maxc - minc) / (maxc + 1e-10), 0)
            v = np.clip(v * args.delight_bright, effective_floor, 1.0)
            s = np.clip(s * args.delight_sat, 0, 1.0)
            old_v = maxc + 1e-10
            ratio = v / old_v
            delit = delit * ratio[:, np.newaxis]
            delit = np.clip(delit, 0, 1)
            print(f"   Fallback delight applied to {len(delit)} pixels")

    # Batch RGB→Lab conversion (vectorized)
    def batch_rgb_to_lab(rgb):
        """Vectorized sRGB→CIELAB for numpy array (N,3)."""
        # Linearize sRGB
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        # Linear RGB → XYZ (D65)
        M = np.array([[0.4124564, 0.3575761, 0.1804375],
                       [0.2126729, 0.7151522, 0.0721750],
                       [0.0193339, 0.1191920, 0.9503041]])
        xyz = linear @ M.T
        # Normalize
        xyz[:, 0] /= 0.95047
        xyz[:, 2] /= 1.08883
        # XYZ → Lab
        mask = xyz > 0.008856
        xyz_f = np.where(mask, xyz ** (1/3), 7.787 * xyz + 16/116)
        L = 116 * xyz_f[:, 1] - 16
        a = 500 * (xyz_f[:, 0] - xyz_f[:, 1])
        b_val = 200 * (xyz_f[:, 1] - xyz_f[:, 2])
        return np.column_stack([L, a, b_val])

    pixel_lab = batch_rgb_to_lab(delit)

    # ─── Step 2: Shadow-aware color mapping ───
    # Shadow pixels take the color of their nearest NON-SHADOW physical neighbor.
    # Non-shadow pixels get normal CIELAB mapping and are NOT modified.
    print(f"\n🎯 Step 2: Shadow-aware color mapping ({n_colors} filament colors)")
    
    filament_lab_np = np.array(filament_lab)
    
    # 2a: Identify shadow pixels using AO map
    ao_threshold = effective_floor + 0.1
    try:
        shadow_mask_flat = ao_pixels < ao_threshold
    except:
        brightness = np.max(pixels, axis=1)
        shadow_mask_flat = brightness < 0.3
    
    shadow_mask = shadow_mask_flat.reshape(h, w)
    shadow_count = int(np.sum(shadow_mask))
    nonshadow_count = len(shadow_mask_flat) - shadow_count
    print(f"   Non-shadow: {nonshadow_count:,} px ({nonshadow_count*100//len(shadow_mask_flat)}%)")
    print(f"   Shadow: {shadow_count:,} px ({shadow_count*100//len(shadow_mask_flat)}%)")
    
    # 2b: Map ALL pixels using CIELAB nearest-neighbor (standard, no chromaticity hack)
    quantized = np.zeros(len(pixel_lab), dtype=np.int32)
    chunk_size = 100000
    for start in range(0, len(pixel_lab), chunk_size):
        end = min(start + chunk_size, len(pixel_lab))
        chunk = pixel_lab[start:end]
        diff = chunk[:, None, :] - filament_lab_np[None, :, :]
        dists = np.sqrt(np.sum(diff ** 2, axis=2))
        quantized[start:end] = np.argmin(dists, axis=1)
    
    # 2c: Shadow pixels → iterative edge erosion (vectorized, no scipy)
    # Shadow regions shrink from edges: border shadow pixels adopt the dominant
    # non-shadow neighbor color. Repeat until all shadows absorbed.
    if 0 < shadow_count < len(shadow_mask_flat) * 0.7:
        quant_2d = quantized.reshape(h, w)
        remaining = shadow_mask.copy()  # True = still shadow
        total_fixed = 0
        
        for iteration in range(100):
            # Pad for neighbor access
            pad_r = np.pad(remaining, 1, mode='constant', constant_values=True)
            pad_q = np.pad(quant_2d, 1, mode='edge')
            
            # For each shadow pixel, count non-shadow neighbor colors
            # Build 8 neighbor arrays (shifted views)
            shifts = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
            
            # Find border shadow pixels: shadow pixels with at least 1 non-shadow neighbor
            has_nonshadow_neighbor = np.zeros((h, w), dtype=bool)
            for dy, dx in shifts:
                has_nonshadow_neighbor |= ~pad_r[1+dy:h+1+dy, 1+dx:w+1+dx]
            
            border = remaining & has_nonshadow_neighbor
            border_count = int(np.sum(border))
            if border_count == 0:
                break
            
            # For border pixels, find dominant non-shadow neighbor color
            by, bx = np.where(border)
            for idx in range(len(by)):
                y, x = int(by[idx]), int(bx[idx])
                votes = {}
                for dy, dx in shifts:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and not remaining[ny, nx]:
                        c = int(quant_2d[ny, nx])
                        votes[c] = votes.get(c, 0) + 1
                if votes:
                    quant_2d[y, x] = max(votes, key=votes.get)
            
            remaining[border] = False
            total_fixed += border_count
            
            if iteration < 3 or iteration % 10 == 0:
                print(f"   Pass {iteration+1}: {border_count} border pixels absorbed")
        
        quantized = quant_2d.reshape(-1)
        unfixed = int(np.sum(remaining))
        print(f"   ✅ {total_fixed:,} shadow pixels fixed in {iteration+1} passes")
        if unfixed > 0:
            print(f"   ⚠️ {unfixed} isolated shadow pixels remain")
    
    # Print final distribution
    for i in range(n_colors):
        count = int(np.sum(quantized == i))
        pct = count / len(quantized) * 100
        if count > 0:
            r, g, b = filament_colors[i]
            print(f"Filament {i+1}: {count} pixels ({pct:.1f}%) — #{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}")

    # ─── Step 3: Texture-space smoothing — vectorized mode filter ───
    print(f"\n🔄 Step 3: Texture smoothing (window={args.tex_smooth}, passes={args.tex_smooth_passes})")
    q_2d = quantized.reshape(h, w)
    half = args.tex_smooth // 2

    for pass_i in range(args.tex_smooth_passes):
        # Pad array for uniform window access
        padded = np.pad(q_2d, half, mode='edge')
        new_q = q_2d.copy()
        changed = 0
        # Process in chunks of rows for memory efficiency
        for y in range(h):
            # Extract all windows for this row at once
            row_windows = np.array([padded[y:y+args.tex_smooth, x:x+args.tex_smooth].flatten()
                                     for x in range(w)])
            # Vectorized bincount per row
            for x in range(w):
                votes = np.bincount(row_windows[x], minlength=n_colors)
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

# Note: Multi-material OBJ files inherently have non-manifold edges at color boundaries.
# This is normal OBJ format behavior and does NOT affect printing.
# Bambu Studio will show a warning but slices correctly.

# ─── Convert to mm (glTF/GLB uses meters) ───
bbox_pre = [obj.matrix_world @ v.co for v in obj.data.vertices]
max_dim_pre = max(max(abs(v.x) for v in bbox_pre), max(abs(v.y) for v in bbox_pre), max(abs(v.z) for v in bbox_pre))
if max_dim_pre < 10:  # Still in meters
    obj.scale *= 1000
    bpy.ops.object.transform_apply(scale=True)
    print(f"📐 Converted to mm for Bambu Studio")

# ─── Export ───
# Ensure .obj extension
if not args.output.lower().endswith('.obj'):
    args.output = args.output + '.obj'

bpy.ops.wm.obj_export(
    filepath=args.output,
    export_selected_objects=False,
    export_materials=True,
    export_normals=True,
    export_uv=True
)

# Fix MTL: Blender doesn't write correct Kd colors from diffuse_color
mtl_path = args.output.rsplit(".", 1)[0] + ".mtl"
if os.path.exists(mtl_path):
    mtl_lines = []
    mtl_lines.append("# Multi-color MTL for Bambu Lab AMS\n")
    for i in range(n_colors):
        mat_name = f"Color_{i+1:02d}"
        r, g, b = filament_colors[i]
        mtl_lines.append(f"newmtl {mat_name}\n")
        mtl_lines.append(f"Kd {r:.6f} {g:.6f} {b:.6f}\n")
        mtl_lines.append(f"Ka 0.000000 0.000000 0.000000\n")
        mtl_lines.append(f"Ks 0.000000 0.000000 0.000000\n")
        mtl_lines.append(f"Ns 0.000000\n")
        mtl_lines.append(f"d 1.000000\n")
        mtl_lines.append(f"illum 1\n")
        mtl_lines.append(f"\n")
    with open(mtl_path, "w") as f:
        f.writelines(mtl_lines)
    print(f"\n📝 MTL rewritten with correct filament colors")

# Ensure OBJ mtllib references the correct MTL filename (basename only)
mtl_basename = os.path.basename(mtl_path)
with open(args.output, "r") as f:
    obj_head = f.read(4096)
if "mtllib " in obj_head:
    import re
    old_ref = re.search(r"mtllib (.+)", obj_head).group(1).strip()
    if old_ref != mtl_basename:
        with open(args.output, "r") as f:
            obj_content = f.read()
        obj_content = obj_content.replace(f"mtllib {old_ref}", f"mtllib {mtl_basename}", 1)
        with open(args.output, "w") as f:
            f.write(obj_content)
        print(f"📝 Fixed mtllib reference: {old_ref} → {mtl_basename}")

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


# ─── Bambu Lab Official Filament Colors ───
import json as _json

def _load_bambu_palette():
    """Load Bambu Lab official filament colors as fallback palette."""
    ref_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "references", "bambu_filament_colors.json")
    if not os.path.exists(ref_path):
        return None
    with open(ref_path) as f:
        data = _json.load(f)
    # Flatten all colors into a unique set
    colors = {}
    for series, palette in data.get("filaments", {}).items():
        for name, hex_code in palette.items():
            if hex_code not in colors.values():
                colors[f"{name} ({series})"] = hex_code
    return colors


def _validate_colors(colors_str):
    """Validate hex color string."""
    import re
    colors = [c.strip() for c in colors_str.split(",")]
    for c in colors:
        if not re.match(r'^#?[0-9A-Fa-f]{6}$', c):
            print(f"❌ Invalid color: '{c}'. Use hex format: #FF0000,#00FF00,#0000FF")
            return None
    return colors_str


def colorize(input_path, output_path, colors, height=0, subdivide=2,
             min_island=50, cleanup=3, tex_smooth=9,
             tex_smooth_passes=5, delight_floor=0.7, delight_bright=2.0,
             delight_sat=1.5, no_delight=False):
    """Convert GLB to multi-color OBJ+MTL using full pipeline."""
    blender = find_blender()
    # Validate colors first
    if not _validate_colors(colors):
        return None

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
    delight_label = "No delight" if no_delight else "AO Delight"
    print(f"   Pipeline: {delight_label} → CIELAB NN → Shadow vote → Tex smooth({tex_smooth}×{tex_smooth_passes}) → Subdivide({subdivide}) → Sample → Clean")
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
        "--tex_smooth", str(tex_smooth),
        "--tex_smooth_passes", str(tex_smooth_passes),
        "--delight_floor", str(delight_floor),
        "--delight_bright", str(delight_bright),
        "--delight_sat", str(delight_sat),
    ]
    if no_delight:
        cmd.append("--no_delight")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line and (line.startswith(('Mesh:', 'Texture:', 'Filament', 'Faces:', 'Non-manifold', 'Repaired', '✅', '📋', '📐', '🔆', '🎯', '🔄', '🧹', '🏝', '🔧', '⚡', '🧩', '  ')) or 'ERROR' in line or 'WARNING' in line or 'Step' in line):
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
        epilog="Pipeline: [AO Delight] → CIELAB NN → Shadow vote → Texture smooth → Face sample → Cleanup → OBJ+MTL"
    )
    parser.add_argument("input", help="Input model (GLB/GLTF/OBJ/FBX/STL)")
    parser.add_argument("--output", "-o", help="Output OBJ path")
    parser.add_argument("--colors", "-c", required=False, help="AMS filament hex colors, comma-separated. Omit to use --palette bambu.")
    parser.add_argument("--palette", choices=["bambu", "custom"], default="bambu", help="Use Bambu Lab official palette")
    parser.add_argument("--height", type=float, default=0, help="Target height mm (0=keep)")
    parser.add_argument("--subdivide", type=int, default=2, choices=[0, 1, 2, 3], help="Subdivision (0=raw, 2=recommended, 3=max)")
    parser.add_argument("--min_island", type=int, default=50, help="Min faces per color island")
    parser.add_argument("--cleanup", type=int, default=3, help="Neighbor cleanup rounds")
    parser.add_argument("--tex_smooth", type=int, default=9, help="Texture smoothing window size")
    parser.add_argument("--tex_smooth_passes", type=int, default=5, help="Texture smoothing passes")
    parser.add_argument("--delight_floor", type=float, default=0.7, help="Min brightness after delight (0-1)")
    parser.add_argument("--delight_bright", type=float, default=2.0, help="Brightness multiplier")
    parser.add_argument("--no_delight", action="store_true", help="Skip delight entirely")
    parser.add_argument("--delight_sat", type=float, default=1.5, help="Saturation multiplier")

    args = parser.parse_args()
    if not args.output:
        args.output = os.path.splitext(args.input)[0] + "_multicolor.obj"

    # Auto-use Bambu Lab palette if no colors specified
    colors = args.colors
    if colors:
        pass  # User provided colors explicitly, use them
    elif args.palette == "bambu" or not colors:
        bambu = _load_bambu_palette()
        if bambu:
            colors = ",".join(bambu.values())
            print(f"🎨 Using Bambu Lab official palette ({len(bambu)} colors)")
        elif not colors:
            print("❌ No --colors provided and Bambu Lab palette not found.")
            print("   Provide colors: --colors '#FF0000,#00FF00,#0000FF'")
            sys.exit(1)
    colorize(args.input, args.output, colors, args.height, args.subdivide,
             args.min_island, args.cleanup, args.tex_smooth,
             args.tex_smooth_passes, args.delight_floor, args.delight_bright,
             args.delight_sat, no_delight=getattr(args, "no_delight", False))


if __name__ == "__main__":
    main()
