"""preview.py command line: flags, exit codes, and the --json contract."""

import json
import os
import subprocess
import sys

import pytest
import render_models

import preview
from bambu_studio_ai import render
from bambu_studio_ai.render import pipeline

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "preview.py")


@pytest.fixture
def no_external_renderers(monkeypatch):
    """Pretend neither Blender nor Bambu Studio is installed: the software renderer runs."""
    monkeypatch.setattr(preview, "find_blender", lambda: None)
    monkeypatch.setattr(render, "find_bambu_studio_cli", lambda: None)
    monkeypatch.setattr(pipeline, "STILL_SIZE", 120)


def test_help_lists_the_documented_flags():
    result = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0
    for flag in ("--views", "--height", "--output", "-o", "--json", "--renderer", "--cpu", "--timeout"):
        assert flag in result.stdout
    assert "compiles Cycles' GPU kernels once" in " ".join(result.stdout.split())


def test_cli_choices_match_the_library():
    assert preview.MODES == render.MODES
    assert preview.RENDERER_CHOICES == ("auto", *render.RENDERERS)


def test_json_output_is_one_document_on_stdout(tmp_path):
    # Real subprocess, so any stray print or log line on stdout would break the parse.
    model = render_models.write_3mf(tmp_path / "model_scaled.3mf")
    result = subprocess.run(
        [sys.executable, SCRIPT, str(model), "--renderer", "software", "--height", "30", "--json"],
        capture_output=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["output_file"] == str(tmp_path / "model_scaled_preview.png")
    assert data["renderer"] == "software"
    assert data["views"] == ["perspective"]
    assert data["dimensions_mm"] == [40.0, 20.0, 30.0]
    assert data["height_check"] == {"expected_mm": 30.0, "actual_mm": 30.0, "diff_pct": 0.0, "ok": True}
    assert "Rendering perspective with software" in result.stderr
    assert os.path.isfile(data["output_file"])


def test_human_output_ends_with_the_file_to_use(tmp_path, capsys, no_external_renderers):
    model = render_models.write_stl(tmp_path / "box.stl")
    assert preview.main([str(model), "--height", "60"]) == preview.EXIT_OK
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0].startswith("📸 perspective rendered with software renderer")
    assert "20.0 × 20.0 × 30.0 mm" in lines[1]
    assert any("50% off the target 60 mm" in line for line in lines)
    assert lines[-1] == f"➡️ Use this file: {tmp_path / 'box_preview.png'}"


def test_turntable_defaults_to_a_gif_next_to_the_model(tmp_path, capsys, no_external_renderers, monkeypatch):
    monkeypatch.setattr(pipeline, "TURNTABLE_SIZE", 60)
    model = render_models.write_stl(tmp_path / "box.stl")
    assert preview.main([str(model), "--views", "turntable", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["output_file"] == str(tmp_path / "box_preview.gif")


def test_missing_file_is_exit_2_with_a_json_error(tmp_path, capsys, no_external_renderers):
    assert preview.main([str(tmp_path / "nope.stl"), "--json"]) == preview.EXIT_USAGE
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"]["type"] == "bad_request"
    assert "file not found" in captured.err


def test_wrong_output_suffix_is_exit_2(tmp_path, capsys, no_external_renderers):
    model = render_models.write_stl(tmp_path / "box.stl")
    assert preview.main([str(model), "--views", "turntable", "-o", str(tmp_path / "x.png")]) == 2
    assert "writes a .gif file" in capsys.readouterr().err


def test_forced_missing_renderer_is_exit_3_with_install_hint(tmp_path, capsys, no_external_renderers):
    model = render_models.write_stl(tmp_path / "box.stl")
    assert preview.main([str(model), "--renderer", "blender", "--json"]) == preview.EXIT_DEPENDENCY
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["type"] == "dependency"
    assert "blender.org/download" in error["message"]


def test_fbx_without_blender_is_exit_3(tmp_path, capsys, no_external_renderers):
    model = tmp_path / "rig.fbx"
    model.write_bytes(b"Kaydara FBX Binary")
    assert preview.main([str(model)]) == preview.EXIT_DEPENDENCY
    assert ".fbx previews need Blender" in capsys.readouterr().err


def test_render_failure_is_exit_1(tmp_path, capsys, no_external_renderers, monkeypatch):
    def broken(*args, **kwargs):
        raise render.BackendError("out of memory")

    monkeypatch.setattr(pipeline.software, "render_frames", broken)
    model = render_models.write_stl(tmp_path / "box.stl")
    assert preview.main([str(model), "--json"]) == preview.EXIT_FAILED
    assert "software: out of memory" in json.loads(capsys.readouterr().out)["error"]["message"]
