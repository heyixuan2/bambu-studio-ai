"""Host-side model handling for previews: measuring, colour, and converting for Blender."""

from pathlib import Path

import numpy as np
import pytest
import render_models
import trimesh

from bambu_studio_ai.render import meshes
from bambu_studio_ai.render.errors import ModelError


def _analyze_extents(path):
    """How analyze.py measures a file (scripts/analyze.py: trimesh.load(..., force="mesh"))."""
    return tuple(trimesh.load(str(path), force="mesh").extents)


@pytest.mark.parametrize(
    "writer",
    [render_models.write_stl, render_models.write_3mf, render_models.write_two_color_glb,
     render_models.write_textured_glb, render_models.write_y_tall_glb],
)
def test_dimensions_match_analyze(tmp_path, writer):
    suffix = {"write_stl": ".stl", "write_3mf": ".3mf"}.get(writer.__name__, ".glb")
    path = writer(tmp_path / f"model{suffix}")
    assert meshes.load_model(path).dimensions == pytest.approx(_analyze_extents(path))


def test_glb_keeps_file_axes_z_up(tmp_path):
    # Regression: Blender's glTF importer stood Y-up files upright, so preview said
    # 20 x 10 x 50 where analyze.py and Bambu Studio say 20 x 50 x 10.
    path = render_models.write_y_tall_glb(tmp_path / "slab.glb")
    assert meshes.load_model(path).dimensions == pytest.approx((20, 50, 10))


def test_3mf_parts_and_size(tmp_path):
    model = meshes.load_model(render_models.write_3mf(tmp_path / "two.3mf"))
    assert len(model.parts) == 2
    assert model.faces == 24
    assert model.dimensions == pytest.approx((40, 20, 30))
    assert model.color_kind == "none"


def test_material_colours_are_kept_per_part(tmp_path):
    model = meshes.load_model(render_models.write_two_color_glb(tmp_path / "two.glb"))
    assert model.color_kind == "material"
    colours = {tuple(part.corner_rgb[0, 0]) for part in model.parts}
    assert colours == {render_models.RED[:3], render_models.GREEN[:3]}


def test_texture_is_kept_with_uvs(tmp_path):
    model = meshes.load_model(render_models.write_textured_glb(tmp_path / "ball.glb"))
    (part,) = model.parts
    assert model.color_kind == "texture"
    assert part.texture.shape == (64, 64, 3)
    assert part.corner_uv.shape == (len(part.faces), 3, 2)


def test_blender_native_formats_are_passed_through(tmp_path):
    path = render_models.write_stl(tmp_path / "box.stl")
    assert meshes.blender_input(path, meshes.load_model(path), tmp_path) == path


def test_3mf_is_converted_to_ply_with_the_same_geometry(tmp_path):
    path = render_models.write_3mf(tmp_path / "two.3mf")
    model = meshes.load_model(path)
    converted = meshes.blender_input(path, model, tmp_path)
    assert converted == tmp_path / "model.ply"
    reloaded = trimesh.load(str(converted), force="mesh")
    assert tuple(reloaded.extents) == pytest.approx(model.dimensions)
    assert len(reloaded.faces) == model.faces
    assert reloaded.visual.kind is None  # no colour in, no colour out


def test_coloured_model_is_converted_with_vertex_colours(tmp_path):
    model = meshes.load_model(render_models.write_two_color_glb(tmp_path / "two.glb"))
    converted = meshes.blender_input(Path("two.3mf"), model, tmp_path)
    reloaded = trimesh.load(str(converted), force="mesh")
    colours = {tuple(c) for c in np.asarray(reloaded.visual.vertex_colors)[:, :3]}
    assert colours == {render_models.RED[:3], render_models.GREEN[:3]}


def test_textured_model_is_converted_to_glb(tmp_path):
    model = meshes.load_model(render_models.write_textured_glb(tmp_path / "ball.glb"))
    converted = meshes.blender_input(Path("ball.3mf"), model, tmp_path)
    assert converted.suffix == ".glb"
    assert meshes.load_model(converted).color_kind == "texture"


def test_unreadable_file_is_a_model_error(tmp_path):
    bad = tmp_path / "broken.3mf"
    bad.write_bytes(b"not a zip file")
    with pytest.raises(ModelError, match="could not read broken.3mf"):
        meshes.load_model(bad)


def test_file_without_triangles_is_a_model_error(tmp_path):
    points = tmp_path / "points.ply"
    trimesh.PointCloud(np.random.default_rng(0).random((10, 3))).export(str(points))
    with pytest.raises(ModelError, match="no triangles"):
        meshes.load_model(points)


def test_supported_suffixes():
    suffixes = meshes.supported_suffixes()
    assert {".stl", ".obj", ".ply", ".3mf", ".glb", ".gltf", ".fbx"} <= suffixes


@pytest.mark.parametrize(
    ("dimensions", "expected"),
    [
        ((0.02, 0.02, 0.03), "almost certainly in metres"),  # analyze.py: < 0.5 → metres
        ((0.8, 0.8, 0.5), "probably in metres"),  # analyze.py: < 5 → probably metres
        ((1.5, 1.0, 1.0), "probably in metres"),
        ((20, 20, 30), None),
    ],
)
def test_units_warning_uses_analyze_thresholds(dimensions, expected):
    warning = meshes.units_warning(dimensions)
    if expected is None:
        assert warning is None
    else:
        assert expected in warning
        assert "analyze.py converts it to mm" in warning
