#!/usr/bin/env python3
"""
🎨 Multi-Color Converter v4 — GLB to vertex-color OBJ for Bambu Lab AMS

Pipeline: GLB → Extract texture (pygltflib) → Pixel family classification (HSV)
          → Greedy color-mode selection (≤8 colors) → Per-pixel CIELAB assign
          → Blender vertex color bake → OBJ export

Requires: Blender 4.0+ (brew install --cask blender)
          pygltflib (pip3 install pygltflib)

Usage:
  # Auto-detect colors (recommended):
  python3 scripts/colorize.py model.glb --height 80

  # Limit to 4 colors:
  python3 scripts/colorize.py model.glb --height 80 --max_colors 4

  # Manual colors (legacy mode):
  python3 scripts/colorize.py model.glb --colors "#FFFF00,#000000,#FF0000,#FFFFFF" --height 80
"""

import os
import sys
import io
import json
import argparse
import subprocess
import tempfile
import numpy as np

_skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BLENDER_PATHS = [
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "blender",
]


# ═══════════════════════════════════════════════════════════════
# Color Science Utilities
# ═══════════════════════════════════════════════════════════════

def srgb_to_lab(rgb):
    """Vectorized sRGB [0,1] (N,3) → CIELAB (N,3)."""
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    r, g, b = linear[:, 0], linear[:, 1], linear[:, 2]
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    x /= 0.95047; z /= 1.08883
    def f(t):
        return np.where(t > 0.008856, t ** (1/3), 7.787 * t + 16/116)
    return np.stack([116*f(y)-16, 500*(f(x)-f(y)), 200*(f(y)-f(z))], axis=1)



# ═══════════════════════════════════════════════════════════════
# Step 1: Extract texture from GLB (no Blender needed)
# ═══════════════════════════════════════════════════════════════

def extract_texture(glb_path):
    """Extract base color texture from GLB using pygltflib. Returns PIL Image or None."""
    try:
        import pygltflib
    except ImportError:
        print("   ⚠️ pygltflib not installed, falling back to Blender extraction")
        return None

    from PIL import Image

    glb = pygltflib.GLTF2().load(glb_path)
    for mat in glb.materials:
        if mat.pbrMetallicRoughness and mat.pbrMetallicRoughness.baseColorTexture:
            tex_idx = mat.pbrMetallicRoughness.baseColorTexture.index
            tex = glb.textures[tex_idx]
            image = glb.images[tex.source]

            if image.bufferView is not None:
                bv = glb.bufferViews[image.bufferView]
                data = glb.binary_blob()[bv.byteOffset:bv.byteOffset + bv.byteLength]
            elif image.uri and image.uri.startswith("data:"):
                import base64
                data = base64.b64decode(image.uri.split(",")[1])
            else:
                return None

            return Image.open(io.BytesIO(data)).convert("RGB")
    return None


def extract_texture_blender(glb_path, blender_path):
    """Fallback: extract texture via Blender."""
    from PIL import Image

    out_png = os.path.join(tempfile.gettempdir(), "bambu_extracted_texture.png")
    glb_repr = repr(glb_path)
    out_repr = repr(out_png)
    script = f'''
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={glb_repr})
obj = [o for o in bpy.context.scene.objects if o.type == 'MESH'][0]
for mat in obj.data.materials:
    if mat and mat.use_nodes:
        for link in mat.node_tree.links:
            if link.to_node.type == 'BSDF_PRINCIPLED' and link.to_socket.name == 'Base Color':
                if link.from_node.type == 'TEX_IMAGE':
                    img = link.from_node.image
                    img.filepath_raw = {out_repr}
                    img.file_format = 'PNG'
                    img.save()
                    print("SAVED")
                    break
'''
    script_file = os.path.join(tempfile.gettempdir(), "extract_tex.py")
    with open(script_file, "w") as f:
        f.write(script)

    result = subprocess.run([blender_path, "--background", "--python", script_file],
                           capture_output=True, text=True, timeout=60)
    if os.path.exists(out_png):
        return Image.open(out_png).convert("RGB")
    return None


# ═══════════════════════════════════════════════════════════════
# Step 2: Pixel family classification (vectorized HSV)
# ═══════════════════════════════════════════════════════════════

FAMILY_NAMES = ["black", "dark_gray", "light_gray", "white",
                "red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink"]

