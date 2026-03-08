"""
Multi-Color Converter v4 — GLB to vertex-color OBJ for Bambu Lab AMS.

Pipeline: GLB → Extract texture (pygltflib) → Pixel family classification (HSV)
          → Greedy color-mode selection (≤8 colors) → Per-pixel CIELAB assign
          → Blender vertex color bake → OBJ export

Public API:
    from colorize import colorize
    colorize("model.glb", "output.obj", max_colors=4, height=80)
"""

import os
import sys
import tempfile
import numpy as np

# Add parent (scripts/) to path so `from common import ...` works
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import find_blender, SKILL_DIR as _skill_dir

from .color_science import srgb_to_lab, classify_pixels, FAMILY_NAMES
from .selection import (
    greedy_select_colors, kmeans_select_colors, hybrid_select_colors,
    assign_pixels,
)
from .texture import (
    extract_texture, extract_texture_blender,
    build_quantized_texture, cleanup_labels, preserve_salient_regions,
)
from .geometry import curvature_mask_from_glb
from .vertex_colors import apply_vertex_colors, snap_vertex_colors
from .bambu_map import load_bambu_palette, map_colors_to_filaments, write_bambu_map


def colorize(input_path, output_path, max_colors=8, height=0, subdivide=1,
             colors=None, min_pct=0.001, no_merge=False, island_size=1000,
             smooth=5, method="hybrid", bambu_map=False, geometry_protect=True):
    """Convert GLB to multi-color vertex-color OBJ.

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
        return _colorize_manual(
            input_path, output_path, colors, blender, height, subdivide, bambu_map)

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
            print(f"   {FAMILY_NAMES[fid]:12s}: {count:>10,} px ({pct:5.1f}%)  "
                  f"avg RGB({avg[0]:3d},{avg[1]:3d},{avg[2]:3d})")

    # ── Step 3: Color selection ──
    pixel_lab = srgb_to_lab(pixels)
    use_kmeans = False
    try:
        from sklearn.cluster import KMeans  # noqa: F401
        if method == "kmeans":
            print(f"\n🎯 Step 3: k-means color discovery (≤{max_colors})")
            selected = kmeans_select_colors(pixels, pixel_lab, max_colors, min_pct=min_pct)
        else:
            print(f"\n🎯 Step 3: Hybrid HSV + k-means color selection (≤{max_colors})")
            selected = hybrid_select_colors(
                pixels, pixel_lab, pixel_families, max_colors, min_pct=min_pct)
        use_kmeans = True
    except ImportError:
        print(f"\n🎯 Step 3: Greedy color selection (≤{max_colors}) "
              f"[install scikit-learn for better results]")
        selected = greedy_select_colors(
            pixels, pixel_lab, pixel_families, max_colors,
            min_pct=min_pct, no_merge=no_merge)

    for i, sc in enumerate(selected):
        rgb_int = (sc["rgb"] * 255).astype(int)
        hex_c = f"#{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}"
        print(f"   #{i+1}: {sc['family']:12s} ({sc['percentage']:5.1f}%) → {hex_c}")

    # ── Step 4: Per-pixel assignment ──
    print(f"\n🔄 Step 4: Per-pixel CIELAB assignment ({N:,} px × {len(selected)} colors)")
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
    protected_mask = preserve_salient_regions(
        labels_2d, pixel_lab_2d,
        min_region=max(32, island_size // 6), contrast_delta=18.0)

    if geometry_protect and os.path.splitext(input_path)[1].lower() in (".glb", ".gltf"):
        geom_mask = curvature_mask_from_glb(os.path.abspath(input_path), w, h)
        if geom_mask is not None:
            protected_mask = protected_mask | geom_mask
            print(f"   Geometry protect: {geom_mask.mean()*100:.1f}% convex regions (eyes, etc.)")

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
        print(f"   Boundary smoothing ({smooth}-pass majority vote, "
              f"{window}×{window} window, salient regions protected)")
    else:
        print(f"   Boundary smoothing: disabled (smooth=0)")

    if island_size > 0:
        labels_2d = cleanup_labels(labels_2d, min_island=island_size, protect_mask=protected_mask)

    if smooth > 0:
        smoothed = median_filter(labels_2d, size=5)
        labels_2d = np.where(protected_mask, labels_2d, smoothed)
    labels = labels_2d.ravel()
    print(f"   Cleaned isolated patches + edge-aware smoothing "
          f"(protected {protected_mask.mean()*100:.1f}% salient pixels)")

    # ── Step 5: Build quantized texture ──
    print(f"\n🖼️  Step 5: Quantized texture")
    quantized = build_quantized_texture(pixels, labels, selected, w, h)

    npy_path = os.path.join(tempfile.gettempdir(), "bambu_quantized_texture.npy")
    np.save(npy_path, quantized[::-1])

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
        snap_vertex_colors(output_path, selected)
        print(f"\n✅ Output: {output_path} ({size_kb} KB)")
        print(f"   Colors: {len(selected)}")
        for i, sc in enumerate(selected):
            rgb_int = (sc["rgb"] * 255).astype(int)
            hex_c = f"#{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}"
            print(f"   {i+1}. {hex_c} ({sc['family']}, {sc['percentage']:.1f}%)")
        if bambu_map:
            _do_bambu_map(selected, output_path)
        print(f"\n📋 Next: Import OBJ into Bambu Studio → map vertex colors to AMS filaments")
        return output_path
    else:
        print("❌ Failed to create output")
        return None


def _colorize_manual(input_path, output_path, colors, blender, height, subdivide, bambu_map):
    """Handle manual color mode (user provides hex colors)."""
    import re

    hex_list = [c.strip().lstrip('#') for c in colors.split(',')]
    for h_val in hex_list:
        if not re.match(r'^[0-9A-Fa-f]{6}$', h_val):
            print(f"❌ Invalid color: '#{h_val}'. Use hex format: #FF0000,#00FF00")
            return None
    manual_rgb = np.array([[int(h_val[i:i+2], 16)/255 for i in (0, 2, 4)]
                           for h_val in hex_list])
    manual_lab = srgb_to_lab(manual_rgb)
    manual_selected = []
    for i, h_val in enumerate(hex_list):
        manual_selected.append({
            "rgb": manual_rgb[i],
            "lab": manual_lab[i],
            "family": f"manual_{i+1}",
            "group_names": [f"#{h_val.upper()}"],
            "pixel_count": 0,
            "percentage": 0,
        })
    print(f"🎨 Manual colors mode ({len(manual_selected)} colors)")
    for sc in manual_selected:
        rgb_int = (sc["rgb"] * 255).astype(int)
        print(f"   #{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}")

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
            _do_bambu_map(manual_selected, output_path)
        return output_path
    return None


def _do_bambu_map(selected, output_path):
    """Run Bambu filament mapping and print results."""
    palette = load_bambu_palette(_skill_dir)
    if palette:
        mappings = map_colors_to_filaments(selected, palette)
        map_path = write_bambu_map(mappings, output_path)
        print(f"   📋 Bambu map: {map_path}")
        for m in mappings:
            print(f"      {m['hex']} → {m['best']['line']} "
                  f"{m['best']['name']} (ΔE {m['best']['delta_e']})")
    else:
        print("   ⚠️ bambu_filament_colors.json not found, skip Bambu mapping")
