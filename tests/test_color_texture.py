"""Reading colour from models: the right texture, the right texels, the right axes.

Each test is a regression test for a bug in the Blender pipeline this replaced.
"""

import numpy as np
import pytest
import trimesh

from bambu_studio_ai.color import ColorizeOptions, ModelLoadError, NoColourError, colorize
from bambu_studio_ai.color.load import load_model
from bambu_studio_ai.color.sampling import sample_surface
from glb_builder import bands, box, grid, png, seamed_sphere, textured, write_glb

RED, GREEN, BLUE = (200, 30, 30), (30, 180, 40), (30, 60, 200)


def face_colours(path):
    """Mean sampled sRGB (0-255) of every triangle."""
    model = load_model(path)
    samples = sample_surface(model)
    counts = np.bincount(samples.face, minlength=len(model.faces))[:, None]
    sums = np.stack([np.bincount(samples.face, samples.rgb[:, c], len(model.faces)) for c in range(3)], 1)
    return model, np.round(sums / counts * 255)


def test_base_colour_texture_is_used_when_a_normal_map_comes_first(tmp_path):
    # Regression: v2.0 took the first image in the file, so models came out #8080FF.
    normal_map = np.full((8, 8, 3), (128, 128, 255), np.uint8)
    corners, faces, uv = box((0.02, 0.02, 0.02))
    material = textured(1)
    material["normalTexture"] = {"index": 0}
    path = write_glb(tmp_path / "normal_first.glb", [{"positions": corners, "faces": faces, "uv": uv, "material": 0}],
                     [material], [png(normal_map), png(bands([RED, BLUE]))])
    result = colorize(path)
    assert sorted(result.palette.hex) == ["#1E3CC8", "#C81E1E"]


def test_uv_of_exactly_one_samples_the_far_edge(tmp_path):
    # Regression: int(u * width) % width sent u = 1.0 to column 0, so blue vanished.
    corners, faces, uv = box((0.04, 0.04, 0.04))
    path = write_glb(tmp_path / "cube.glb", [{"positions": corners, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(bands([RED, GREEN, BLUE]))])
    model, colours = face_colours(path)
    right_side = np.all(model.uv[model.faces][:, :, 0] == 1.0, axis=1)
    assert right_side.sum() == 2
    assert (colours[right_side] == BLUE).all()
    assert "#1E3CC8" in colorize(path).palette.hex


def test_texture_rows_are_not_mirrored(tmp_path):
    # Regression: the curvature mask flipped v and protected the mirror-image rows.
    image = np.zeros((64, 64, 3), np.uint8)
    image[:32] = RED  # glTF v = 0 is the top row of the image
    image[32:] = BLUE
    quad = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], float) * 0.01
    positions = np.concatenate([quad, quad + [0.02, 0, 0]])
    faces = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
    uv = np.array([[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4], [0.1, 0.6], [0.4, 0.6], [0.4, 0.9], [0.1, 0.9]])
    path = write_glb(tmp_path / "rows.glb", [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(image)])
    _, colours = face_colours(path)
    assert (colours[:2] == RED).all()
    assert (colours[2:] == BLUE).all()


@pytest.mark.parametrize("alpha_mode", [None, "BLEND", "MASK"])
def test_transparent_texels_do_not_count(tmp_path, alpha_mode):
    # Regression: alpha was dropped, so an invisible band took an AMS slot.
    positions, faces, uv = grid(12, width=0.03)
    texture = bands([RED, GREEN, BLUE], alpha=[255, 255, 0])
    path = write_glb(tmp_path / "rgba.glb", [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0, alpha_mode=alpha_mode)], [png(texture)])
    result = colorize(path)
    assert sorted(result.palette.hex) == ["#1EB428", "#C81E1E"]
    assert result.area_share.sum() == pytest.approx(1.0)  # the invisible band still gets a filament


def test_an_all_transparent_alpha_channel_is_treated_as_junk(tmp_path):
    positions, faces, uv = grid(6, width=0.03)
    texture = bands([RED, BLUE], alpha=[0, 0])
    path = write_glb(tmp_path / "alpha0.glb", [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(texture)])
    result = colorize(path)
    assert sorted(result.palette.hex) == ["#1E3CC8", "#C81E1E"]
    assert any("alpha channel is ignored" in w for w in result.warnings)


def test_atlas_padding_never_counts(tmp_path):
    # Regression: statistics over the whole image made unused black padding colour #1.
    image = np.zeros((64, 64, 3), np.uint8)  # black everywhere no triangle maps to
    image[:, 40:][:32] = RED
    image[:, 40:][32:] = GREEN
    positions, faces, uv = grid(10, width=0.03)
    uv = np.stack([0.65 + uv[:, 0] * 0.3, uv[:, 1]], 1)
    path = write_glb(tmp_path / "atlas.glb", [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(image)])
    result = colorize(path)
    assert sorted(result.palette.hex) == ["#1EB428", "#C81E1E"]


