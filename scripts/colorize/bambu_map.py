"""Bambu Lab filament color mapping: match detected colors to real filaments."""

import os

import numpy as np

from bambu_studio_ai.filaments import PLAIN_FINISHES, filament_colors

from .color_science import srgb_to_lab


def load_bambu_palette(finishes=PLAIN_FINISHES, materials=("PLA",)):
    """Bambu Lab filament colours to match against, from assets/filaments.json.

    Only single-colour spools of the given materials and finishes compete. The default,
    opaque and matte PLA, keeps silk, translucent and glow filaments out: they look
    different from the flat colour they match, so they are offered only when asked for.
    Support materials are never offered.
    Returns list of dicts: {line, name, hex, finish, rgb, lab}.
    """
    palette = []
    for color in filament_colors():
        if (color.support or color.pattern != "solid"
                or color.material not in materials or color.finish not in finishes):
            continue
        rgb = np.array([int(color.hex[i:i + 2], 16) / 255.0 for i in (1, 3, 5)])
        palette.append({
            "line": color.line,
            "name": color.name,
            "hex": color.hex,
            "finish": color.finish,
            "rgb": rgb,
            "lab": srgb_to_lab(rgb[np.newaxis, :])[0],
        })
    return palette


def map_colors_to_filaments(selected_colors, palette):
    """Map each selected color to closest Bambu filament by CIELAB distance.
    Returns list of mapping dicts with best match and alternatives.
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
            alternatives.append({
                "line": alt["line"], "name": alt["name"],
                "hex": alt["hex"], "delta_e": round(alt_delta, 1),
            })
        rgb_int = (sc["rgb"] * 255).astype(int)
        hex_c = f"#{rgb_int[0]:02X}{rgb_int[1]:02X}{rgb_int[2]:02X}"
        mappings.append({
            "color_idx": i + 1,
            "hex": hex_c,
            "family": sc["family"],
            "percentage": sc["percentage"],
            "best": {
                "line": best["line"], "name": best["name"],
                "hex": best["hex"], "delta_e": round(delta_e, 1),
            },
            "alternatives": alternatives,
        })
    return mappings


def write_bambu_map(mappings, output_path):
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
    with open(map_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return map_path
