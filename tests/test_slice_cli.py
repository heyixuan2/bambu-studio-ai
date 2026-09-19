"""slice.py: the command-line contract (arguments, exit codes, --json, human output).

Bambu Studio is replaced by the trimmed fixture profiles and a recorded slice result,
so these tests run without it; tests/test_slicer_live.py slices for real (opt-in).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import slice as slice_cli
from bambu_studio_ai.slicing import ProfileLibrary, SliceError, SliceResult
from bambu_studio_ai.slicing.estimate import parse_result_json

FIXTURES = Path(__file__).parent / "fixtures" / "slicing"
SCRIPT = Path(__file__).parent.parent / "scripts" / "slice.py"


@pytest.fixture
def model(tmp_path):
    path = tmp_path / "cube.stl"
    path.write_text("solid cube\nendsolid cube\n", encoding="utf-8")
    return path


@pytest.fixture
def installed(monkeypatch):
    """Bambu Studio 'installed' with the fixture profiles; slices are recorded, not run."""
    jobs = []
    result = json.loads((FIXTURES / "result_p1s_box.json").read_text(encoding="utf-8"))

    def fake_run(cli, job):
        jobs.append(job)
        return SliceResult(output_file=job.output, estimate=parse_result_json(result),
                           bambu_studio_version="02.07.01.62", seconds=0.4)

    monkeypatch.setattr(slice_cli, "find_cli", lambda: ("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio",))
    monkeypatch.setattr(slice_cli, "find_profiles_dir", lambda cli=None: FIXTURES / "profiles")
    monkeypatch.setattr(slice_cli, "run_slice", fake_run)
    return jobs


def test_no_printer_configured_is_exit_2_before_looking_for_bambu_studio(model, monkeypatch, capsys):
    # Regression (audit S-4): an unconfigured printer became the model "Unknown".
    monkeypatch.setattr(slice_cli, "find_cli", lambda: pytest.fail("looked for Bambu Studio"))
    assert slice_cli.main([str(model)]) == slice_cli.EXIT_CONFIG
    err = capsys.readouterr().err
    assert "No printer given and none configured" in err
    assert "H2D Pro" in err and "configure.py set model" in err

    assert slice_cli.main([str(model), "--json"]) == slice_cli.EXIT_CONFIG
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "not_configured"


def test_configured_model_is_used(model, installed, monkeypatch):
    home = Path(os.environ["BAMBU_STUDIO_AI_HOME"])
    home.mkdir(parents=True)
    (home / "config.json").write_text(json.dumps({"model": "P2S"}), encoding="utf-8")
    assert slice_cli.main([str(model)]) == 0
    assert installed[-1].machine["name"] == "Bambu Lab P2S 0.4 nozzle"

    monkeypatch.setenv("BAMBU_MODEL", "a1 mini")  # the environment beats config.json
    assert slice_cli.main([str(model)]) == 0
    assert installed[-1].machine["name"] == "Bambu Lab A1 mini 0.4 nozzle"


def test_unknown_printer_is_exit_2(model, capsys):
    assert slice_cli.main([str(model), "--printer", "Ender 3"]) == slice_cli.EXIT_CONFIG
    assert "Unknown printer 'Ender 3'" in capsys.readouterr().err


def test_json_output(model, installed, capsys):
    assert slice_cli.main([str(model), "--printer", "P1S", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["output_file"] == str(model.with_name("cube_sliced.3mf"))
    assert data["printer"] == "P1S"
    assert data["machine_profile"] == "Bambu Lab P1S 0.4 nozzle"
    assert data["process_profile"] == "0.20mm Standard @BBL X1C"
    assert data["filament_profiles"] == ["Bambu PLA Basic @BBL P1S 0.4 nozzle"]
    assert data["plate"] == "Textured PEI Plate"
    assert data["print_time_s"] == 1126
    assert data["print_time_includes_start_sequence"] is True
    assert data["filament_g"] == pytest.approx(5.08)
    assert data["filaments"] == [{"slot": 1, "filament_id": "GFA00", "grams": 5.08,
                                  "profile": "Bambu PLA Basic @BBL P1S 0.4 nozzle"}]
    assert data["bambu_studio"]["version"] == "02.07.01.62"


def test_human_output_ends_with_the_estimate_and_the_file(model, installed, capsys):
    assert slice_cli.main([str(model), "--printer", "P1S"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[-2] == "≈ 19 min incl. start sequence · 5.1 g PLA"
    assert lines[-1] == f"➡️ Use this file: {model.with_name('cube_sliced.3mf')}"


def test_slicer_gets_bambu_studios_own_presets(model, installed):
    library = ProfileLibrary(FIXTURES / "profiles")
    assert slice_cli.main([str(model), "--printer", "P1S", "--material", "PETG", "-o",
                           str(model.parent / "petg.3mf")]) == 0
    job = installed[-1]
    assert job.output == model.parent / "petg.3mf"
    assert job.machine == library.flatten("machine", "Bambu Lab P1S 0.4 nozzle")
    assert job.filament == library.flatten("filament", "Generic PETG")
    assert job.bed_type == "Textured PEI Plate"


def test_bambu_studio_missing_is_exit_3(model, monkeypatch, capsys):
    monkeypatch.setattr(slice_cli, "find_cli", lambda: None)
    monkeypatch.setattr(slice_cli, "find_profiles_dir", lambda cli=None: None)
    assert slice_cli.main([str(model), "--printer", "P1S", "--json"]) == slice_cli.EXIT_DEPENDENCY
    captured = capsys.readouterr()
    assert json.loads(captured.out)["error"]["type"] == "dependency"
    assert "bambulab.com/en/download/studio" in captured.err


def test_slice_failure_is_exit_1(model, installed, monkeypatch, capsys):
    def failing(cli, job):
        raise SliceError("Bambu Studio: Some objects are located over the boundary of the heated bed.")

    monkeypatch.setattr(slice_cli, "run_slice", failing)
    assert slice_cli.main([str(model), "--printer", "P1S", "--json"]) == slice_cli.EXIT_FAILED
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["type"] == "slice_failed"
    assert "boundary of the heated bed" in error["message"]


def test_no_matching_preset_is_exit_2(model, installed, capsys):
    assert slice_cli.main([str(model), "--printer", "P1S", "--layer-height", "0.3"]) == slice_cli.EXIT_CONFIG
    assert "Layer heights:" in capsys.readouterr().err


def test_step_files_are_refused_with_a_way_forward(tmp_path, capsys):
    step = tmp_path / "part.step"
    step.write_text("ISO-10303-21;", encoding="utf-8")
    assert slice_cli.main([str(step), "--printer", "P1S"]) == slice_cli.EXIT_CONFIG
    assert "can't read STEP" in capsys.readouterr().err


def test_missing_model_is_exit_2(tmp_path, capsys):
    assert slice_cli.main([str(tmp_path / "nope.stl"), "--printer", "P1S"]) == slice_cli.EXIT_CONFIG
    assert "File not found" in capsys.readouterr().err


def test_output_must_be_a_new_3mf(model, capsys):
    assert slice_cli.main([str(model), "--printer", "P1S", "-o", "out.gcode"]) == slice_cli.EXIT_CONFIG
    assert "-o must name a new .3mf" in capsys.readouterr().err


@pytest.mark.parametrize(("args", "explanation"), [
    (["--filament=Bambu PLA Basic"], "renamed to `--material`"),
    (["--orient"], "no longer re-orients"),
    (["--arrange"], "no longer arranges"),
    (["--no-detect"], "no longer asks the printer"),
    (["--quality", "extra"], "`--quality extra` was removed"),
    (["--quality=Extra"], "--layer-height 0.08"),
])
def test_removed_flags_explain_themselves(args, explanation, model, capsys):
    assert slice_cli.main([str(model), *args]) == slice_cli.EXIT_CONFIG
    assert explanation in capsys.readouterr().err


def test_list_profiles_json(installed, capsys):
    assert slice_cli.main(["--list-profiles", "--printer", "P1S", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    printers = {p["printer"]: p["nozzles_mm"] for p in data["printers"]}
    assert len(printers) == 13
    assert printers["P1S"] == [0.4, 0.8]
    assert printers["X2D"] == []  # not in the fixture profiles
    assert data["selected"]["qualities"] == {
        "draft": "0.24mm Draft @BBL X1C",
        "standard": "0.20mm Standard @BBL X1C",
        "fine": "0.12mm Fine @BBL X1C",
    }
    assert data["selected"]["default_filament"] == "Bambu PLA Basic @BBL P1S 0.4 nozzle"
    assert "PETG" in data["selected"]["materials"]


def test_help_runs_as_a_script():
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                            capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0
    assert "--layer-height" in result.stdout
