"""python3 scripts/colorize: CLI contract (flags, --json, exit codes, outputs) and speed."""

import json
import os
import subprocess
import sys
import time

import numpy as np
import pytest

import colorize.__main__ as cli
from bambu_studio_ai.color import build_project, colorize, read_project
from glb_builder import bands, box, grid, png, textured, write_glb

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "colorize")
RED, GREEN, BLUE = (200, 30, 30), (30, 180, 40), (30, 60, 200)


@pytest.fixture
def cube(tmp_path):
    corners, faces, uv = box((0.04, 0.04, 0.04))
    return write_glb(tmp_path / "cube.glb", [{"positions": corners, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(bands([RED, GREEN, BLUE]))])


def run_json(capsys, *argv):
    code = cli.main([*map(str, argv), "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_help_runs_by_path_and_shows_kebab_case_flags():
    result = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0
    for flag in ("--max-colors", "--colors", "--min-area", "--height", "--format", "--json"):
        assert flag in result.stdout
    assert "--max_colors" not in result.stdout and "--method" not in result.stdout


def test_json_report_and_files(cube, capsys):
    code, report, _ = run_json(capsys, cube, "--height", "30")
    assert code == 0
    assert report["output_file"].endswith("cube_multicolor.3mf")
    assert report["format"] == "3mf" and report["metric"] == "CIEDE2000"
    assert report["size_mm"] == [30.0, 30.0, 30.0]
    assert sorted(c["hex"] for c in report["colors"]) == ["#1E3CC8", "#1EB428", "#C81E1E"]
    assert sum(c["area_pct"] for c in report["colors"]) == pytest.approx(100, abs=0.1)
    assert [c["filament"] for c in report["colors"]] == [1, 2, 3]
    for colour in report["colors"]:
        match = colour["suggested_filament"]
        assert match is None or set(match) == {"line", "name", "hex", "delta_e"}
    with open(report["output_file"], "rb") as handle:
        project = read_project(handle.read())
    assert project.settings["filament_colour"] == [c["hex"] for c in report["colors"]]
    assert os.path.getsize(report["preview_file"]) > 0


def test_human_output_ends_with_the_file_to_use(cube, capsys):
    assert cli.main([str(cube)]) == 0
    out = capsys.readouterr().out
    assert out.strip().splitlines()[-1].startswith("➡️ Use this file: ")
    assert "CIEDE2000" in out


def test_obj_format_from_flag_or_output_suffix(cube, tmp_path, capsys):
    code, report, _ = run_json(capsys, cube, "--format", "obj")
    assert code == 0 and report["output_file"].endswith("cube_multicolor.obj")
    code, report, _ = run_json(capsys, cube, "-o", tmp_path / "out.obj")
    assert code == 0 and report["format"] == "obj"
    with open(report["output_file"], encoding="utf-8") as handle:
        assert sum(line.startswith("v ") and len(line.split()) == 7 for line in handle) == 8


def test_removed_flags_print_a_note_and_continue(cube, capsys):
    code, report, err = run_json(capsys, cube, "--method", "hybrid", "--subdivide", "2", "--no-merge",
                                 "--island-size=500", "--no-geometry-protect", "--bambu-map")
    assert code == 0 and len(report["colors"]) == 3
    for flag in ("--method", "--subdivide", "--no-merge", "--island-size", "--no-geometry-protect", "--bambu-map"):
        assert f"note: {flag} was removed" in err


def test_legacy_spellings_still_work(cube, capsys):
    code, report, _ = run_json(capsys, cube, "--max_colors", "2", "--min-pct", "1.0")
    assert code == 0 and len(report["colors"]) == 2


def test_forced_colours_become_the_filaments_in_order(cube, capsys):
    code, report, _ = run_json(capsys, cube, "--colors", "#c81e1e, #1EB428,#1E3CC8,#FFFFFF")
    assert code == 0
    assert [c["hex"] for c in report["colors"]] == ["#C81E1E", "#1EB428", "#1E3CC8", "#FFFFFF"]
    assert report["colors"][3]["area_pct"] == 0
    assert any("#FFFFFF" in w for w in report["warnings"])


@pytest.mark.parametrize("argv", [
    ["--max-colors", "9"], ["--max-colors", "0"], ["--min-area", "5"], ["--height", "-3"],
    ["--colors", "#12345"], ["--colors", ",".join(["#000000"] * 9)], ["--smooth", "-1"],
])
def test_bad_arguments_exit_2(cube, capsys, argv):
    code, report, _ = run_json(capsys, cube, *argv)
    assert code == cli.EXIT_USAGE
    assert report["error"]["type"] == "bad_arguments"


def test_missing_input_exits_2(tmp_path, capsys):
    code, report, _ = run_json(capsys, tmp_path / "nope.glb")
    assert (code, report["error"]["type"]) == (cli.EXIT_USAGE, "not_found")


def test_model_without_colour_exits_1(tmp_path, capsys):
    corners, faces, _ = box()
    path = write_glb(tmp_path / "plain.glb", [{"positions": corners, "faces": faces}])
    code, report, _ = run_json(capsys, path)
    assert (code, report["error"]["type"]) == (cli.EXIT_FAILED, "no_colour")
    assert not (tmp_path / "plain_multicolor.3mf").exists()


def test_lost_colour_exits_1_and_writes_nothing(tmp_path, capsys):
    image = np.zeros((200, 200, 3), np.uint8)
    image[:, :95], image[:, 95:105], image[:, 105:] = RED, (20, 20, 20), BLUE
    positions, faces, uv = grid(1, width=0.05)
    path = write_glb(tmp_path / "line.glb", [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(image)])
    code, report, _ = run_json(capsys, path)
    assert (code, report["error"]["type"]) == (cli.EXIT_FAILED, "colors_lost")
    assert report["error"]["lost"] == ["#141414"]
    assert not (tmp_path / "line_multicolor.3mf").exists()


def test_unreadable_model_exits_1(tmp_path, capsys):
    path = tmp_path / "broken.glb"
    path.write_bytes(b"glTF not really")
    code, report, _ = run_json(capsys, path)
    assert (code, report["error"]["type"]) == (cli.EXIT_FAILED, "unreadable")


def test_200k_triangles_and_a_2048_texture_take_seconds_not_minutes(tmp_path):
    # Regression: v2.0's texture-space cleanup took 2 minutes at 1024².
    rng = np.random.default_rng(0)
    palette = np.array([(220, 190, 50), (110, 60, 25), (20, 20, 20), (240, 240, 240)])
    blocks = rng.integers(0, len(palette), (32, 32))
    image = np.clip(palette[np.kron(blocks, np.ones((64, 64), int))] + rng.normal(0, 6, (2048, 2048, 3)), 0, 255)
    positions, faces, uv = grid(317, width=0.08)
    path = write_glb(tmp_path / "big.glb", [{"positions": positions, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(image.astype(np.uint8))])
    start = time.perf_counter()
    result = colorize(path)
    build_project(result.vertices, result.faces, result.labels, result.palette.hex, "big")
    elapsed = time.perf_counter() - start
    assert len(result.faces) > 200_000
    assert len(result.palette) == 4
    assert elapsed < 10, f"{elapsed:.1f} s"  # about 1.2 s on an M-series Mac
