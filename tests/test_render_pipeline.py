"""Renderer selection, fallback and the finished preview file (software renderer, no Blender)."""

import logging
import tempfile

import numpy as np
import pytest
import render_models
from PIL import Image

from bambu_studio_ai import render
from bambu_studio_ai.render import compose, meshes, pipeline, software, views
from bambu_studio_ai.render.errors import BackendError

ALL_TOOLS = render.Tools(blender="/opt/blender", bambu_studio=("/opt/bambu-studio",))


@pytest.fixture
def small_frames(monkeypatch):
    """Render at thumbnail size so the pipeline tests stay fast."""
    monkeypatch.setattr(pipeline, "STILL_SIZE", 160)
    monkeypatch.setattr(pipeline, "TILE_SIZE", 120)
    monkeypatch.setattr(pipeline, "TURNTABLE_SIZE", 80)


def _request(tmp_path, model, mode="perspective", **options):
    suffix = ".gif" if mode == "turntable" else ".png"
    return render.PreviewRequest(model=model, output=tmp_path / f"out{suffix}", mode=mode, **options)


def _plan(tmp_path, tools, mode="perspective", writer=render_models.write_stl, suffix=".stl", **options):
    path = writer(tmp_path / f"model{suffix}")
    return render.plan(_request(tmp_path, path, mode, **options), tools, meshes.load_model(path))


# --- choosing renderers ------------------------------------------------------------------


def test_best_renderer_first(tmp_path):
    assert _plan(tmp_path, ALL_TOOLS) == ["blender", "bambu-studio", "software"]


def test_without_blender_bambu_studio_then_software(tmp_path):
    tools = render.Tools(bambu_studio=("/opt/bambu-studio",))
    assert _plan(tmp_path, tools) == ["bambu-studio", "software"]


def test_nothing_installed_still_has_the_software_renderer(tmp_path):
    assert _plan(tmp_path, render.Tools()) == ["software"]


@pytest.mark.parametrize("mode", ["front", "side", "top", "all", "turntable"])
def test_bambu_studio_is_only_used_for_the_perspective_view(tmp_path, mode):
    assert _plan(tmp_path, render.Tools(bambu_studio=("bs",)), mode) == ["software"]


def test_bambu_studio_is_skipped_for_coloured_models(tmp_path):
    # Its thumbnail is flat filament green: the software renderer shows the real colours.
    plan = _plan(tmp_path, ALL_TOOLS, writer=render_models.write_two_color_glb, suffix=".glb")
    assert plan == ["blender", "software"]


def test_fbx_needs_blender(tmp_path):
    fbx = tmp_path / "model.fbx"
    fbx.write_bytes(b"Kaydara FBX Binary")
    assert render.plan(_request(tmp_path, fbx), ALL_TOOLS, None) == ["blender"]
    with pytest.raises(render.RendererMissingError, match="need Blender"):
        render.plan(_request(tmp_path, fbx), render.Tools(), None)


def test_forced_renderer_that_is_missing_is_a_dependency_error(tmp_path):
    with pytest.raises(render.RendererMissingError, match="Blender is not installed: install Blender"):
        _plan(tmp_path, render.Tools(), renderer="blender")


def test_forced_bambu_studio_cannot_draw_a_grid(tmp_path):
    with pytest.raises(render.RequestError, match="only render the perspective"):
        _plan(tmp_path, ALL_TOOLS, "all", renderer="bambu-studio")


def test_default_timeout_leaves_room_for_the_gpu_kernel_compile():
    # First GPU use compiles kernels (~105 s measured); the budget must cover that and the frames.
    assert render.default_timeout("perspective") >= 180
    assert render.default_timeout("turntable") > render.default_timeout("all") > 180


# --- rendering ---------------------------------------------------------------------------


def test_falls_back_when_blender_fails(tmp_path, monkeypatch, caplog, small_frames):
    def broken(*args, **kwargs):
        raise BackendError("Blender crashed")

    monkeypatch.setattr(pipeline.blender, "run", broken)
    path = render_models.write_3mf(tmp_path / "model.3mf")
    with caplog.at_level(logging.WARNING):
        result = render.render_preview(_request(tmp_path, path), render.Tools(blender="/opt/blender"))
    assert result.renderer == "software"
    assert "Blender failed: Blender crashed" in caplog.text


