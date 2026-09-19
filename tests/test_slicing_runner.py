"""Running the Bambu Studio command line (bambu_studio_ai.slicing.runner).

Uses fixtures/slicing/fake_bambu_studio.py in place of the app, so these tests run
anywhere; tests/test_slicer_live.py runs the real one (opt-in).
"""

import dataclasses
import json
import sys
from pathlib import Path

import pytest

from bambu_studio_ai.slicing import ProfileLibrary, SliceError, SliceJob, run_slice

FIXTURES = Path(__file__).parent / "fixtures" / "slicing"
FAKE_CLI = (sys.executable, str(FIXTURES / "fake_bambu_studio.py"))


@pytest.fixture(scope="module")
def library():
    return ProfileLibrary(FIXTURES / "profiles")


@pytest.fixture
def job(library, tmp_path):
    model = tmp_path / "cube.stl"
    model.write_text("solid cube\nendsolid cube\n", encoding="utf-8")
    return SliceJob(
        model=model,
        output=tmp_path / "out" / "cube_sliced.3mf",
        machine=library.flatten("machine", "Bambu Lab P1S 0.4 nozzle"),
        process=library.flatten("process", "0.20mm Standard @BBL X1C"),
        filament=library.flatten("filament", "Bambu PLA Basic @BBL P1S 0.4 nozzle"),
        bed_type="Textured PEI Plate",
        timeout_s=20,
    )


@pytest.fixture
def record(monkeypatch, tmp_path):
    path = tmp_path / "invocation.json"
    monkeypatch.setenv("FAKE_BS_RECORD", str(path))
    return path


def test_slice_writes_the_project_and_reads_the_estimate(job, record):
    result = run_slice(FAKE_CLI, job)

    assert result.output_file == job.output
    assert job.output.is_file()
    assert result.estimate.print_time_s == pytest.approx(600.5)
    assert result.estimate.filament_g == pytest.approx(2.5)
    assert result.estimate.source == "result.json"
    assert result.bambu_studio_version == "02.07.01.62"
    # the scratch folder next to the output is gone
    assert [p.name for p in job.output.parent.iterdir()] == ["cube_sliced.3mf"]


def test_command_line_and_working_directory(job, record):
    run_slice(FAKE_CLI, job)
    invocation = json.loads(record.read_text(encoding="utf-8"))
    argv = invocation["argv"]

    # --export-3mf must be relative: with --outputdir set, Bambu Studio prefixes it
    # with that folder even when it is absolute, and the export fails.
    assert argv[argv.index("--export-3mf") + 1] == "sliced.3mf"
    assert argv[argv.index("--slice") + 1] == "0"
    # result.json lands in the working directory, so it must be the scratch folder
    assert Path(invocation["cwd"]).resolve() == Path(argv[argv.index("--outputdir") + 1]).resolve()
    assert argv[-1] == str(job.model.resolve())


def test_profiles_reach_bambu_studio_unchanged(job, record):
    run_slice(FAKE_CLI, job)
    machine, process = json.loads(record.read_text(encoding="utf-8"))["settings"]
    filaments = json.loads(record.read_text(encoding="utf-8"))["filaments"]

    # Regression (audit S-1): the start and filament-change G-code were replaced.
    assert machine == dict(job.machine)
    assert machine["machine_start_gcode"] == job.machine["machine_start_gcode"]
    assert machine["change_filament_gcode"] == job.machine["change_filament_gcode"]
    assert filaments == [dict(job.filament)]
    # the one addition: the build plate, a project setting
    assert process == {**job.process, "curr_bed_type": "Textured PEI Plate"}


def test_missing_result_json_falls_back_to_the_gcode_header(job, record, monkeypatch):
    monkeypatch.setenv("FAKE_BS_MODE", "no_result")
    result = run_slice(FAKE_CLI, job)
    assert result.estimate.source == "gcode"
    assert result.estimate.print_time_s == 600
    assert result.estimate.filaments[0].filament_id == "GFA00"


def test_bambu_studio_error_is_reported(job, record, monkeypatch):
    monkeypatch.setenv("FAKE_BS_MODE", "fail")
    with pytest.raises(SliceError, match=r"not compatible with the plate type\. \(code -61\)"):
        run_slice(FAKE_CLI, job)
    assert not job.output.exists()
    assert list(job.output.parent.iterdir()) == []


def test_no_sliced_file_is_a_failure(job, record, monkeypatch):
    # Regression (audit S-14): success used to mean "some file exists".
    monkeypatch.setenv("FAKE_BS_MODE", "no_3mf")
    with pytest.raises(SliceError, match="without writing a sliced 3MF"):
        run_slice(FAKE_CLI, job)


def test_timeout(job, record, monkeypatch):
    monkeypatch.setenv("FAKE_BS_MODE", "hang")
    with pytest.raises(SliceError, match=r"did not finish within 0\.5 s"):
        run_slice(FAKE_CLI, dataclasses.replace(job, timeout_s=0.5))


def test_missing_executable(job, tmp_path):
    with pytest.raises(SliceError, match="could not run"):
        run_slice((str(tmp_path / "no-such-slicer"),), job)
