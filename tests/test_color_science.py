"""Tests for colorize.color_science — sRGB↔LAB and pixel classification."""

import numpy as np
import pytest

from colorize.color_science import srgb_to_lab, classify_pixels, name_from_rgb


class TestSrgbToLab:
    def test_black(self):
        lab = srgb_to_lab(np.array([[0.0, 0.0, 0.0]]))
        assert lab.shape == (1, 3)
        assert abs(lab[0, 0]) < 1.0  # L* ≈ 0

    def test_white(self):
        lab = srgb_to_lab(np.array([[1.0, 1.0, 1.0]]))
        assert abs(lab[0, 0] - 100.0) < 1.0  # L* ≈ 100

    def test_pure_red(self):
        lab = srgb_to_lab(np.array([[1.0, 0.0, 0.0]]))
        assert lab[0, 0] > 40  # L* mid-range
        assert lab[0, 1] > 50  # a* positive (red)

    def test_pure_green(self):
        lab = srgb_to_lab(np.array([[0.0, 1.0, 0.0]]))
        assert lab[0, 1] < -50  # a* negative (green)

    def test_batch(self):
        rgb = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
        lab = srgb_to_lab(rgb)
        assert lab.shape == (3, 3)
        # Red and green should differ significantly in a*
        assert abs(lab[0, 1] - lab[1, 1]) > 100


class TestClassifyPixels:
    def _classify_single(self, r, g, b):
        return int(classify_pixels(np.array([[r, g, b]], dtype=np.float32))[0])

    def test_pure_black(self):
        assert self._classify_single(0, 0, 0) == 0  # black

    def test_pure_white(self):
        assert self._classify_single(1, 1, 1) == 3  # white

    def test_pure_red(self):
        assert self._classify_single(1, 0, 0) == 4  # red

    def test_pure_green(self):
        assert self._classify_single(0, 1, 0) == 7  # green

    def test_pure_blue(self):
        assert self._classify_single(0, 0, 1) == 9  # blue

    def test_yellow(self):
        assert self._classify_single(1, 1, 0) == 6  # yellow

    def test_dark_gray(self):
        assert self._classify_single(0.3, 0.3, 0.3) == 1  # dark_gray

    def test_light_gray(self):
        assert self._classify_single(0.7, 0.7, 0.7) == 2  # light_gray

    def test_very_dark_chromatic_goes_black(self):
        # Very dark pixels (v < 0.1) should be classified as achromatic
        fid = self._classify_single(0.08, 0.02, 0.02)
        assert fid == 0  # black (achromatic)

    def test_batch_shape(self):
        pixels = np.random.rand(1000, 3).astype(np.float32)
        families = classify_pixels(pixels)
        assert families.shape == (1000,)
        assert families.dtype == np.int32
        assert all(0 <= f <= 11 for f in families)


class TestNameFromRgb:
    def test_red(self):
        assert name_from_rgb(np.array([1.0, 0.0, 0.0])) == "red"

    def test_white(self):
        assert name_from_rgb(np.array([1.0, 1.0, 1.0])) == "white"

    def test_black(self):
        assert name_from_rgb(np.array([0.0, 0.0, 0.0])) == "black"

    def test_blue(self):
        assert name_from_rgb(np.array([0.0, 0.0, 1.0])) == "blue"