def test_every_renderer_failing_is_reported_together(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise BackendError("boom")

    monkeypatch.setattr(pipeline.blender, "run", broken)
    monkeypatch.setattr(pipeline.software, "render_frames", broken)
    path = render_models.write_stl(tmp_path / "model.stl")
    with pytest.raises(render.RenderFailedError, match="blender: boom; software: boom"):
        render.render_preview(_request(tmp_path, path), render.Tools(blender="/opt/blender"))


def test_scratch_files_are_removed_even_after_a_failure(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    def broken(*args, **kwargs):
        raise BackendError("timed out")

    monkeypatch.setattr(pipeline.software, "render_frames", broken)
    path = render_models.write_3mf(tmp_path / "model.3mf")
    with pytest.raises(render.RenderFailedError):
        render.render_preview(_request(tmp_path, path), render.Tools())
    assert list(scratch.iterdir()) == []


def test_3mf_single_view_with_height_check(tmp_path, small_frames):
    path = render_models.write_3mf(tmp_path / "model_scaled.3mf")
    result = render.render_preview(_request(tmp_path, path, expected_height_mm=60), render.Tools())
    assert result.dimensions_mm == pytest.approx((40, 20, 30))
    assert result.height_check.to_dict() == {"expected_mm": 60, "actual_mm": 30.0, "diff_pct": 50.0, "ok": False}
    with Image.open(result.output_file) as image:
        assert (image.format, image.size) == ("PNG", (160, 160))


def test_grid_tiles_are_perspective_front_side_top(tmp_path, small_frames):
    model_path = tmp_path / "bracket.stl"
    render_models.bracket().export(model_path)
    result = render.render_preview(_request(tmp_path, model_path, "all"), render.Tools())
    assert result.views == ("perspective", "front", "side", "top")
    frames = software.render_frames(
        meshes.load_model(model_path), [views.view_direction(v) for v in views.GRID_VIEWS], 120, same_distance=False
    )
    with Image.open(result.output_file) as sheet:
        for index, (view, frame) in enumerate(zip(views.GRID_VIEWS, frames)):
            x, y = (index % 2) * 120, (index // 2) * 120
            expected = compose.label(compose.flatten(frame), views.VIEW_LABELS[view])
            assert np.array_equal(np.asarray(sheet.convert("RGB").crop((x, y, x + 120, y + 120))),
                                  np.asarray(expected)), f"tile {index} is not {view}"


def test_turntable_is_a_36_frame_gif(tmp_path, small_frames):
    model_path = tmp_path / "bracket.stl"
    render_models.bracket().export(model_path)
    result = render.render_preview(_request(tmp_path, model_path, "turntable"), render.Tools())
    assert result.views == ("turntable",)
    with Image.open(result.output_file) as gif:
        assert (gif.format, gif.n_frames, gif.info["duration"]) == ("GIF", 36, 120)


def test_tiny_model_is_reported_as_is_with_a_units_warning(tmp_path, small_frames):
    # Regression: the old preview silently multiplied models under 1.0 by 1000.
    path = render_models.write_stl(tmp_path / "tiny.stl", extents=(0.8, 0.8, 0.5))
    result = render.render_preview(_request(tmp_path, path), render.Tools())
    assert result.dimensions_mm == pytest.approx((0.8, 0.8, 0.5))
    assert any("probably in metres" in w for w in result.warnings)


@pytest.mark.parametrize(("mode", "output", "message"), [
    ("turntable", "x.png", "writes a .gif file"),
    ("all", "x.gif", "writes a .png file"),
])
def test_output_suffix_must_match_the_mode(tmp_path, mode, output, message):
    path = render_models.write_stl(tmp_path / "m.stl")
    request = render.PreviewRequest(model=path, output=tmp_path / output, mode=mode)
    with pytest.raises(render.RequestError, match=message):
        render.render_preview(request, render.Tools())


def test_missing_and_unsupported_files_are_model_errors(tmp_path):
    with pytest.raises(render.ModelError, match="file not found"):
        render.render_preview(_request(tmp_path, tmp_path / "nope.stl"), render.Tools())
    notes = tmp_path / "notes.txt"
    notes.write_text("hello")
    with pytest.raises(render.ModelError, match=r"can't preview \.txt"):
        render.render_preview(_request(tmp_path, notes), render.Tools())
