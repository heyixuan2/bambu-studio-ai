"""Tests for colorize.selection — color selection algorithms."""

import numpy as np
import pytest

from colorize.color_science import srgb_to_lab, classify_pixels
from colorize.selection import greedy_select_colors, assign_pixels


class TestGreedySelect:
    def _make_bicolor_texture(self, n=10000):
        """Half red, half blue pixels."""
        rng = np.random.RandomState(0)
        red = np.clip(rng.normal(0.8, 0.05, (n // 2, 3)) * [1, 0.1, 0.1], 0, 1)
        blue = np.clip(rng.normal(0.8, 0.05, (n // 2, 3)) * [0.1, 0.1, 1], 0, 1)
        return np.vstack([red, blue]).astype(np.float32)

    def test_finds_two_colors(self):
        pixels = self._make_bicolor_texture()
        pixel_lab = srgb_to_lab(pixels)
        families = classify_pixels(pixels)
        selected = greedy_select_colors(pixels, pixel_lab, families, max_colors=4)
        assert len(selected) >= 2, "Should find at least 2 colors"

    def test_respects_max_colors(self):
        pixels = self._make_bicolor_texture()
        pixel_lab = srgb_to_lab(pixels)
        families = classify_pixels(pixels)
        selected = greedy_select_colors(pixels, pixel_lab, families, max_colors=1)
        assert len(selected) == 1

    def test_output_structure(self):
        pixels = self._make_bicolor_texture()
        pixel_lab = srgb_to_lab(pixels)
        families = classify_pixels(pixels)
        selected = greedy_select_colors(pixels, pixel_lab, families, max_colors=4)
        for sc in selected:
            assert "rgb" in sc
            assert "lab" in sc
            assert "family" in sc
            assert "percentage" in sc
            assert sc["percentage"] > 0


class TestAssignPixels:
    def test_assigns_all_pixels(self):
        pixels = np.array([
            [1, 0, 0], [1, 0, 0],
            [0, 0, 1], [0, 0, 1],
        ], dtype=np.float32)
        pixel_lab = srgb_to_lab(pixels)
        selected = [
            {"rgb": np.array([1, 0, 0]), "lab": srgb_to_lab(np.array([[1, 0, 0]]))[0],
             "family": "red"},
            {"rgb": np.array([0, 0, 1]), "lab": srgb_to_lab(np.array([[0, 0, 1]]))[0],
             "family": "blue"},
        ]
        labels = assign_pixels(pixel_lab, selected)
        assert labels.shape == (4,)
        assert labels[0] == labels[1]  # both red
        assert labels[2] == labels[3]  # both blue
        assert labels[0] != labels[2]  # red ≠ blue