def test_mid_greys_keep_their_value(tmp_path):
    # Regression: sRGB was written through Blender's linear accessor; mid-greys came out white.
    greys = [(0x33,) * 3, (0x7B,) * 3, (0xF0,) * 3]
    positions, faces, uv = grid(12, width=0.03)
    path = write_glb(tmp_path / "greys.glb", [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(bands(greys))])
    assert sorted(colorize(path).palette.hex) == ["#333333", "#7B7B7B", "#F0F0F0"]


def test_base_colour_factor_tints_the_texture_in_linear_light(tmp_path):
    positions, faces, uv = grid(4, width=0.02)
    white = np.full((8, 8, 3), 255, np.uint8)
    path = write_glb(tmp_path / "tint.glb", [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0, factor=[0.5, 0.5, 0.5, 1.0])], [png(white)])
    result = colorize(path)
    assert result.palette.hex == ["#BCBCBC"]  # linear 0.5 is sRGB 188
    assert any("only one colour" in w for w in result.warnings)


def test_untextured_materials_use_their_colour(tmp_path):
    corners, faces, _ = box((0.02, 0.02, 0.02))
    materials = [{"pbrMetallicRoughness": {"baseColorFactor": [1, 0, 0, 1]}},
                 {"pbrMetallicRoughness": {"baseColorFactor": [0, 0, 1, 1]}}]
    primitives = [{"positions": corners, "faces": faces, "material": 0},
                  {"positions": corners + [0.03, 0, 0], "faces": faces, "material": 1}]
    path = write_glb(tmp_path / "flat.glb", primitives, materials)
    result = colorize(path)
    assert sorted(result.palette.hex) == ["#0000FF", "#FF0000"]
    np.testing.assert_allclose(result.area_share, [0.5, 0.5])


def test_vertex_colours_are_linear_in_gltf(tmp_path):
    positions, faces, _ = grid(8, width=0.02)
    colours = np.ones((len(positions), 4))
    left = positions[:, 0] < 0.0099
    colours[left, :3] = 0.21404  # linear light for sRGB 0.5 (#808080)
    colours[~left, :3] = (1.0, 0.0, 0.0)
    path = write_glb(tmp_path / "vc.glb", [{"positions": positions, "faces": faces, "colors": colours}])
    assert sorted(colorize(path).palette.hex) == ["#808080", "#FF0000"]


def test_output_is_z_up_in_millimetres_and_node_transforms_apply(tmp_path):
    # Regression: the OBJ was exported Y-up, so a 60 mm tall model imported lying down.
    corners, faces, uv = box((0.010, 0.060, 0.020))  # glTF: metres, Y up
    texture = [png(bands([RED, BLUE]))]
    primitive = {"positions": corners, "faces": faces, "uv": uv, "material": 0}
    plain = write_glb(tmp_path / "tall.glb", [primitive], [textured(0)], texture)
    assert colorize(plain).size_mm == pytest.approx((10.0, 20.0, 60.0))
    scaled = np.diag([2.0, 2.0, 2.0, 1.0])
    doubled = write_glb(tmp_path / "tall2.glb", [primitive], [textured(0)], texture, node_matrices=[scaled])
    assert colorize(doubled).size_mm == pytest.approx((20.0, 40.0, 120.0))
    assert colorize(plain, ColorizeOptions(height_mm=45)).size_mm == pytest.approx((7.5, 15.0, 45.0))


def test_seamed_sphere_does_not_crash_and_comes_out_welded(tmp_path):
    # Regression: trimesh merged the seam vertices, then indices overflowed (IndexError).
    positions, faces, uv = seamed_sphere()
    image = np.zeros((64, 64, 3), np.uint8)
    image[:32], image[32:] = RED, BLUE  # northern hemisphere red, southern blue
    path = write_glb(tmp_path / "sphere.glb", [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(image)])
    result = colorize(path)
    assert sorted(result.palette.hex) == ["#1E3CC8", "#C81E1E"]
    assert len(result.vertices) < len(positions)  # seam and pole duplicates joined
    assert trimesh.Trimesh(result.vertices, result.faces, process=False).is_watertight
    north = result.vertices[result.faces].mean(axis=1)[:, 2] > 0
    red = result.palette.hex.index("#C81E1E")
    assert (result.labels[north] == red).mean() > 0.95


def test_model_without_colour_is_refused(tmp_path):
    corners, faces, _ = box()
    path = write_glb(tmp_path / "grey.glb", [{"positions": corners, "faces": faces}])
    with pytest.raises(NoColourError, match="no base-colour texture"):
        colorize(path)


def test_unsupported_or_missing_file_is_a_load_error(tmp_path):
    (tmp_path / "model.stl").write_text("solid x\nendsolid x\n")
    with pytest.raises(ModelLoadError, match="unsupported format"):
        colorize(tmp_path / "model.stl")
    with pytest.raises(ModelLoadError, match="not found"):
        colorize(tmp_path / "missing.glb")
