"""The Blender and Bambu Studio backends, driven through stand-in executables.

The committed Blender script is checked statically (it must compile, stay importable
without bpy, and accept exactly the argv the host builds). Real renders are in
test_render_blender.py behind the opt-in ``blender`` marker.
"""

import ast
import sys
import textwrap
import time

import pytest

from bambu_studio_ai.render import bambu_studio, blender, blender_scene, views
from bambu_studio_ai.render.errors import BackendError

FAKE_BLENDER = textwrap.dedent('''
    import argparse, json, os, sys, time
    from pathlib import Path
    from PIL import Image
    args = sys.argv[sys.argv.index("--") + 1:]
    parser = argparse.ArgumentParser()
    for flag in ("--model", "--out-dir", "--json-out", "--size", "--samples", "--turntable"):
        parser.add_argument(flag)
    parser.add_argument("--views", nargs="+")
    parser.add_argument("--cpu", action="store_true")
    ns = parser.parse_args(args)
    mode = os.environ["FAKE_BLENDER_MODE"]
    if mode == "hang":
        print("BSA_PROGRESS " + json.dumps({"stage": "device", "device": "METAL"}), flush=True)
        time.sleep(60)
    if mode == "crash":
        print("Error: segfault in something", flush=True)
        sys.exit(11)
    report = {"ok": mode == "ok", "error": "ValueError: model.stl contains no meshes"}
    if mode == "ok":
        names = ns.views or [f"frame_{i:03d}" for i in range(int(ns.turntable))]
        frames = []
        for i, name in enumerate(names):
            path = Path(ns.out_dir) / f"{i:03d}_{name}.png"
            Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(path)
            frames.append({"name": name, "path": str(path)})
            print("BSA_PROGRESS " + json.dumps({"stage": "frame", "index": i + 1,
                  "total": len(names), "seconds": 0.1}), flush=True)
        report.update(dimensions=[20, 20, 30], faces=12, material="preview", device="CPU",
                      frames=frames, blender_version="fake")
    Path(ns.json_out).write_text(json.dumps(report))
    sys.exit(0 if mode == "ok" else 1)
''')

FAKE_BAMBU_STUDIO = textwrap.dedent('''
    import json, os, sys
    from pathlib import Path
    from PIL import Image
    args = sys.argv[1:]
    out = Path(args[args.index("--outputdir") + 1])
    camera = args[args.index("--camera-view") + 1]
    ok = os.environ.get("FAKE_BS_MODE") == "ok"
    # Like the real CLI: result.json goes to the working directory.
    Path("result.json").write_text(json.dumps(
        {"return_code": 0 if ok else -2, "error_string": "Success." if ok else "Failed loading the input model."}))
    if ok:
        Image.new("RGBA", (512, 512), (0, 160, 60, 255)).save(out / f"plate_1_{camera}.png")
    sys.exit(0 if ok else 1)
''')


@pytest.fixture
def fake_blender(tmp_path, monkeypatch):
    script = tmp_path / "fake_blender.py"
    script.write_text(FAKE_BLENDER, encoding="utf-8")

    def make(mode):
        monkeypatch.setenv("FAKE_BLENDER_MODE", mode)
        return [sys.executable, str(script)]

    return make


def _job(tmp_path, **options):
    return blender.BlenderJob(model=tmp_path / "model.stl", workdir=tmp_path / "work", **options)


# --- the committed Blender script ------------------------------------------------------


def test_blender_script_compiles_and_imports_bpy_only_inside_blender():
    source = blender.SCENE_SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    compile(tree, str(blender.SCENE_SCRIPT), "exec")
    top_level = {alias.name for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
                 for alias in node.names}
    assert not top_level & {"bpy", "mathutils"}, "bpy must stay out of module scope"
    assert "{{" not in source, "the scene script is plain Python, not an f-string template"


@pytest.mark.parametrize("options", [
    {"views": ("perspective",)},
    {"views": views.GRID_VIEWS, "size": 600},
    {"turntable": 36, "samples": 24, "cpu_only": True},
])
def test_blender_script_accepts_the_host_command_line(tmp_path, options):
    job = _job(tmp_path, **options)
    command = blender.build_command(["blender"], job)
    assert command[:command.index("--")].count(str(blender.SCENE_SCRIPT)) == 1
    args = blender_scene.parse_args(blender_scene.script_args(command))
    assert args.model == job.model and args.json_out == job.json_out and args.out_dir == job.frame_dir
    assert (args.views or []) == list(job.views)
    assert (args.turntable or 0) == job.turntable
    assert (args.size, args.samples, args.cpu) == (job.size, job.samples, job.cpu_only)