# Families that exclude each other during greedy selection
FAMILY_GROUPS = {
    0: [0, 1], 1: [0, 1],       # black ↔ dark_gray
    2: [2, 3], 3: [2, 3],       # light_gray ↔ white
    4: [4, 11], 11: [4, 11],    # red ↔ pink
    # orange and yellow are independent (e.g. SpongeBob yellow body + brown pants)
    7: [7, 8], 8: [7, 8],       # green ↔ cyan
    9: [9, 10], 10: [9, 10],    # blue ↔ purple
}


def classify_pixels(pixels):
    """Classify each pixel into a color family by HSV. Returns int32 array of family IDs."""
    N = len(pixels)
    r, g, b = pixels[:, 0], pixels[:, 1], pixels[:, 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc

    s = np.zeros(N, dtype=np.float64)
    np.divide(delta, maxc, out=s, where=maxc > 0)
    v = maxc

    h = np.zeros(N)
    mr = (maxc == r) & (delta > 0)
    mg = (maxc == g) & (delta > 0)
    mb = (maxc == b) & (delta > 0)
    h[mr] = 60 * (((g[mr] - b[mr]) / delta[mr]) % 6)
    h[mg] = 60 * ((b[mg] - r[mg]) / delta[mg] + 2)
    h[mb] = 60 * ((r[mb] - g[mb]) / delta[mb] + 4)

    pf = np.full(N, 1, dtype=np.int32)  # default: dark_gray
    # Force very dark pixels to achromatic regardless of saturation
    # (at v < 0.1, hue is meaningless noise)
    achro = (s < 0.15) | (v < 0.1)
    pf[achro & (v < 0.2)] = 0                          # black
    pf[achro & (v >= 0.2) & (v < 0.5)] = 1             # dark_gray
    pf[achro & (v >= 0.5) & (v < 0.8)] = 2             # light_gray
    pf[achro & (v >= 0.8)] = 3                          # white
    chro = ~achro
    pf[chro & ((h < 15) | (h >= 345))] = 4             # red
    pf[chro & (h >= 15) & (h < 40)] = 5                # orange
    pf[chro & (h >= 40) & (h < 70)] = 6                # yellow
    pf[chro & (h >= 70) & (h < 160)] = 7               # green
    pf[chro & (h >= 160) & (h < 200)] = 8              # cyan
    pf[chro & (h >= 200) & (h < 260)] = 9              # blue
    pf[chro & (h >= 260) & (h < 310)] = 10             # purple
    pf[chro & (h >= 310) & (h < 345)] = 11             # pink

    return pf


# ═══════════════════════════════════════════════════════════════
# Step 3: Greedy color-mode selection
# ═══════════════════════════════════════════════════════════════

def greedy_select_colors(pixels, pixel_lab, pixel_families, max_colors=8, min_pct=0.001, no_merge=False):
    """
    Greedy select representative colors:
    1. Find largest pixel family
    2. Take median of that family's pixels as representative color
    3. Exclude the family group
    4. Repeat until max_colors or all pixels assigned

    Returns: list of dicts with rgb, lab, family, percentage, etc.
    """
    N = len(pixels)
    selected = []
    excluded_fids = set()

    for rnd in range(max_colors):
        best_fid = -1
        best_count = 0
        for fid in range(12):
            if fid in excluded_fids:
                continue
            c = int(np.sum(pixel_families == fid))
            if c > best_count:
                best_count = c
                best_fid = fid

        if best_fid < 0 or best_count == 0:
            break

        # Floor threshold: skip noise families (<0.1%)
        if best_count / N < 0.001:
            break





        group = [best_fid] if no_merge else FAMILY_GROUPS.get(best_fid, [best_fid])
        group_mask = np.zeros(N, dtype=bool)
        for gf in group:
            group_mask |= (pixel_families == gf)
        total = int(np.sum(group_mask))
        if total == 0:
            break

        # Representative: median in RGB and LAB
        median_rgb = np.median(pixels[group_mask], axis=0)
        median_lab = np.median(pixel_lab[group_mask], axis=0)

        pct = total / N * 100
        group_names = [FAMILY_NAMES[gf] for gf in group]

        selected.append({
            "rgb": median_rgb,
            "lab": median_lab,
            "family": FAMILY_NAMES[best_fid],
            "group_names": group_names,
            "pixel_count": total,
            "percentage": pct,
        })

        for gf in group:
            excluded_fids.add(gf)

    return selected


# ═══════════════════════════════════════════════════════════════
# Step 4: Per-pixel assignment (CIELAB nearest neighbor)
# ═══════════════════════════════════════════════════════════════

def assign_pixels(pixel_lab, selected_colors, pixel_families=None, pixels=None):
    """Assign each pixel to nearest selected color by CIELAB distance.
    
    Achromatic constraint: pixels classified as chromatic (HSV family >= 4)
    cannot be assigned to achromatic selected colors (black/dark_gray/light_gray/white).
    This prevents dark-but-colored shadow pixels from being pulled into black.
    """
    N = len(pixel_lab)
    sel_lab = np.array([sc["lab"] for sc in selected_colors])
    labels = np.zeros(N, dtype=np.int32)
    CHUNK = 500000

    # Identify which selected colors are achromatic
    ACHROMATIC_FAMILIES = {"black", "dark_gray", "light_gray", "white"}
    achro_mask_sel = np.array([sc["family"] in ACHROMATIC_FAMILIES for sc in selected_colors])
    has_achro_constraint = pixel_families is not None and np.any(achro_mask_sel)

    for i in range(0, N, CHUNK):
        chunk = pixel_lab[i:i+CHUNK]
        dist = np.sum((chunk[:, None, :] - sel_lab[None, :, :]) ** 2, axis=2)

        if has_achro_constraint:
            # Chromatic pixels cannot go to achromatic colors
            # EXCEPT very dark pixels (V < 0.2) — they should be allowed to go black
            chunk_families = pixel_families[i:i+CHUNK]
            chunk_pixels = pixels[i:i+CHUNK] if pixels is not None else None
            chromatic_px = chunk_families >= 4
            if chunk_pixels is not None:
                v_values = chunk_pixels.max(axis=1)
                very_dark = v_values < 0.2
                chromatic_px = chromatic_px & ~very_dark  # dark pixels exempt
            dist[np.ix_(chromatic_px, achro_mask_sel)] = 1e12  # block assignment

        labels[i:i+CHUNK] = np.argmin(dist, axis=1)

    return labels


# ═══════════════════════════════════════════════════════════════
# Step 5: Build quantized texture
# ═══════════════════════════════════════════════════════════════


def cleanup_labels(labels_2d, min_island=1000):
    """Remove tiny isolated color regions by majority vote of neighbors.
    
    For each pixel, if its connected component (same-color island) has fewer
    than min_island pixels, replace it with the most common neighbor color.
    """
    from scipy import ndimage
    h, w = labels_2d.shape
    cleaned = labels_2d.copy()
    
    unique_labels = np.unique(labels_2d)
    for lbl in unique_labels:
        mask = labels_2d == lbl
        # Find connected components for this color
        components, n_comp = ndimage.label(mask)
        for comp_id in range(1, n_comp + 1):
            comp_mask = components == comp_id
            if np.sum(comp_mask) >= min_island:
                continue
            # Dilate to find neighbors
            dilated = ndimage.binary_dilation(comp_mask, iterations=1)
            neighbor_mask = dilated & ~comp_mask
            if np.sum(neighbor_mask) == 0:
                continue
            # Most common neighbor label
            neighbor_labels = labels_2d[neighbor_mask]
            counts = np.bincount(neighbor_labels)
            majority = np.argmax(counts)
            cleaned[comp_mask] = majority
    
    return cleaned


def build_quantized_texture(pixels, labels, selected_colors, width, height):
    """Build quantized RGB texture from labels. Returns uint8 (H,W,3)."""
    sel_rgb = np.array([sc["rgb"] for sc in selected_colors])
    return (sel_rgb[labels].reshape(height, width, 3) * 255).astype(np.uint8)


# ═══════════════════════════════════════════════════════════════
# Step 6: Apply to mesh via Blender (vertex color)
# ═══════════════════════════════════════════════════════════════

def apply_vertex_colors(glb_path, quantized_npy_path, output_path, blender_path,
                        height_mm=0, subdivide=1):
    """Load GLB in Blender, sample quantized texture to vertex colors, export OBJ."""

    # Use repr() for safe path embedding
    glb_esc = repr(glb_path)
    npy_esc = repr(quantized_npy_path)
    out_esc = repr(output_path)

    script = f'''
import bpy
import numpy as np
import os

bpy.ops.wm.read_factory_settings(use_empty=True)

ext = os.path.splitext({glb_esc})[1].lower()
if ext in ['.glb', '.gltf']:
    bpy.ops.import_scene.gltf(filepath={glb_esc})
elif ext == '.obj':
    bpy.ops.wm.obj_import(filepath={glb_esc})
elif ext == '.fbx':
    bpy.ops.import_scene.fbx(filepath={glb_esc})
elif ext == '.stl':
    bpy.ops.wm.stl_import(filepath={glb_esc})

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
bpy.context.view_layer.objects.active = meshes[0]
for o in meshes:
    o.select_set(True)
if len(meshes) > 1:
    bpy.ops.object.join()

obj = bpy.context.active_object

# Scale to target height
height_mm = {height_mm}
if height_mm > 0:
    bbox = [obj.matrix_world @ v.co for v in obj.data.vertices]
    z_min = min(v.z for v in bbox)
    z_max = max(v.z for v in bbox)
    current_h = (z_max - z_min) * 1000
    if current_h > 0:
        scale = height_mm / current_h
        obj.scale *= scale
        bpy.ops.object.transform_apply(scale=True)
        bbox2 = [obj.matrix_world @ v.co for v in obj.data.vertices]
        z_min2 = min(v.z for v in bbox2)
        obj.location.z -= z_min2

# Subdivide for vertex color resolution
subdivide = {subdivide}
if subdivide > 0:
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    for _ in range(subdivide):
        bpy.ops.mesh.subdivide(number_cuts=1)
    bpy.ops.object.mode_set(mode='OBJECT')

mesh = obj.data
print(f"Mesh: {{len(mesh.polygons):,}} faces, {{len(mesh.vertices):,}} verts")

# Load quantized texture (uint8 sRGB, Y-flipped for UV)
tex_srgb = np.load({npy_esc})
th, tw = tex_srgb.shape[:2]
tex_f = tex_srgb.astype(np.float32) / 255.0

# sRGB → linear for Blender vertex colors
tex_linear = np.where(tex_f <= 0.04045, tex_f / 12.92, ((tex_f + 0.055) / 1.055) ** 2.4)

# Create vertex color attribute
if "Col" not in mesh.color_attributes:
    mesh.color_attributes.new(name="Col", type='BYTE_COLOR', domain='CORNER')
mesh.color_attributes.active_color = mesh.color_attributes["Col"]
cl = mesh.color_attributes["Col"]
if not mesh.uv_layers.active:
    print("ERROR: No UV mapping found. Colorize requires a textured model (GLB/GLTF).")
    import sys; sys.exit(1)
uv = mesh.uv_layers.active.data

print("Writing vertex colors...")
for fi, poly in enumerate(mesh.polygons):
    for li in poly.loop_indices:
        u, v_coord = uv[li].uv
        px = int(u * tw) % tw
        py = int(v_coord * th) % th
        r, g, b = tex_linear[py, px]
        cl.data[li].color = (r, g, b, 1.0)
    if fi % 300000 == 0 and fi > 0:
        print(f"  {{fi:,}}/{{len(mesh.polygons):,}}")

# Convert to mm if still in meters
bbox_post = [obj.matrix_world @ v.co for v in obj.data.vertices]
max_dim = max(max(abs(v.x) for v in bbox_post), max(abs(v.y) for v in bbox_post), max(abs(v.z) for v in bbox_post))
if max_dim < 10:
    obj.scale *= 1000
    bpy.ops.object.transform_apply(scale=True)
    print("Converted to mm")

# Mesh repair before export
import bmesh
bpy.ops.object.mode_set(mode='OBJECT')
bm = bmesh.new()
bm.from_mesh(obj.data)

# Merge by distance
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
# Remove loose
for v in [v for v in bm.verts if not v.link_faces]:
    bm.verts.remove(v)
# Fix normals
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

# Count non-manifold edges
nm_edges = sum(1 for e in bm.edges if not e.is_manifold)
print(f"Mesh repair: {{nm_edges}} non-manifold edges remaining (from original)")

bm.to_mesh(obj.data)
bm.free()
obj.data.update()

# Export OBJ with vertex colors
bpy.ops.wm.obj_export(
    filepath={out_esc},
    export_selected_objects=True,
    export_colors=True,
    export_materials=False,
    export_uv=False
)
size_mb = os.path.getsize({out_esc}) / 1024 / 1024
print(f"Done: {{size_mb:.1f}}MB")
'''

    script_file = os.path.join(tempfile.gettempdir(), "bambu_vertex_color.py")
    with open(script_file, "w") as f:
        f.write(script)

    print(f"   Blender: subdivide={subdivide}, vertex colors...")
    result = subprocess.run([blender_path, "--background", "--python", script_file],
                           capture_output=True, text=True, timeout=1800)

    for line in result.stdout.split('\n'):
        line = line.strip()
        if line and any(k in line for k in ['Mesh:', 'Writing', 'Converted', 'Done:', '/', 'ERROR', 'repair', 'manifold']):
            print(f"   {line}")

    if result.returncode != 0:
        print(f"\n⚠️ Blender error:")
        for line in result.stderr.split('\n')[-5:]:
            if line.strip():
                print(f"   {line.strip()}")
        return None

    if os.path.exists(output_path):
        return output_path
    return None


# ═══════════════════════════════════════════════════════════════
# Main pipeline
# ═══════════════════════════════════════════════════════════════

def find_blender():
    for path in BLENDER_PATHS:
        if os.path.exists(path):
            return path
        result = subprocess.run(["which", path], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    return None




def _snap_vertex_colors(obj_path, selected_colors):
    """Post-process OBJ to snap vertex colors to exact selected RGB values.
    Blender UV sampling causes interpolation → 40+ unique colors instead of 5.
    """
    import numpy as np
    sel_rgb = np.array([sc["rgb"] for sc in selected_colors])  # float 0-1
    sel_lab = np.array([sc["lab"] for sc in selected_colors])
    
    lines_out = []
    snapped = 0
    with open(obj_path) as f:
        for line in f:
            if line.startswith('v ') and len(line.split()) >= 7:
                parts = line.strip().split()
                xyz = parts[1:4]
                rgb = np.array([float(parts[4]), float(parts[5]), float(parts[6])])
                # Find nearest selected color using CIELAB distance
                rgb_reshaped = rgb.reshape(1, -1)
                lab = srgb_to_lab(rgb_reshaped)[0]
                dist = np.sum((sel_lab - lab) ** 2, axis=1)
                nearest = sel_rgb[np.argmin(dist)]
                nearest = sel_rgb[np.argmin(dist)]
                vline = "v %s %s %s %.4f %.4f %.4f\n" % (xyz[0], xyz[1], xyz[2], nearest[0], nearest[1], nearest[2])
                lines_out.append(vline)
            else:
                lines_out.append(line)
    
    with open(obj_path, 'w') as f:
        f.writelines(lines_out)
    print(f"   Snapped {snapped:,} vertex colors to {len(sel_rgb)} exact colors")


def colorize(input_path, output_path, max_colors=8, height=0, subdivide=1,
             colors=None, min_pct=0.001, no_merge=False, island_size=1000, smooth=5):
    """
    Convert GLB to multi-color vertex-color OBJ.

    v4 pipeline:
      1. Extract texture (pygltflib, no Blender)
      2. Classify pixels into color families (HSV)
      3. Greedy select representative colors (median, ≤8)
      4. Assign every pixel to nearest color (CIELAB)
      5. Build quantized texture
      6. Apply to mesh as vertex colors (Blender)
      7. Export OBJ
    """
    blender = find_blender()
    if not blender:
        print("❌ Blender not found. Install: brew install --cask blender")
        return None

    if not os.path.exists(input_path):
        print(f"❌ Input file not found: {input_path}")
        return None

    max_colors = min(max_colors, 8)

    print(f"🎨 Colorize v4 Pipeline (≤{max_colors} colors)")
    print(f"   Input:     {input_path}")
    print(f"   Output:    {output_path}")
    if height > 0:
        print(f"   Height:    {height}mm")
    print()

    # ── Manual colors mode ──
    if colors:
        import re
        hex_list = [c.strip().lstrip('#') for c in colors.split(',')]
        for h in hex_list:
            if not re.match(r'^[0-9A-Fa-f]{6}$', h):
                print(f"❌ Invalid color: '#{h}'. Use hex format: #FF0000,#00FF00")
                return None
        manual_rgb = np.array([[int(h[i:i+2], 16)/255 for i in (0,2,4)] for h in hex_list])
        manual_lab = srgb_to_lab(manual_rgb)
        manual_selected = []
        for i, h in enumerate(hex_list):
            manual_selected.append({
                "rgb": manual_rgb[i],
                "lab": manual_lab[i],
                "family": f"manual_{i+1}",
                "group_names": [f"#{h.upper()}"],
                "pixel_count": 0,
                "percentage": 0,
            })
        print(f"🎨 Manual colors mode ({len(manual_selected)} colors)")
        for sc in manual_selected:
            rgb_int = (sc["rgb"] * 255).astype(int)
            print(f"   #{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}")

        # Still need texture for vertex color mapping
        print(f"\n📷 Extracting texture for vertex color mapping...")
        texture = extract_texture(input_path)
        if texture is None:
            texture = extract_texture_blender(input_path, blender)
        if texture is None:
            print("   ❌ No texture found")
            return None

        w, h_img = texture.size
        pixels = np.array(texture).reshape(-1, 3).astype(np.float32) / 255.0
        pixel_lab = srgb_to_lab(pixels)
        labels = assign_pixels(pixel_lab, manual_selected)
        quantized = build_quantized_texture(pixels, labels, manual_selected, w, h_img)

        npy_path = os.path.join(tempfile.gettempdir(), "bambu_quantized_texture.npy")
        np.save(npy_path, quantized[::-1])

        from PIL import Image
        preview_path = os.path.splitext(output_path)[0] + "_preview.png"
        Image.fromarray(quantized).save(preview_path)

        result = apply_vertex_colors(
            os.path.abspath(input_path), npy_path,
            os.path.abspath(output_path), blender,
            height_mm=height, subdivide=subdivide
        )
        if result:
            size_kb = os.path.getsize(output_path) // 1024
            print(f"\n✅ Output: {output_path} ({size_kb} KB)")
            return output_path
        return None

    # ── Step 1: Extract texture ──
    print(f"📷 Step 1: Extract texture")
    texture = extract_texture(input_path)
    if texture is None:
        texture = extract_texture_blender(input_path, blender)
    if texture is None:
        print("   ❌ No texture found in model")
        return None

    w, h = texture.size
    pixels = np.array(texture).reshape(-1, 3).astype(np.float32) / 255.0
    N = len(pixels)
    print(f"   ✅ {w}×{h} = {N:,} pixels")

    # ── Step 2: Pixel family classification ──
    print(f"\n🏷️  Step 2: Pixel family classification")
    pixel_families = classify_pixels(pixels)

    for fid in range(12):
        count = int(np.sum(pixel_families == fid))
        if count > 0:
            pct = count / N * 100
            avg = (pixels[pixel_families == fid].mean(axis=0) * 255).astype(int)
            print(f"   {FAMILY_NAMES[fid]:12s}: {count:>10,} px ({pct:5.1f}%)  avg RGB({avg[0]:3d},{avg[1]:3d},{avg[2]:3d})")

    # ── Step 3: Greedy color selection ──
    print(f"\n🎯 Step 3: Greedy color selection (≤{max_colors})")
    pixel_lab = srgb_to_lab(pixels)
    selected = greedy_select_colors(pixels, pixel_lab, pixel_families, max_colors, min_pct=min_pct, no_merge=no_merge)

    for i, sc in enumerate(selected):
        rgb_int = (sc["rgb"] * 255).astype(int)
        hex_c = f"#{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}"
        print(f"   #{i+1}: {sc['family']:12s} ({sc['percentage']:5.1f}%) → {hex_c}")

    # ── Step 4: Per-pixel assignment ──
    print(f"\n🔄 Step 4: Per-pixel CIELAB assignment ({N:,} px × {len(selected)} colors)")
    labels = assign_pixels(pixel_lab, selected, pixel_families=pixel_families, pixels=pixels)

    for i, sc in enumerate(selected):
        pct = np.sum(labels == i) / N * 100
        rgb_int = (sc["rgb"] * 255).astype(int)
        hex_c = f"#{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}"
        print(f"   {hex_c}: {pct:.1f}%")

    # ── Step 4b: Boundary erosion + island cleanup ──
    labels_2d = labels.reshape(h, w)
    
    # Majority vote smoothing — each pixel adopts the most common color in its neighborhood
    from scipy.ndimage import uniform_filter
    n_colors = len(selected)
    for vote_pass in range(5):
        # Build per-color density maps, pick highest density at each pixel
        best = np.zeros_like(labels_2d, dtype=np.int32)
        best_score = np.zeros(labels_2d.shape, dtype=np.float32)
        for lbl in range(n_colors):
            density = uniform_filter((labels_2d == lbl).astype(np.float32), size=7)
            better = density > best_score
            best[better] = lbl
            best_score[better] = density[better]
        labels_2d = best
    print(f"   Boundary smoothing ({smooth}-pass majority vote, 7×7 window)")
    
    labels_2d = cleanup_labels(labels_2d, min_island=island_size)
    # Median filter to smooth thin strips and jagged edges
    from scipy.ndimage import median_filter
    labels_2d = median_filter(labels_2d, size=7)
    labels = labels_2d.ravel()
    print(f"   Cleaned isolated patches + median smoothed")

        # ── Step 5: Build quantized texture ──
    print(f"\n🖼️  Step 5: Quantized texture")
    quantized = build_quantized_texture(pixels, labels, selected, w, h)

    # Save Y-flipped for Blender UV
    npy_path = os.path.join(tempfile.gettempdir(), "bambu_quantized_texture.npy")
    np.save(npy_path, quantized[::-1])

    # Save preview PNG
    from PIL import Image
    preview_path = os.path.splitext(output_path)[0] + "_preview.png"
    Image.fromarray(quantized).save(preview_path)
    print(f"   ✅ {w}×{h}, {len(selected)} colors")
    print(f"   📷 Preview: {preview_path}")

    # ── Step 6: Apply vertex colors ──
    print(f"\n🔧 Step 6: Vertex colors via Blender")
    result = apply_vertex_colors(
        os.path.abspath(input_path), npy_path,
        os.path.abspath(output_path), blender,
        height_mm=height, subdivide=subdivide
    )

    if result:
        size_kb = os.path.getsize(output_path) // 1024
        _snap_vertex_colors(output_path, selected)
        print(f"\n✅ Output: {output_path} ({size_kb} KB)")
        print(f"   Colors: {len(selected)}")
        for i, sc in enumerate(selected):
            rgb_int = (sc["rgb"] * 255).astype(int)
            hex_c = f"#{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}"
            print(f"   {i+1}. {hex_c} ({sc['family']}, {sc['percentage']:.1f}%)")
        print(f"\n📋 Next: Import OBJ into Bambu Studio → map vertex colors to AMS filaments")
        return output_path
    else:
        print("❌ Failed to create output")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="🎨 Multi-color converter v4 for Bambu Lab AMS (GLB → vertex-color OBJ)",
        epilog="Pipeline: Extract texture → Pixel classify → Greedy select → CIELAB assign → Vertex color → OBJ"
    )
    parser.add_argument("input", help="Input model (GLB/GLTF/OBJ/FBX/STL)")
    parser.add_argument("--output", "-o", help="Output OBJ path")
    parser.add_argument("--min-pct", type=float, default=1.0,
                        help="Min %% for small color families (default 2.0, set 0 to keep all)")
    parser.add_argument("--max_colors", "-n", type=int, default=8, choices=range(1, 9),
                        help="Maximum colors (1-8, default 8)")
    parser.add_argument("--height", type=float, default=0, help="Target height mm (0=keep)")
    parser.add_argument("--subdivide", type=int, default=1, choices=[0, 1, 2, 3],
                        help="Subdivision (0=raw, 1=default, 2-3=high)")
    parser.add_argument("--colors", "-c", help="Manual hex colors (legacy, comma-separated)")
    parser.add_argument("--no-merge", action="store_true",
                            help="Disable family mutual exclusion (all 12 families independent)")
    parser.add_argument("--island-size", type=int, default=1000,
                            help="Island cleanup threshold in pixels (0=disabled)")
    parser.add_argument("--smooth", type=int, default=5,
                            help="Majority vote smoothing passes (0=disabled)")

    args = parser.parse_args()

    if not args.output:
        args.output = os.path.splitext(args.input)[0] + "_multicolor.obj"

    result = colorize(
        args.input, args.output,
        max_colors=args.max_colors,
        height=args.height,
        subdivide=args.subdivide,
        colors=args.colors,
        min_pct=getattr(args, "min_pct", 1.0) / 100
    )
    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
