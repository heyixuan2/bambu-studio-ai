"""Color selection algorithms: greedy HSV, k-means, and hybrid."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import ASSIGN_CHUNK_SIZE, ACHROMATIC_BLOCK_DIST

from .color_science import (
    FAMILY_NAMES, FAMILY_GROUPS, ACHROMATIC_FAMILIES,
    srgb_to_lab, name_from_rgb,
)


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


def greedy_select_colors(pixels, pixel_lab, pixel_families, max_colors=8,
                         min_pct=0.001, no_merge=False):
    """Greedy select representative colors by largest pixel family first."""
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
        if best_count / N < min_pct:
            break

        group = [best_fid] if no_merge else FAMILY_GROUPS.get(best_fid, [best_fid])
        group_mask = np.zeros(N, dtype=bool)
        for gf in group:
            group_mask |= (pixel_families == gf)
        total = int(np.sum(group_mask))
        if total == 0:
            break

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


def kmeans_select_colors(pixels, pixel_lab, max_colors=8, min_pct=0.001):
    """Direct k-means in full CIELAB space — best for sub-color detail."""
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
    km = KMeans(n_clusters=max_colors, init='k-means++', n_init=5,
                random_state=42, max_iter=100)
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
            "family": name_from_rgb(median_rgb),
            "group_names": [name_from_rgb(median_rgb)],
            "pixel_count": count,
            "percentage": count / Ns * 100,
        })
    selected.sort(key=lambda x: -x["percentage"])
    return selected


def hybrid_select_colors(pixels, pixel_lab, pixel_families, max_colors=8,
                         min_pct=0.001):
    """Hybrid HSV + k-means: HSV families guarantee hue separation, k-means
    splits large families into sub-shades when budget allows."""
    from sklearn.cluster import KMeans

    N = len(pixels)

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
        selected = family_data[:max_colors]
    else:
        selected = list(family_data)
        slots_left = max_colors - n_families

        for fd in sorted(family_data, key=lambda x: -x["pixel_count"]):
            if slots_left <= 0:
                break
            fmask = fd["mask"]
            fcount = fd["pixel_count"]
            if fcount < 2000:
                continue

            f_lab = pixel_lab[fmask]
            f_rgb = pixels[fmask]
            if len(f_lab) > 100000:
                rng = np.random.RandomState(42)
                idx = rng.choice(len(f_lab), 100000, replace=False)
                f_lab_sub = f_lab[idx]
                f_rgb_sub = f_rgb[idx]
            else:
                f_lab_sub = f_lab
                f_rgb_sub = f_rgb

            km = KMeans(n_clusters=2, init='k-means++', n_init=5,
                        random_state=42, max_iter=50)
            km.fit(f_lab_sub)

            center_dist = np.sqrt(np.sum(
                (km.cluster_centers_[0] - km.cluster_centers_[1]) ** 2))
            if center_dist < 10:
                continue

            full_labels = km.predict(f_lab)
            count_before = len(selected)
            selected = [s for s in selected if s.get("fid") != fd["fid"]]

            for sub_id in [0, 1]:
                sub_mask_full = full_labels == sub_id
                sub_count = int(np.sum(sub_mask_full))
                if sub_count < N * min_pct:
                    continue
                med_rgb, med_lab = _representative_color(
                    f_rgb[sub_mask_full], f_lab[sub_mask_full])
                selected.append({
                    "rgb": med_rgb,
                    "lab": med_lab,
                    "family": fd["family"],
                    "group_names": [fd["family"]],
                    "pixel_count": sub_count,
                    "percentage": sub_count / N * 100,
                })
            net_added = len(selected) - count_before
            slots_left -= max(net_added, 0)

    for s in selected:
        s.pop("mask", None)
        s.pop("fid", None)

    selected.sort(key=lambda x: -x["percentage"])
    if len(selected) > max_colors:
        selected = selected[:max_colors]
    return selected


def assign_pixels(pixel_lab, selected_colors, pixel_families=None, pixels=None):
    """Assign each pixel to nearest selected color by CIELAB distance.

    Achromatic constraint: chromatic pixels (HSV family >= 4) cannot be
    assigned to achromatic selected colors, preventing dark-but-colored shadow
    pixels from being pulled into black.
    """
    N = len(pixel_lab)
    sel_lab = np.array([sc["lab"] for sc in selected_colors])
    labels = np.zeros(N, dtype=np.int32)
    CHUNK = ASSIGN_CHUNK_SIZE

    achro_mask_sel = np.array([
        sc["family"] in ACHROMATIC_FAMILIES for sc in selected_colors
    ])
    has_achro_constraint = (pixel_families is not None and
                            np.any(achro_mask_sel))

    for i in range(0, N, CHUNK):
        chunk = pixel_lab[i:i+CHUNK]
        dist = np.sum((chunk[:, None, :] - sel_lab[None, :, :]) ** 2, axis=2)

        if has_achro_constraint:
            chunk_families = pixel_families[i:i+CHUNK]
            chunk_pixels = pixels[i:i+CHUNK] if pixels is not None else None
            chromatic_px = chunk_families >= 4
            if chunk_pixels is not None:
                v_values = chunk_pixels.max(axis=1)
                very_dark = v_values < 0.2
                chromatic_px = chromatic_px & ~very_dark
            dist[np.ix_(chromatic_px, achro_mask_sel)] = ACHROMATIC_BLOCK_DIST

        labels[i:i+CHUNK] = np.argmin(dist, axis=1)

    return labels