def test_blender_script_uses_the_shared_view_module():
    loaded = blender_scene.load_views()
    assert loaded.GRID_VIEWS == views.GRID_VIEWS
    assert loaded.turntable_directions(8) == views.turntable_directions(8)
    assert set(blender_scene.VIEW_NAMES) == set(views.GRID_VIEWS)


def test_blender_preview_colour_matches_the_software_renderer():
    from bambu_studio_ai.render.meshes import PREVIEW_RGB
    assert blender_scene.PREVIEW_SRGB == PREVIEW_RGB


# --- running Blender --------------------------------------------------------------------


def test_run_reads_the_report_and_frames(tmp_path, fake_blender):
    report = blender.run(fake_blender("ok"), _job(tmp_path, views=views.GRID_VIEWS), timeout_s=60)
    assert [p.name for p in report.frames] == [f"{i:03d}_{v}.png" for i, v in enumerate(views.GRID_VIEWS)]
    assert report.dimensions == (20, 20, 30)
    assert (report.faces, report.material, report.device) == (12, "preview", "CPU")


def test_run_reports_the_scripts_error(tmp_path, fake_blender):
    with pytest.raises(BackendError, match="contains no meshes"):
        blender.run(fake_blender("error"), _job(tmp_path, views=("top",)), timeout_s=60)


def test_run_without_a_report_shows_blenders_output(tmp_path, fake_blender):
    with pytest.raises(BackendError, match="exited with 11 and no report.*segfault"):
        blender.run(fake_blender("crash"), _job(tmp_path, views=("top",)), timeout_s=60)


def test_run_kills_blender_on_timeout_and_explains_gpu_kernels(tmp_path, fake_blender):
    started = time.monotonic()
    with pytest.raises(BackendError, match=r"within 2 s \(0/1 frames\).*GPU kernels.*--cpu"):
        blender.run(fake_blender("hang"), _job(tmp_path, views=("top",)), timeout_s=2)
    assert time.monotonic() - started < 20


# --- Bambu Studio -----------------------------------------------------------------------


@pytest.fixture
def fake_bambu_studio(tmp_path, monkeypatch):
    script = tmp_path / "fake_bambu_studio.py"
    script.write_text(FAKE_BAMBU_STUDIO, encoding="utf-8")
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return [sys.executable, str(script)]


def test_bambu_studio_renders_in_a_scratch_directory(tmp_path, fake_bambu_studio, monkeypatch):
    monkeypatch.setenv("FAKE_BS_MODE", "ok")
    image = bambu_studio.render_view(fake_bambu_studio, tmp_path / "m.stl", "perspective", tmp_path / "work")
    assert image.name == "plate_1_0.png" and image.is_file()
    assert not (tmp_path / "cwd" / "result.json").exists(), "result.json must not land in the user's cwd"


def test_bambu_studio_failure_quotes_result_json(tmp_path, fake_bambu_studio, monkeypatch):
    monkeypatch.setenv("FAKE_BS_MODE", "fail")
    with pytest.raises(BackendError, match="Failed loading the input model"):
        bambu_studio.render_view(fake_bambu_studio, tmp_path / "m.stl", "perspective", tmp_path / "w")


def test_bambu_studio_only_draws_the_perspective_view(tmp_path):
    with pytest.raises(BackendError, match="top"):
        bambu_studio.render_view(["unused"], tmp_path / "m.stl", "top", tmp_path)


def test_bambu_studio_cli_discovery(monkeypatch, tmp_path):
    monkeypatch.setattr(bambu_studio.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bambu_studio.shutil, "which", lambda name: None)
    assert bambu_studio.find_bambu_studio_cli() is None
    monkeypatch.setattr(bambu_studio.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert bambu_studio.find_bambu_studio_cli() == ["/usr/bin/bambu-studio"]


def test_fake_report_shape_matches_the_real_script():
    # The keys the host reads must be the ones blender_scene.render() returns.
    source = blender.SCENE_SCRIPT.read_text(encoding="utf-8")
    for key in ("dimensions", "faces", "material", "device", "frames", "blender_version"):
        assert f'"{key}"' in source
