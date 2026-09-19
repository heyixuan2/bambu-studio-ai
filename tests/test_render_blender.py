"""Real Blender renders (opt-in: ``pytest -m blender``; skipped when Blender isn't installed).

These catch what the stand-in tests can't: framing, axes, materials and textures as
Blender actually draws them.
"""

import numpy as np
import pytest
import render_models
from PIL import Image

import common
from bambu_studio_ai import render
from bambu_studio_ai.render import blender, meshes, views

pytestmark = pytest.mark.blender
SIZE = 200


@pytest.fixture(scope="module")
def blender_path():
    path = common.find_blender()
    if not path:
        pytest.skip("Blender is not installed")
    return path


def _render(blender_path, model, tmp_path, **options):
    options.setdefault("views", ("perspective",))
    job = blender.BlenderJob(model=model, workdir=tmp_path / "work", size=SIZE, samples=16, **options)
    return blender.run([blender_path], job, timeout_s=render.default_timeout("turntable"))


def _alpha(path):
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"))[:, :, 3]


def _assert_framed(path, min_span=0.8):
    """The object fills at least ``min_span`` of the frame and touches no edge (no clipping).

    Stills are fitted per view (about 92 % of the frame); turntable frames share one
    distance, so the narrowest angles fill less.
    """
    alpha = _alpha(path) > 0
    rows, cols = np.flatnonzero(alpha.any(axis=1)), np.flatnonzero(alpha.any(axis=0))
    assert rows.size and cols.size, f"{path.name} is empty"
    span = max(rows[-1] - rows[0] + 1, cols[-1] - cols[0] + 1) / SIZE
    assert span >= min_span, f"{path.name}: object spans only {span:.0%} of the frame"
    assert not (alpha[0].any() or alpha[-1].any() or alpha[:, 0].any() or alpha[:, -1].any()), (
        f"{path.name}: object touches the frame edge"
    )


def _share(path, channel):
    """Share of object pixels where ``channel`` (0=R, 1=G, 2=B) clearly dominates."""
    with Image.open(path) as image:
        pixels = np.asarray(image.convert("RGBA")).astype(int)
    solid = pixels[pixels[:, :, 3] == 255][:, :3]
    others = np.delete(solid, channel, axis=1).max(axis=1)
    return float((solid[:, channel] > 1.5 * others + 20).mean())


def test_stl_fills_the_frame_in_every_view(blender_path, tmp_path):
    model = render_models.write_stl(tmp_path / "box.stl")
    report = _render(blender_path, model, tmp_path, views=views.GRID_VIEWS)
    assert report.dimensions == pytest.approx((20, 20, 30), rel=1e-4)
    assert report.material == "preview"
    for frame in report.frames:
        _assert_framed(frame)


def test_turntable_never_clips(blender_path, tmp_path):
    model = tmp_path / "bracket.stl"
    render_models.bracket().export(model)
    report = _render(blender_path, model, tmp_path, views=(), turntable=12)
    assert len(report.frames) == 12
    for frame in report.frames:
        _assert_framed(frame, min_span=0.4)


def test_textured_glb_keeps_its_texture(blender_path, tmp_path):
    model = render_models.write_textured_glb(tmp_path / "ball.glb")
    report = _render(blender_path, model, tmp_path)
    assert report.material == "texture"
    _assert_framed(report.frames[0])
    assert _share(report.frames[0], 0) > 0.2  # red squares
    assert _share(report.frames[0], 2) > 0.2  # blue squares


def test_untextured_materials_are_kept(blender_path, tmp_path):
    # Regression: baseColorFactor-only materials were replaced by the blue preview material.
    model = render_models.write_two_color_glb(tmp_path / "two.glb")
    report = _render(blender_path, model, tmp_path, views=("front",))
    assert report.material == "material"
    assert _share(report.frames[0], 0) > 0.2 and _share(report.frames[0], 1) > 0.2


def test_glb_keeps_the_files_axes(blender_path, tmp_path):
    # Regression: Blender's glTF import stood Y-up files upright, unlike Bambu Studio and analyze.py.
    model = render_models.write_y_tall_glb(tmp_path / "slab.glb")
    report = _render(blender_path, model, tmp_path)
    assert report.dimensions == pytest.approx(meshes.load_model(model).dimensions, rel=1e-4)


def test_3mf_end_to_end(blender_path, tmp_path):
    model = render_models.write_3mf(tmp_path / "model_scaled.3mf")
    request = render.PreviewRequest(model=model, output=tmp_path / "preview.png", expected_height_mm=30)
    result = render.render_preview(request, render.Tools(blender=blender_path))
    assert result.renderer == "blender"
    assert result.dimensions_mm == pytest.approx((40, 20, 30))
    assert result.height_check.ok
    assert result.warnings == ()  # Blender and trimesh agree on the size
    with Image.open(result.output_file) as image:
        assert image.size == (render.pipeline.STILL_SIZE, render.pipeline.STILL_SIZE)
