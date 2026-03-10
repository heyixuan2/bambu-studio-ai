"""Texture extraction from GLB/GLTF models and quantized texture building."""

import os
import io
import json
import subprocess
import tempfile

import numpy as np


def extract_texture(glb_path):
    """Extract texture from GLB using pygltflib (no Blender needed).
    Returns PIL Image or None.
    """
    try:
        import pygltflib
        from PIL import Image
    except ImportError:
        return None

    try:
        glb = pygltflib.GLTF2().load(glb_path)
    except Exception:
        return None

    if not glb.images:
        return None

    img_data = None
    for img_obj in glb.images:
        if img_obj.bufferView is not None:
            bv = glb.bufferViews[img_obj.bufferView]
            blob = glb.binary_blob() if hasattr(glb, "binary_blob") else None
            if blob:
                start = bv.byteOffset or 0
                end = start + bv.byteLength
                img_data = blob[start:end]
                break
        elif img_obj.uri:
            uri = img_obj.uri
            if uri.startswith("data:"):
                import base64
                header, data = uri.split(",", 1)
                img_data = base64.b64decode(data)
                break
            else:
                img_path = os.path.join(os.path.dirname(glb_path), uri)
                if os.path.exists(img_path):
                    with open(img_path, "rb") as f:
                        img_data = f.read()
                    break

    if img_data is None:
        return None

    try:
        img = Image.open(io.BytesIO(img_data)).convert("RGB")
        return img
    except Exception:
        return None


def extract_texture_blender(glb_path, blender_path):
    """Fallback: extract texture via Blender headless."""
    from PIL import Image

    glb_esc = json.dumps(glb_path)
    tmp_tex = os.path.join(tempfile.gettempdir(), "bambu_extracted_texture.png")
    tex_esc = json.dumps(tmp_tex)

    script = f'''
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={glb_esc})
for img in bpy.data.images:
    if img.size[0] > 0 and img.name != "Render Result":
        img.save_render({tex_esc})
        print(f"Saved texture: {{img.name}} ({{img.size[0]}}x{{img.size[1]}})")
        break
'''
    script_file = os.path.join(tempfile.gettempdir(), "bambu_extract_tex.py")
    with open(script_file, "w") as f:
        f.write(script)

    try:
        subprocess.run(
            [blender_path, "--background", "--python", script_file],
            capture_output=True, timeout=120,
        )
    except Exception:
        return None

    if os.path.exists(tmp_tex):
        try:
            return Image.open(tmp_tex).convert("RGB")
        except Exception:
            return None
    return None


def build_quantized_texture(pixels, labels, selected_colors, width, height):
    """Build quantized RGB texture from labels. Returns uint8 (H,W,3)."""
    sel_rgb = np.array([sc["rgb"] for sc in selected_colors])
    return np.round(sel_rgb[labels].reshape(height, width, 3) * 255).astype(np.uint8)


def cleanup_labels(labels_2d, min_island=1000, protect_mask=None):
    """Remove tiny isolated color regions by majority vote of neighbors.

    Protects the LARGEST connected component of each color from removal, so
    small but salient features (eyes, buttons) that are the only representative
    of their color are never erased.
    """
    from scipy import ndimage
    h, w = labels_2d.shape
    cleaned = labels_2d.copy()

    unique_labels = np.unique(labels_2d)
    for lbl in unique_labels:
        mask = labels_2d == lbl
        components, n_comp = ndimage.label(mask)
        if n_comp <= 1:
            continue

        comp_sizes = [int(np.sum(components == cid)) for cid in range(1, n_comp + 1)]
        max_size = max(comp_sizes)

        for comp_id, comp_size in enumerate(comp_sizes, 1):
            if comp_size == max_size:
                continue
            if comp_size >= min_island:
                continue
            comp_mask = components == comp_id
            if protect_mask is not None and np.any(protect_mask & comp_mask):
                continue
            dilated = ndimage.binary_dilation(comp_mask, iterations=1)
            neighbor_mask = dilated & ~comp_mask
            if np.sum(neighbor_mask) == 0:
                continue
            neighbor_labels = labels_2d[neighbor_mask]
            counts = np.bincount(neighbor_labels)
            majority = np.argmax(counts)
            cleaned[comp_mask] = majority

    return cleaned


def preserve_salient_regions(labels_2d, pixel_lab_2d, min_region=64,
                             contrast_delta=18.0):
    """Protect small-but-meaningful regions from later smoothing.
    Returns a boolean mask of visually distinct regions worth preserving.
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
