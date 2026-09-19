"""Palette choice and per-triangle labels (bambu_studio_ai.color.palette / segment)."""

import numpy as np
import pytest

from bambu_studio_ai.color import ColorizeOptions, ColorsLostError, colorize
from bambu_studio_ai.color.lab import delta_e_2000, srgb_to_lab
from bambu_studio_ai.color.segment import UNLABELLED, face_adjacency, fill_unlabelled, smooth, weld
from glb_builder import bands, grid, png, textured, write_glb

YELLOW_LIGHT, YELLOW_DARK = (235, 205, 60), (215, 180, 35)
BROWN, BLACK = (110, 60, 25), (15, 15, 15)


def plate(tmp_path, image, cells=100, name="plate.glb"):
    """A flat square whose UVs map evenly onto its area, so texture share == surface share."""
    positions, faces, uv = grid(cells, width=0.05)
    return write_glb(tmp_path / name, [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(image)])


def face_with_eye(size=512, eye_share=0.003):
    """Shaded yellow, a brown band over 30 % of the width, and a round black eye."""
    ramp = np.linspace(0, 1, size)[:, None, None]
    image = (np.array(YELLOW_LIGHT) * (1 - ramp) + np.array(YELLOW_DARK) * ramp) * np.ones((size, size, 3))
    image[:, : int(0.3 * size)] = BROWN
    radius = np.sqrt(eye_share / np.pi) * size
    rows, columns = np.mgrid[:size, :size]
    image[(rows - 0.4 * size) ** 2 + (columns - 0.7 * size) ** 2 <= radius**2] = BLACK
    return image.astype(np.uint8)


def test_ramp_premise_is_one_colour_to_a_printer():
    assert delta_e_2000(srgb_to_lab(np.array(YELLOW_LIGHT) / 255), srgb_to_lab(np.array(YELLOW_DARK) / 255)) < 12


def test_small_distinct_eye_keeps_its_own_filament(tmp_path):
    result = colorize(plate(tmp_path, face_with_eye()))
    assert len(result.palette) == 3  # shading merged, eye kept
    lab = result.palette.lab
    eye = int(np.argmin(lab[:, 0]))
    assert lab[eye, 0] < 15  # the darkest colour is the black eye
    assert result.area_share[eye] == pytest.approx(0.003, abs=0.0015)


def test_features_below_min_area_merge_away(tmp_path):
    result = colorize(plate(tmp_path, face_with_eye()), ColorizeOptions(min_area=0.01))
    assert len(result.palette) == 2
    assert np.all(result.palette.lab[:, 0] > 15)


def test_max_colors_is_respected_and_nothing_is_lost(tmp_path):
    six = [(230, 30, 30), (30, 160, 40), (30, 60, 200), (240, 220, 40), (20, 20, 20), (240, 240, 240)]
    result = colorize(plate(tmp_path, bands(six, size=120), cells=60), ColorizeOptions(max_colors=4))
    assert len(result.palette) == 4
    assert result.area_share.sum() == pytest.approx(1.0)
    assert (result.area_share > 0).all()
    # Colours that had to share a filament keep the dominant one, not a blend of both.
    inputs = srgb_to_lab(np.array(six) / 255)
    nearest = delta_e_2000(result.palette.lab[:, None, :], inputs[None, :, :]).min(axis=1)
    assert (nearest < 2).all()


def test_forced_palette_keeps_order_and_warns_about_unused_colours(tmp_path):
    image = bands([(200, 30, 30), (30, 60, 200)], size=64)
    forced = ("#FFFFFF", "#1E3CC8", "#C81E1E")
    result = colorize(plate(tmp_path, image, cells=20), ColorizeOptions(colors=forced))
    assert result.palette.hex == list(forced)
    assert result.area_share[0] == 0
    assert result.area_share[1:] == pytest.approx([0.5, 0.5])
    assert any("#FFFFFF" in w for w in result.warnings)


def test_colour_finer_than_the_mesh_is_reported_as_lost(tmp_path):
    # Regression: v2.0 printed success although a selected colour never reached the model.
    image = np.zeros((200, 200, 3), np.uint8)
    image[:, :95], image[:, 95:105], image[:, 105:] = (200, 30, 30), (20, 20, 20), (30, 60, 200)
    path = plate(tmp_path, image, cells=1)  # two triangles; the black line crosses both
    with pytest.raises(ColorsLostError) as error:
        colorize(path)
    assert error.value.lost == ["#141414"]
    assert sorted(error.value.kept) == ["#1E3CC8", "#C81E1E"]
    assert "--colors" in str(error.value)


def _strip(cells=10):
    positions, faces, _ = grid(cells)
    mesh = weld(positions, faces)
    return mesh, face_adjacency(mesh.faces)


def test_smoothing_removes_isolated_triangles():
    mesh, pairs = _strip()  # 10 x 10 cells; triangle i and i + 100 share cell i
    labels = np.zeros(len(mesh.faces), np.int64)
    band = np.r_[50:70, 150:170]  # both triangles of two full rows of cells
    labels[band] = 1
    labels[22] = 1  # one speck, far from the band
    smoothed = smooth(labels, pairs, 2, passes=1)
    assert smoothed[22] == 0
    assert (smoothed[band] == 1).mean() > 0.9


def test_smoothing_never_removes_a_colour_entirely():
    mesh, pairs = _strip()
    labels = np.zeros(len(mesh.faces), np.int64)
    labels[37] = 1  # the only triangle of colour 1
    assert smooth(labels, pairs, 2, passes=3)[37] == 1


def test_unlabelled_triangles_take_their_neighbours_colour():
    mesh, pairs = _strip()
    labels = np.zeros(len(mesh.faces), np.int64)
    labels[100:] = 1
    labels[95:105] = UNLABELLED
    filled = fill_unlabelled(labels, pairs, 2)
    assert (filled != UNLABELLED).all()
    assert set(np.unique(filled[95:105])) <= {0, 1}
