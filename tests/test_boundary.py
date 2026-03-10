"""Test color boundary preservation in the colorize package's quantization logic."""

import colorsys
from collections import defaultdict

import numpy as np
import pytest


def hex_to_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hsv(r, g, b):
    return colorsys.rgb_to_hsv(r, g, b)


def nearest_color_idx(r, g, b, filament_hsv):
    hsv = rgb_to_hsv(r, g, b)
    best, best_dist = 0, float('inf')
    for i, fhsv in enumerate(filament_hsv):
        dh = min(abs(hsv[0] - fhsv[0]), 1.0 - abs(hsv[0] - fhsv[0]))
        ds = abs(hsv[1] - fhsv[1])
        dv = abs(hsv[2] - fhsv[2])
        dist = dh * 3.0 + ds * 1.0 + dv * 0.5
        if dist < best_dist:
            best_dist = dist
            best = i
    return best


def make_test_texture(w, h, colors_rgb):
    pixels = np.zeros((h * w, 3))
    band_w = w // len(colors_rgb)
    for i, (r, g, b) in enumerate(colors_rgb):
        x_start = i * band_w
        x_end = (i + 1) * band_w if i < len(colors_rgb) - 1 else w
        for y in range(h):
            for x in range(x_start, x_end):
                pixels[y * w + x] = [r, g, b]
    return pixels


def simulate_face_assignment(face_uvs_list, quantized, w, h, use_multipoint=False):
    face_colors, face_is_boundary = [], []

    def sample_uv(uv_x, uv_y):
        px = int(uv_x * (w - 1)) % w
        py = int(uv_y * (h - 1)) % h
        idx = py * w + px
        return quantized[idx] if 0 <= idx < len(quantized) else 0

    for uvs in face_uvs_list:
        votes = defaultdict(int)
        for u, v in uvs:
            votes[sample_uv(u, v)] += 1
        if use_multipoint and uvs:
            cx = sum(u for u, v in uvs) / len(uvs)
            cy = sum(v for u, v in uvs) / len(uvs)
            votes[sample_uv(cx, cy)] += 2
            for i in range(len(uvs)):
                j = (i + 1) % len(uvs)
                mx = (uvs[i][0] + uvs[j][0]) * 0.5
                my = (uvs[i][1] + uvs[j][1]) * 0.5
                votes[sample_uv(mx, my)] += 1
        color = max(votes, key=votes.get) if votes else 0
        face_colors.append(color)
        total = sum(votes.values())
        top = max(votes.values()) if votes else 0
        face_is_boundary.append(total > 0 and (top / total) < 0.8)
    return face_colors, face_is_boundary


def simulate_cleanup(face_colors, adjacency, face_is_boundary, rounds=3, boundary_aware=False):
    fc = list(face_colors)
    for _ in range(rounds):
        changed = 0
        for fi in range(len(fc)):
            if boundary_aware and face_is_boundary[fi]:
                continue
            neighbors = [fc[nf] for nf in adjacency[fi]]
            if not neighbors:
                continue
            votes = defaultdict(int)
            for nc in neighbors:
                votes[nc] += 1
            dominant = max(votes, key=votes.get)
            threshold = 0.75 if boundary_aware else 0.6
            if votes[dominant] / len(neighbors) > threshold and dominant != fc[fi]:
                fc[fi] = dominant
                changed += 1
        if changed == 0:
            break
    return fc


class TestBoundaryPreservation:
    """Red|Blue vertical split — multi-point sampling should preserve boundary."""

    def _setup_texture(self):
        colors = ["#FF0000", "#0000FF"]
        filament_rgb = [hex_to_rgb(c) for c in colors]
        filament_hsv = [rgb_to_hsv(*c) for c in filament_rgb]
        W, H = 100, 100
        pixels = make_test_texture(W, H, filament_rgb)
        quantized = np.array([nearest_color_idx(*p, filament_hsv) for p in pixels], dtype=np.int32)
        return W, H, quantized

    def test_texture_quantized_correctly(self):
        W, H, quantized = self._setup_texture()
        assert quantized[0] == 0
        assert quantized[99] == 1

    def test_new_method_equal_or_better(self):
        W, H, quantized = self._setup_texture()
        face_uvs = []
        for i in range(10):
            x0, x1 = i * 0.1, (i + 1) * 0.1
            face_uvs.append([(x0, 0.4), (x1, 0.4), (x1, 0.6), (x0, 0.6)])

        old_colors, old_bnd = simulate_face_assignment(face_uvs, quantized, W, H, False)
        new_colors, new_bnd = simulate_face_assignment(face_uvs, quantized, W, H, True)

        adjacency = {i: [j for j in [i - 1, i + 1] if 0 <= j < 10] for i in range(10)}
        old_after = simulate_cleanup(old_colors, adjacency, old_bnd, 3, False)
        new_after = simulate_cleanup(new_colors, adjacency, new_bnd, 3, True)

        expected = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
        old_err = sum(1 for i in range(10) if old_after[i] != expected[i])
        new_err = sum(1 for i in range(10) if new_after[i] != expected[i])
        assert new_err <= old_err, f"New boundary errors ({new_err}) > old ({old_err})"


class TestSmallIslandProtection:
    """Boundary-aware cleanup should not erase small islands at color borders."""

    def test_boundary_preserved(self):
        fc = [0, 0, 1, 1, 1]
        fb = [False, True, True, False, False]
        adj = {0: [1], 1: [0, 2], 2: [1, 3], 3: [2, 4], 4: [3]}

        new = simulate_cleanup(fc, adj, fb, 3, True)
        assert new[1] == 0, f"Boundary face 1 should stay 0, got {new[1]}"
        assert new[2] == 1, f"Boundary face 2 should stay 1, got {new[2]}"


class TestHSVQuantization:
    """HSV-weighted nearest-color assignment accuracy."""

    @pytest.fixture
    def filament_hsv(self):
        colors = ["#FF0000", "#800000", "#0000FF"]
        frgb = [hex_to_rgb(c) for c in colors]
        return [rgb_to_hsv(*c) for c in frgb]

    @pytest.mark.parametrize("rgb,expected,desc", [
        ((1.0, 0.0, 0.0), 0, "pure red -> bright red"),
        ((0.5, 0.0, 0.0), 1, "dark red -> dark red"),
        ((0.0, 0.0, 1.0), 2, "pure blue -> blue"),
        ((0.8, 0.1, 0.1), 0, "mostly red -> bright red"),
        ((0.3, 0.0, 0.0), 1, "very dark red -> dark red"),
    ])
    def test_quantization(self, filament_hsv, rgb, expected, desc):
        result = nearest_color_idx(*rgb, filament_hsv)
        assert result == expected, f"{desc}: got {result}, expected {expected}"
