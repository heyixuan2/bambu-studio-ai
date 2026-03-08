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

  # With Bambu filament suggestions:
  python3 scripts/colorize.py model.glb --height 80 --bambu-map

  # Disable geometry-based eye/button protection (texture-only):
  python3 scripts/colorize.py model.glb --height 80 --no-geometry-protect
"""

import os
import sys
import io
import json
import argparse
import subprocess
import tempfile
import numpy as np

from common import find_blender, SKILL_DIR as _skill_dir


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
                bv_off = bv.byteOffset or 0
                data = glb.binary_blob()[bv_off:bv_off + bv.byteLength]
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
    glb_esc = json.dumps(glb_path)
    out_esc = json.dumps(out_png)
    script = f'''
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={glb_esc})
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError("No mesh found in GLB")
obj = meshes[0]
for mat in obj.data.materials:
    if mat and mat.use_nodes:
        for link in mat.node_tree.links:
            if link.to_node.type == 'BSDF_PRINCIPLED' and link.to_socket.name == 'Base Color':
                if link.from_node.type == 'TEX_IMAGE':
                    img = link.from_node.image
                    img.filepath_raw = {out_esc}
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

# Legacy family groups (empty — all 12 families independent since v0.22.20)
FAMILY_GROUPS = {}


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

def _representative_color(rgb_pixels, lab_pixels):
    """Stable representative color for a region/family.

    Uses a trimmed median/mean blend to reduce baked-shadow bias while keeping
    the robustness of median statistics.
    """
    if len(rgb_pixels) == 0:
        return np.array([0.5, 0.5, 0.5]), np.array([50.0, 0.0, 0.0])
    if len(rgb_pixels) < 16:
        return np.median(rgb_pixels, axis=0), np.median(lab_pixels, axis=0)

    luminance = rgb_pixels.max(axis=1)
    lo = np.quantile(luminance, 0.10)
    hi = np.quantile(luminance, 0.90)
    keep = (luminance >= lo) & (luminance <= hi)
    trimmed_rgb = rgb_pixels[keep] if np.any(keep) else rgb_pixels
    trimmed_lab = lab_pixels[keep] if np.any(keep) else lab_pixels

    median_rgb = np.median(trimmed_rgb, axis=0)
    median_lab = np.median(trimmed_lab, axis=0)
    mean_rgb = np.mean(trimmed_rgb, axis=0)
    mean_lab = np.mean(trimmed_lab, axis=0)
    return 0.7 * median_rgb + 0.3 * mean_rgb, 0.7 * median_lab + 0.3 * mean_lab


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

        # Floor threshold: skip noise families below min_pct
        if best_count / N < min_pct:
            break





        group = [best_fid] if no_merge else FAMILY_GROUPS.get(best_fid, [best_fid])
        group_mask = np.zeros(N, dtype=bool)
        for gf in group:
            group_mask |= (pixel_families == gf)
        total = int(np.sum(group_mask))
        if total == 0:
            break

        # Representative: trimmed median/mean blend in RGB and LAB
        median_rgb, median_lab = _representative_color(pixels[group_mask], pixel_lab[group_mask])

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


def _name_from_rgb(median_rgb):
    """Name a color by closest HSV family from 0-1 float RGB."""
    r, g, b = int(median_rgb[0] * 255), int(median_rgb[1] * 255), int(median_rgb[2] * 255)
    maxc = max(r, g, b)
    minc = min(r, g, b)
    v = maxc / 255.0
    s = (maxc - minc) / maxc if maxc > 0 else 0
    # Match classify_pixels thresholds exactly
    if s < 0.15 or v < 0.1:
        if v < 0.2: return "black"
        elif v < 0.5: return "dark_gray"
        elif v < 0.8: return "light_gray"
        else: return "white"
    diff = maxc - minc
    if diff == 0: h = 0
    elif maxc == r: h = 60 * ((g - b) / diff % 6)
    elif maxc == g: h = 60 * ((b - r) / diff + 2)
    else: h = 60 * ((r - g) / diff + 4)
    if h < 0: h += 360
    if h < 15 or h >= 345: return "red"
    elif h < 40: return "orange"
    elif h < 70: return "yellow"
    elif h < 160: return "green"
    elif h < 200: return "cyan"
    elif h < 260: return "blue"
    elif h < 310: return "purple"
    else: return "pink"


def kmeans_select_colors(pixels, pixel_lab, max_colors=8, min_pct=0.001):
    """
    Direct k-means in full CIELAB space — best for sub-color detail.
    Splits similar hues into fine variations (e.g., 3 shades of brown).
    May merge small distinct hues into large clusters (e.g., miss red cheeks).
    """
    from sklearn.cluster import KMeans
    
    N = len(pixels)
    if N > 200000:
        rng = np.random.RandomState(42)
        idx = rng.choice(N, 200000, replace=False)
        sub_lab = pixel_lab[idx]
        sub_rgb = pixels[idx]
    else:
        sub_lab = pixel_lab
        sub_rgb = pixels
    
    Ns = len(sub_lab)
    km = KMeans(n_clusters=max_colors, init='k-means++', n_init=5, random_state=42, max_iter=100)
    labels = km.fit_predict(sub_lab)
    
    selected = []
    for cid in range(max_colors):
        m = labels == cid
        count = int(np.sum(m))
        if count < Ns * min_pct:
            continue
        median_rgb = np.median(sub_rgb[m], axis=0)
        median_lab = np.median(sub_lab[m], axis=0)
        selected.append({
            "rgb": median_rgb,
            "lab": median_lab,
            "family": _name_from_rgb(median_rgb),
            "group_names": [_name_from_rgb(median_rgb)],
            "pixel_count": count,
            "percentage": count / Ns * 100,
        })
    
    selected.sort(key=lambda x: -x["percentage"])
    return selected


def hybrid_select_colors(pixels, pixel_lab, pixel_families, max_colors=8, min_pct=0.001):
    """
    Hybrid HSV + k-means color selection (shadow-immune):
    
    1. HSV families guarantee hue separation (red ≠ yellow ≠ blue)
    2. If significant families > max_colors: keep largest
    3. If significant families < max_colors: k-means splits largest families
    
    This avoids k-means merging small but distinct hues (e.g., red cheeks on Pikachu).
    """
    from sklearn.cluster import KMeans
    
    N = len(pixels)
    
    # ── Find all significant HSV families ──
    family_data = []
    for fid in range(12):
        mask = pixel_families == fid
        count = int(np.sum(mask))
        if count < N * min_pct:
            continue
        pct = count / N * 100
        median_rgb, median_lab = _representative_color(pixels[mask], pixel_lab[mask])
        family_data.append({
            "fid": fid,
            "rgb": median_rgb,
            "lab": median_lab,
            "family": FAMILY_NAMES[fid],
            "group_names": [FAMILY_NAMES[fid]],
            "pixel_count": count,
            "percentage": pct,
            "mask": mask,
        })
    
    family_data.sort(key=lambda x: -x["pixel_count"])
    n_families = len(family_data)
    print(f"   Significant families: {n_families} (threshold {min_pct*100:.1f}%)")
    
    if n_families >= max_colors:
        # Too many families — keep the largest max_colors
        selected = family_data[:max_colors]
    else:
        # Fewer families than max_colors — split largest families with k-means
        selected = list(family_data)
        slots_left = max_colors - n_families
        
        # Sort by size descending, try splitting each
        for fd in sorted(family_data, key=lambda x: -x["pixel_count"]):
            if slots_left <= 0:
                break
            
            fmask = fd["mask"]
            fcount = fd["pixel_count"]
            if fcount < 2000:  # too small to split
                continue
            
            # k-means on this family's pixels in LAB space
            f_lab = pixel_lab[fmask]
            f_rgb = pixels[fmask]
            
            # Subsample if needed
            if len(f_lab) > 100000:
                rng = np.random.RandomState(42)
                idx = rng.choice(len(f_lab), 100000, replace=False)
                f_lab_sub = f_lab[idx]
                f_rgb_sub = f_rgb[idx]
            else:
                f_lab_sub = f_lab
                f_rgb_sub = f_rgb
            
            # Try splitting into 2
            km = KMeans(n_clusters=2, init='k-means++', n_init=5, random_state=42, max_iter=50)
            km.fit(f_lab_sub)
            
            # Check if the split is meaningful (centers far enough apart in LAB)
            center_dist = np.sqrt(np.sum((km.cluster_centers_[0] - km.cluster_centers_[1]) ** 2))
            if center_dist < 10:  # too similar, don't split
                continue
            
            # Predict on FULL family pixels (not just subsample) for accurate counts
            full_labels = km.predict(f_lab)
            
            # Remove original from selected
            selected = [s for s in selected if s.get("fid") != fd["fid"]]
            
            for sub_id in [0, 1]:
                sub_mask_full = full_labels == sub_id
                sub_count = int(np.sum(sub_mask_full))
                if sub_count < N * min_pct:
                    continue
                if len(f_rgb) == len(full_labels):
                    med_rgb, med_lab = _representative_color(f_rgb[sub_mask_full], f_lab[sub_mask_full])
                else:
                    med_rgb, med_lab = _representative_color(f_rgb_sub[km.labels_ == sub_id], f_lab_sub[km.labels_ == sub_id])
                selected.append({
                    "rgb": med_rgb,
                    "lab": med_lab,
                    "family": fd["family"],
                    "group_names": [fd["family"]],
                    "pixel_count": sub_count,
                    "percentage": sub_count / N * 100,
                })
            
            slots_left -= 1
    
    # Clean up internal fields
    for s in selected:
        s.pop("mask", None)
        s.pop("fid", None)
    
    selected.sort(key=lambda x: -x["percentage"])
    
    # Hard cap at max_colors (AMS has 8 slots max)
    if len(selected) > max_colors:
        selected = selected[:max_colors]
    
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
# Geometry-based saliency (curvature → protect eyes, buttons, etc.)
# ═══════════════════════════════════════════════════════════════

def _curvature_mask_from_glb(glb_path, width, height, percentile=92):
    """Build a 2D mask from mesh curvature: convex regions (eyes, buttons) = True.
    Uses trimesh vertex_defects + UV rasterization. Returns (height, width) bool array.
    """
    try:
        import pygltflib
        import trimesh
    except ImportError:
        return None

    ext = os.path.splitext(glb_path)[1].lower()
    if ext not in (".glb", ".gltf"):
        return None

    try:
        glb = pygltflib.GLTF2().load(glb_path)
        blob = glb.binary_blob() if hasattr(glb, "binary_blob") else getattr(glb, "_glb_data", None)
        if blob is None:
            return None
    except Exception:
        return None

    all_verts, all_faces, all_uvs = [], [], []
    offset = 0

    for mesh in glb.meshes:
        for prim in mesh.primitives:
            attrs = prim.attributes
            pos_idx = getattr(attrs, "POSITION", None) or (attrs.get("POSITION") if isinstance(attrs, dict) else None)
            if pos_idx is None:
                continue
            acc = glb.accessors[pos_idx]
            bv = glb.bufferViews[acc.bufferView]
            start = (bv.byteOffset or 0) + (acc.byteOffset or 0)
            end = start + acc.count * 3 * 4  # float32 × vec3
            verts = np.frombuffer(blob[start:end], dtype=np.float32).reshape(-1, 3)

            # Indices
            idx_val = prim.indices
            if idx_val is not None:
                idx_acc = glb.accessors[idx_val]
                idx_bv = glb.bufferViews[idx_acc.bufferView]
                comp_type = getattr(idx_acc, "componentType", 5123)
                dtype = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}.get(comp_type, np.uint16)
                idx_start = (idx_bv.byteOffset or 0) + (idx_acc.byteOffset or 0)
                idx_end = idx_start + idx_acc.count * dtype().itemsize
                idx_data = np.frombuffer(blob[idx_start:idx_end], dtype=dtype)
                faces = idx_data.reshape(-1, 3)
            else:
                faces = np.arange(len(verts), dtype=np.uint32).reshape(-1, 3)

            # UV
            tex_idx = getattr(attrs, "TEXCOORD_0", None) or getattr(attrs, "texcoord_0", None) or (attrs.get("TEXCOORD_0") if isinstance(attrs, dict) else None)
            if tex_idx is None:
                continue
            uv_acc = glb.accessors[tex_idx]
            uv_bv = glb.bufferViews[uv_acc.bufferView]
            uv_start = (uv_bv.byteOffset or 0) + (uv_acc.byteOffset or 0)
            uv_end = uv_start + uv_acc.count * 2 * 4  # float32 × vec2
            uvs = np.frombuffer(blob[uv_start:uv_end], dtype=np.float32).reshape(-1, 2)

            all_verts.append(verts)
            all_faces.append(faces + offset)
            all_uvs.append(uvs)
            offset += len(verts)

    if not all_verts:
        return None

    verts = np.vstack(all_verts)
    faces = np.vstack(all_faces)
    uvs = np.vstack(all_uvs)

    try:
        mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        defects = trimesh.curvature.vertex_defects(mesh)
    except Exception:
        return None

    # Per-face curvature = max of 3 vertex defects (convex = positive)
    face_curv = np.maximum.reduce([defects[faces[:, 0]], defects[faces[:, 1]], defects[faces[:, 2]]])
    threshold = np.percentile(face_curv[face_curv > 0], percentile) if np.any(face_curv > 0) else 0.05
    salient_faces = face_curv >= threshold

    # Rasterize salient faces onto texture-space curvature map
    curvature_map = np.zeros((height, width), dtype=np.float32)

    try:
        from skimage.draw import polygon as _skpoly
        _has_skimage = True
    except ImportError:
        _has_skimage = False

    salient_idx = np.where(salient_faces)[0]
    for i in salient_idx:
        fa = faces[i]
        u0, v0 = uvs[fa[0]]
        u1, v1 = uvs[fa[1]]
        u2, v2 = uvs[fa[2]]
        v0, v1, v2 = 1 - v0, 1 - v1, 1 - v2
        r0, c0 = int(v0 * (height - 1)) % height, int(u0 * (width - 1)) % width
        r1, c1 = int(v1 * (height - 1)) % height, int(u1 * (width - 1)) % width
        r2, c2 = int(v2 * (height - 1)) % height, int(u2 * (width - 1)) % width
        if _has_skimage:
            rr, cc = _skpoly([r0, r1, r2], [c0, c1, c2], shape=(height, width))
            curvature_map[rr, cc] = np.maximum(curvature_map[rr, cc], face_curv[i])
        else:
            r_min, r_max = max(0, min(r0, r1, r2)), min(height - 1, max(r0, r1, r2))
            c_min, c_max = max(0, min(c0, c1, c2)), min(width - 1, max(c0, c1, c2))
            for rr in range(r_min, r_max + 1):
                for cc in range(c_min, c_max + 1):
                    u_pt = cc / (width - 1) if width > 1 else 0.5
                    v_pt = 1 - rr / (height - 1) if height > 1 else 0.5
                    if _point_in_triangle(u_pt, v_pt, u0, v0, u1, v1, u2, v2):
                        curvature_map[rr, cc] = max(curvature_map[rr, cc], face_curv[i])

    return curvature_map > 0


def _point_in_triangle(px, py, x0, y0, x1, y1, x2, y2):
    """Barycentric test for point in triangle."""
    d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(d) < 1e-10:
        return False
    a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / d
    b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / d
    c = 1 - a - b
    return 0 <= a <= 1 and 0 <= b <= 1 and 0 <= c <= 1


# ═══════════════════════════════════════════════════════════════
# Step 5: Build quantized texture
# ═══════════════════════════════════════════════════════════════


def cleanup_labels(labels_2d, min_island=1000, protect_mask=None):
    """Remove tiny isolated color regions by majority vote of neighbors.

    Protects the LARGEST connected component of each color from removal, so
    small but salient features (eyes, buttons, accessories) that are the only
    representative of their color are never erased — only redundant satellite
    blobs below min_island pixels are removed.
    protect_mask: optional (H,W) bool — pixels in high-curvature regions (eyes, etc.) are never merged.
    """
    from scipy import ndimage
    h, w = labels_2d.shape
    cleaned = labels_2d.copy()

    unique_labels = np.unique(labels_2d)
    for lbl in unique_labels:
        mask = labels_2d == lbl
        # Find connected components for this color
        components, n_comp = ndimage.label(mask)
        if n_comp <= 1:
            continue  # Only one component — nothing to clean up

        # Find sizes so we can protect the largest representative
        comp_sizes = [int(np.sum(components == cid)) for cid in range(1, n_comp + 1)]
        max_size = max(comp_sizes)

        for comp_id, comp_size in enumerate(comp_sizes, 1):
            # Always keep the largest component for this color (salient region guard).
            # This prevents small but important color regions (e.g., a character's eyes
            # that are the only white pixels) from being wiped out by island cleanup.
            if comp_size == max_size:
                continue
            if comp_size >= min_island:
                continue
            comp_mask = components == comp_id
            # Geometry protect: never merge components that overlap high-curvature regions (eyes, etc.)
            if protect_mask is not None and np.any(protect_mask & comp_mask):
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


def preserve_salient_regions(labels_2d, pixel_lab_2d, min_region=64, contrast_delta=18.0):
    """Protect small-but-meaningful regions from later smoothing.

    Returns a boolean mask of pixels that belong to connected regions which are
    small enough to be at risk, but visually distinct enough from their
    neighbors that they should be preserved.
    """
    from scipy import ndimage
    protected = np.zeros(labels_2d.shape, dtype=bool)
    for lbl in np.unique(labels_2d):
        mask = labels_2d == lbl
        components, n_comp = ndimage.label(mask)
        for comp_id in range(1, n_comp + 1):
            comp_mask = components == comp_id
            area = int(np.sum(comp_mask))
            if area < min_region:
                continue
            dilated = ndimage.binary_dilation(comp_mask, iterations=1)
            ring = dilated & ~comp_mask
            if not np.any(ring):
                continue
            region_lab = np.median(pixel_lab_2d[comp_mask], axis=0)
            ring_lab = np.median(pixel_lab_2d[ring], axis=0)
            delta = float(np.linalg.norm(region_lab - ring_lab))
            if delta >= contrast_delta:
                protected[comp_mask] = True
    return protected


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

    # Use json.dumps for safe path embedding (avoids injection)
    glb_esc = json.dumps(glb_path)
    npy_esc = json.dumps(quantized_npy_path)
    out_esc = json.dumps(output_path)

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
if not meshes:
    raise RuntimeError("No mesh found in model")
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

print("Writing vertex colors (vectorized)...")
n_loops = len(uv)
uv_arr = np.empty(n_loops * 2, dtype=np.float32)
uv[0].id_data.uv_layers.active.data.foreach_get("uv", uv_arr)
uv_arr = uv_arr.reshape(-1, 2)
px = (uv_arr[:, 0] * tw).astype(np.int32) % tw
py = (uv_arr[:, 1] * th).astype(np.int32) % th
sampled = tex_linear[py, px]  # (n_loops, 3)
colors_flat = np.empty(n_loops * 4, dtype=np.float32)
colors_flat[0::4] = sampled[:, 0]
colors_flat[1::4] = sampled[:, 1]
colors_flat[2::4] = sampled[:, 2]
colors_flat[3::4] = 1.0
cl.data.foreach_set("color", colors_flat)
mesh.update()
print(f"  Done: {{n_loops:,}} loop colors set")

# Convert to mm and auto-scale
bbox_post = [obj.matrix_world @ v.co for v in obj.data.vertices]
xs = [v.x for v in bbox_post]
ys = [v.y for v in bbox_post]
zs = [v.z for v in bbox_post]
dims_post = (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
max_dim = max(dims_post)

if max_dim < 10:
    # Model in meters, convert to mm
    obj.scale *= 1000
    bpy.ops.object.transform_apply(scale=True)
    max_dim *= 1000
    print("Converted to mm")

# Auto-scale to 80mm if no --height specified and model is too big or too small
if height_mm == 0 and (max_dim > 200 or max_dim < 10):
    target = 80.0
    scale_factor = target / max_dim
    obj.scale *= scale_factor
    bpy.ops.object.transform_apply(scale=True)
    print(f"Auto-scaled: {{max_dim:.1f}} → {{target:.0f}}mm")

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




def _load_bambu_palette():
    """Load Bambu Lab filament palette from references/bambu_filament_colors.json.
    Returns list of dicts: {line, name, hex, rgb, lab}.
    """
    path = os.path.join(_skill_dir, "references", "bambu_filament_colors.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    palette = []
    for line_name, colors in data.get("filaments", {}).items():
        for color_name, hex_val in colors.items():
            hex_val = hex_val.strip().lstrip("#")
            if len(hex_val) != 6:
                continue
            r, g, b = int(hex_val[0:2], 16) / 255.0, int(hex_val[2:4], 16) / 255.0, int(hex_val[4:6], 16) / 255.0
            rgb = np.array([[r, g, b]])
            lab = srgb_to_lab(rgb)[0]
            palette.append({
                "line": line_name,
                "name": color_name,
                "hex": f"#{hex_val.upper()}",
                "rgb": np.array([r, g, b]),
                "lab": lab,
            })
    return palette


def _map_colors_to_filaments(selected_colors, palette):
    """Map each selected color to closest Bambu filament by CIELAB distance.
    Returns list of dicts: {color_idx, hex, family, pct, best: {line, name, hex, delta_e}, alternatives: [...]}.
    """
    if not palette:
        return []
    sel_lab = np.array([sc["lab"] for sc in selected_colors])
    pal_lab = np.array([p["lab"] for p in palette])
    mappings = []
    for i, sc in enumerate(selected_colors):
        dists = np.sum((pal_lab - sel_lab[i]) ** 2, axis=1)
        order = np.argsort(dists)
        best = palette[order[0]]
        delta_e = float(np.sqrt(dists[order[0]]))
        alternatives = []
        for j in range(1, min(4, len(order))):
            alt = palette[order[j]]
            alt_delta = float(np.sqrt(dists[order[j]]))
            alternatives.append({"line": alt["line"], "name": alt["name"], "hex": alt["hex"], "delta_e": round(alt_delta, 1)})
        rgb_int = (sc["rgb"] * 255).astype(int)
        hex_c = f"#{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}"
        mappings.append({
            "color_idx": i + 1,
            "hex": hex_c,
            "family": sc["family"],
            "percentage": sc["percentage"],
            "best": {
                "line": best["line"],
                "name": best["name"],
                "hex": best["hex"],
                "delta_e": round(delta_e, 1),
            },
            "alternatives": alternatives,
        })
    return mappings


def _write_bambu_map(mappings, output_path):
    """Write _color_map.txt with Bambu filament suggestions."""
    map_path = os.path.splitext(output_path)[0] + "_color_map.txt"
    lines = [
        "Bambu Lab Filament Mapping Suggestions",
        "======================================",
        "Map each detected color to AMS slots in Bambu Studio.",
        "",
    ]
    for m in mappings:
        lines.append(f"Color {m['color_idx']}: {m['hex']} ({m['family']}, {m['percentage']:.1f}%)")
        lines.append(f"  → Best match: {m['best']['line']} / {m['best']['name']} {m['best']['hex']} (ΔE {m['best']['delta_e']})")
        if m["alternatives"]:
            alts = ", ".join(f"{a['line']} {a['name']}" for a in m["alternatives"])
            lines.append(f"  → Alternatives: {alts}")
        lines.append("")
    with open(map_path, "w") as f:
        f.write("\n".join(lines))
    return map_path


def _snap_vertex_colors(obj_path, selected_colors):
    """Post-process OBJ to snap vertex colors to exact selected RGB values.
    Blender UV sampling causes interpolation → 40+ unique colors instead of 5.
    Vectorized: reads all vertex colors, batch-converts to LAB, then writes back.
    """
    import numpy as np
    sel_rgb = np.array([sc["rgb"] for sc in selected_colors], dtype=np.float64)
    sel_lab = np.array([sc["lab"] for sc in selected_colors], dtype=np.float64)

    with open(obj_path) as f:
        lines = f.readlines()

    v_indices = []
    v_xyz = []
    v_rgb = []
    for i, line in enumerate(lines):
        if line.startswith('v '):
            parts = line.split()
            if len(parts) >= 7:
                v_indices.append(i)
                v_xyz.append(parts[1:4])
                v_rgb.append([float(parts[4]), float(parts[5]), float(parts[6])])

    if not v_indices:
        return

    rgb_arr = np.array(v_rgb, dtype=np.float64)
    lab_arr = srgb_to_lab(rgb_arr)

    # Vectorized nearest-neighbor: (N, 1, 3) - (1, K, 3) → (N, K)
    dists = np.sum((lab_arr[:, np.newaxis, :] - sel_lab[np.newaxis, :, :]) ** 2, axis=2)
    nearest_idx = np.argmin(dists, axis=1)
    nearest_rgb = sel_rgb[nearest_idx]

    snapped = int(np.sum(~np.all(np.abs(rgb_arr - nearest_rgb) < 0.01, axis=1)))
    for j, vi in enumerate(v_indices):
        xyz = v_xyz[j]
        nr = nearest_rgb[j]
        lines[vi] = "v %s %s %s %.4f %.4f %.4f\n" % (xyz[0], xyz[1], xyz[2], nr[0], nr[1], nr[2])

    with open(obj_path, 'w') as f:
        f.writelines(lines)
    print(f"   Snapped {snapped:,} vertex colors to {len(sel_rgb)} exact colors")


def colorize(input_path, output_path, max_colors=8, height=0, subdivide=1,
             colors=None, min_pct=0.001, no_merge=False, island_size=1000, smooth=5,
             method="hybrid", bambu_map=False, geometry_protect=True):
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
            if bambu_map:
                palette = _load_bambu_palette()
                if palette:
                    mappings = _map_colors_to_filaments(manual_selected, palette)
                    map_path = _write_bambu_map(mappings, output_path)
                    print(f"   📋 Bambu map: {map_path}")
                else:
                    print("   ⚠️ bambu_filament_colors.json not found, skip Bambu mapping")
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

    # ── Step 3: Color selection ──
    pixel_lab = srgb_to_lab(pixels)
    use_kmeans = False
    try:
        from sklearn.cluster import KMeans
        if method == "kmeans":
            print(f"\n🎯 Step 3: k-means color discovery (≤{max_colors})")
            selected = kmeans_select_colors(pixels, pixel_lab, max_colors, min_pct=min_pct)
        else:
            print(f"\n🎯 Step 3: Hybrid HSV + k-means color selection (≤{max_colors})")
            selected = hybrid_select_colors(pixels, pixel_lab, pixel_families, max_colors, min_pct=min_pct)
        use_kmeans = True
    except ImportError:
        print(f"\n🎯 Step 3: Greedy color selection (≤{max_colors}) [install scikit-learn for better results]")
        selected = greedy_select_colors(pixels, pixel_lab, pixel_families, max_colors, min_pct=min_pct, no_merge=no_merge)

    for i, sc in enumerate(selected):
        rgb_int = (sc["rgb"] * 255).astype(int)
        hex_c = f"#{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}"
        print(f"   #{i+1}: {sc['family']:12s} ({sc['percentage']:5.1f}%) → {hex_c}")

    # ── Step 4: Per-pixel assignment ──
    print(f"\n🔄 Step 4: Per-pixel CIELAB assignment ({N:,} px × {len(selected)} colors)")
    # k-means: pure CIELAB distance, no achromatic constraint
    # HSV legacy: use pixel_families for achromatic constraint
    if use_kmeans:
        labels = assign_pixels(pixel_lab, selected, pixel_families=None, pixels=pixels)
    else:
        labels = assign_pixels(pixel_lab, selected, pixel_families=pixel_families, pixels=pixels)

    for i, sc in enumerate(selected):
        pct = np.sum(labels == i) / N * 100
        rgb_int = (sc["rgb"] * 255).astype(int)
        hex_c = f"#{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}"
        print(f"   {hex_c}: {pct:.1f}%")

    # ── Step 4b: Boundary erosion + island cleanup ──
    labels_2d = labels.reshape(h, w)
    pixel_lab_2d = pixel_lab.reshape(h, w, 3)
    protected_mask = preserve_salient_regions(labels_2d, pixel_lab_2d, min_region=max(32, island_size // 6), contrast_delta=18.0)

    # Geometry-based protection: convex regions (eyes, buttons) from mesh curvature
    if geometry_protect and os.path.splitext(input_path)[1].lower() in (".glb", ".gltf"):
        geom_mask = _curvature_mask_from_glb(os.path.abspath(input_path), w, h)
        if geom_mask is not None:
            protected_mask = protected_mask | geom_mask
            print(f"   Geometry protect: {geom_mask.mean()*100:.1f}% convex regions (eyes, etc.)")

    # Majority vote smoothing — each pixel adopts the most common color in its neighborhood,
    # but we protect small high-contrast regions so eyes / accents / key details survive.
    from scipy.ndimage import uniform_filter, median_filter
    n_colors = len(selected)
    if smooth > 0:
        window = 5 if smooth <= 2 else 7
        for _ in range(smooth):
            best = labels_2d.copy()
            best_score = np.full(labels_2d.shape, -1.0, dtype=np.float32)
            for lbl in range(n_colors):
                density = uniform_filter((labels_2d == lbl).astype(np.float32), size=window)
                better = density > best_score
                best[better] = lbl
                best_score[better] = density[better]
            labels_2d = np.where(protected_mask, labels_2d, best)
        print(f"   Boundary smoothing ({smooth}-pass majority vote, {window}×{window} window, salient regions protected)")
    else:
        print(f"   Boundary smoothing: disabled (smooth=0)")

    if island_size > 0:
        labels_2d = cleanup_labels(labels_2d, min_island=island_size, protect_mask=protected_mask)

    if smooth > 0:
        smoothed = median_filter(labels_2d, size=5)
        labels_2d = np.where(protected_mask, labels_2d, smoothed)
    labels = labels_2d.ravel()
    print(f"   Cleaned isolated patches + edge-aware smoothing (protected {protected_mask.mean()*100:.1f}% salient pixels)")

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
        if bambu_map:
            palette = _load_bambu_palette()
            if palette:
                mappings = _map_colors_to_filaments(selected, palette)
                map_path = _write_bambu_map(mappings, output_path)
                print(f"   📋 Bambu map: {map_path}")
                for m in mappings:
                    print(f"      {m['hex']} → {m['best']['line']} {m['best']['name']} (ΔE {m['best']['delta_e']})")
            else:
                print("   ⚠️ bambu_filament_colors.json not found, skip Bambu mapping")
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
                        help="Min %% for color families / sub-clusters to keep (default 1.0, set 0 to keep nearly everything)")
    parser.add_argument("--max_colors", "-n", type=int, default=8, choices=range(1, 9),
                        help="Maximum colors (1-8, default 8)")
    parser.add_argument("--height", type=float, default=0, help="Target height mm (0=keep)")
    parser.add_argument("--subdivide", type=int, default=1, choices=[0, 1, 2, 3],
                        help="Subdivision (0=raw, 1=default, 2-3=high)")
    parser.add_argument("--colors", "-c", help="Manual hex colors (legacy, comma-separated)")
    parser.add_argument("--no-merge", action="store_true",
                            help="Disable family mutual exclusion (all 12 families independent)")
    parser.add_argument("--method", choices=["hybrid", "kmeans"], default="hybrid",
                        help="Color selection: hybrid (HSV+k-means, better hue separation) or kmeans (pure k-means, finer sub-colors)")
    parser.add_argument("--island-size", type=int, default=1000,
                            help="Island cleanup threshold in pixels (0=disabled)")
    parser.add_argument("--smooth", type=int, default=5,
                            help="Majority vote smoothing passes (0=disabled)")
    parser.add_argument("--bambu-map", action="store_true",
                            help="Output _color_map.txt with suggested Bambu filaments for each color")
    parser.add_argument("--no-geometry-protect", action="store_true",
                            help="Disable curvature-based protection for eyes/buttons (use texture-only)")

    args = parser.parse_args()

    if not args.output:
        args.output = os.path.splitext(args.input)[0] + "_multicolor.obj"

    result = colorize(
        args.input, args.output,
        max_colors=args.max_colors,
        height=args.height,
        subdivide=args.subdivide,
        colors=args.colors,
        min_pct=getattr(args, "min_pct", 1.0) / 100,
        no_merge=getattr(args, "no_merge", False),
        island_size=getattr(args, "island_size", 1000),
        smooth=getattr(args, "smooth", 5),
        method=getattr(args, "method", "hybrid"),
        bambu_map=getattr(args, "bambu_map", False),
        geometry_protect=not getattr(args, "no_geometry_protect", False),
    )
    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
