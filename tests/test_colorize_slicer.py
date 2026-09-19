"""The painted project, checked by Bambu Studio itself (opt-in: ``pytest -m slicer``).

Needs Bambu Studio installed (set BAMBU_STUDIO_CLI to its executable if it isn't in the
usual place). Renders the project with ``--export-png`` and slices it headless, then
checks that every filament shows up in the picture and in the G-code.
"""

import json
import os
import re
import shutil
import subprocess

import numpy as np
import pytest
import trimesh
from PIL import Image

import colorize.__main__ as cli
from bambu_studio_ai.color import build_project
from glb_builder import bands, png, textured, write_glb

pytestmark = pytest.mark.slicer

CANDIDATES = [
    os.environ.get("BAMBU_STUDIO_CLI", ""),
    "/Applications/BambuStudio.app/Contents/MacOS/BambuStudio",
    shutil.which("bambu-studio") or "",
    os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Bambu Studio", "bambu-studio.exe"),
]
BAMBU_STUDIO = next((path for path in CANDIDATES if path and os.path.isfile(path)), None)
RGB = [(220, 20, 20), (20, 170, 30), (20, 40, 220)]


@pytest.fixture(scope="module")
def studio():
    if BAMBU_STUDIO is None:
        pytest.skip("Bambu Studio not installed (set BAMBU_STUDIO_CLI)")
    return BAMBU_STUDIO


def run_studio(studio, project, workdir, *args):
    """Run the CLI with ``workdir`` as the current directory, as it may write result.json there."""
    out = workdir / "out"
    out.mkdir(exist_ok=True)
    result = subprocess.run([studio, *args, "--outputdir", str(out), str(project)], cwd=workdir,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=300)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    summary = next(p for p in (out / "result.json", workdir / "result.json") if p.exists())
    report = json.loads(summary.read_text(encoding="utf-8"))
    assert report["return_code"] == 0, report
    return out, report


def colorized_block(tmp_path, capsys):
    """A solid block with red, green and blue bands left to right, run through the CLI."""
    block = trimesh.creation.box(extents=(0.04, 0.03, 0.02)).subdivide().subdivide().subdivide()
    corners = np.asarray(block.vertices)
    low, size = corners.min(axis=0), np.ptp(corners, axis=0)
    uv = (corners[:, :2] - low[:2]) / size[:2]
    model = write_glb(tmp_path / "block.glb", [{"positions": corners, "faces": block.faces, "uv": uv, "material": 0}],
                      [textured(0)], [png(bands(RGB, size=96))])
    assert cli.main([str(model), "--height", "30", "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_bambu_studio_renders_each_filament_in_its_colour(studio, tmp_path, capsys):
    report = colorized_block(tmp_path, capsys)
    out, _ = run_studio(studio, report["output_file"], tmp_path, "--export-png", "0")
    image = np.asarray(Image.open(out / "plate_1_0.png").convert("RGB")).astype(int)
    for channel in range(3):  # red, green and blue areas are all visible
        others = [c for c in range(3) if c != channel]
        dominant = (image[..., channel] > 90) & (image[..., channel] > 2 * image[..., others].max(axis=-1))
        assert dominant.sum() > 500, f"filament {channel + 1} not visible in the render"


def test_headless_slice_changes_filament(studio, tmp_path, capsys):
    report = colorized_block(tmp_path, capsys)
    out, result = run_studio(studio, report["output_file"], tmp_path, "--slice", "0")
    plate = result["sliced_plates"][0]
    assert plate["filament_change_times"] > 0
    assert {f["id"] for f in plate["filaments"] if f["total_used_g"] > 0} == {1, 2, 3}
    gcode = (out / "plate_1.gcode").read_text(encoding="utf-8", errors="replace")
    assert {"0", "1", "2"} <= set(re.findall(r"^T(\d+)", gcode, re.M))
    assert len(re.findall(r"^M620 S\d", gcode, re.M)) > 2


def test_all_eight_paint_codes_slice_as_eight_filaments(studio, tmp_path):
    sphere = trimesh.creation.icosphere(subdivisions=4, radius=15)
    angle = np.arctan2(sphere.triangles_center[:, 1], sphere.triangles_center[:, 0])
    labels = (np.floor((angle + np.pi) / (2 * np.pi) * 8).astype(np.int64)) % 8
    colours = ["#E0301E", "#1EB428", "#1E3CC8", "#F4D03F", "#8E44AD", "#16A085", "#111111", "#EEEEEE"]
    project = tmp_path / "eight.3mf"
    project.write_bytes(build_project(np.asarray(sphere.vertices), np.asarray(sphere.faces, np.int64),
                                      labels, colours, "eight"))
    out, result = run_studio(studio, project, tmp_path, "--slice", "0")
    used = {f["id"] for f in result["sliced_plates"][0]["filaments"] if f["total_used_g"] > 0}
    assert used == set(range(1, 9))
    gcode = (out / "plate_1.gcode").read_text(encoding="utf-8", errors="replace")
    assert {str(i) for i in range(8)} <= set(re.findall(r"^T(\d+)", gcode, re.M))


