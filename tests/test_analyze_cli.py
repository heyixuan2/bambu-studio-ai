"""scripts/analyze.py: the command-line contract agents rely on."""

import json
import math
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import trimesh

import analyze
from common import BUILD_VOLUMES
from mesh_shapes import box, box_missing_a_triangle, cup, open_sheets, wedge

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "analyze.py"


def no_nan(constant):
    raise ValueError(f"not valid JSON: {constant}")


def run_json(capsys, *argv):
    """Run the CLI in-process with --json; return (exit code, parsed document, stderr)."""
    code = analyze.main([*map(str, argv), "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out, parse_constant=no_nan), captured.err


def save(mesh, path):
    mesh.export(path)
    return path


class TestJsonOutput:
    """Regression: --json printed progress before the JSON object and emitted NaN."""

    def test_stdout_is_one_strict_json_document(self, tmp_path):
        model = save(open_sheets(), tmp_path / "sheets.stl")
        result = subprocess.run([sys.executable, str(SCRIPT), str(model), "--json"],
                                capture_output=True, encoding="utf-8", timeout=120)
        assert result.returncode == 0, result.stderr
        document = json.loads(result.stdout, parse_constant=no_nan)  # fails on any extra text
        assert document["schema"] == 1
        assert document["output_file"] == str(model)
        assert "Use this file" in result.stderr

    def test_errors_are_json_too(self, capsys, tmp_path):
        code, document, err = run_json(capsys, tmp_path / "missing.stl")
        assert code == analyze.EXIT_USAGE
        assert document["error"]["type"] == "usage"
        assert "file not found" in err


class TestUnits:
    """Regression: 0.5-5 unit models were forced to metres (a 4 mm part became 4 m),
    and --orient printed dimensions x1000 for parts under 10 mm."""

    def test_four_mm_cube_stays_four_mm(self, capsys, tmp_path):
        code, document, _ = run_json(capsys, save(box(4, 4, 4), tmp_path / "cube4.stl"))
        assert code == 0
        assert document["geometry"]["dimensions_mm"] == [4.0, 4.0, 4.0]
        assert (document["units"]["source"], document["units"]["scale"]) == ("assumed", 1.0)
        assert document["written_files"] == []
        assert any("--unit" in note for note in document["notes"])

    def test_eight_mm_cube_with_orient_reports_true_size(self, capsys, tmp_path):
        assert analyze.main([str(save(box(8, 8, 8), tmp_path / "cube8.stl")), "--orient"]) == 0
        out = capsys.readouterr()
        assert "8000" not in out.out + out.err
        assert "Size 8 x 8 x 8 mm" in out.out

    def test_tiny_numbers_are_read_as_metres_and_said_so(self, capsys, tmp_path):
        code, document, _ = run_json(capsys, save(box(0.04, 0.02, 0.03), tmp_path / "metres.stl"))
        assert document["geometry"]["dimensions_mm"] == pytest.approx([40, 20, 30])
        assert document["units"]["source"] == "size"
        assert document["output_file"].endswith("metres_scaled.stl")

    def test_three_mf_unit_is_honoured(self, capsys, tmp_path):
        path = save(box(1, 2, 3), tmp_path / "inch.3mf")
        loaded = trimesh.load(path)
        assert loaded.units == "millimeter"  # trimesh writes mm; rewrite it as inches
        with zipfile.ZipFile(path) as archive:
            parts = {name: archive.read(name) for name in archive.namelist()}
        parts["3D/3dmodel.model"] = parts["3D/3dmodel.model"].replace(b'unit="millimeter"', b'unit="inch"')
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in parts.items():
                archive.writestr(name, data)
        code, document, _ = run_json(capsys, path)
        assert document["units"] == {**document["units"], "unit": "in", "source": "file", "scale": 25.4}
        assert document["geometry"]["dimensions_mm"] == pytest.approx([25.4, 50.8, 76.2])
        assert trimesh.load(document["output_file"]).extents == pytest.approx([25.4, 50.8, 76.2])


class TestRepairTiers:
    """Regression: the minor tier was unreachable, so default auto-repair never ran and
    --no-auto-repair did nothing."""

    def test_default_run_repairs_a_missing_triangle(self, capsys, tmp_path):
        code, document, _ = run_json(capsys, save(box_missing_a_triangle(), tmp_path / "hole.stl"))
        assert document["steps"]["repair"]["applied"] is True
        assert document["steps"]["repair"]["before"]["boundary_edges"] == 3
        assert document["mesh"]["watertight"] is True
        assert document["output_file"] == str(tmp_path / "hole_repaired.stl")
        assert trimesh.load(document["output_file"]).is_watertight

    def test_no_auto_repair_leaves_it(self, capsys, tmp_path):
        model = save(box_missing_a_triangle(), tmp_path / "hole.stl")
        code, document, _ = run_json(capsys, model, "--no-auto-repair")
        assert document["steps"]["repair"]["applied"] is False
        assert document["mesh"]["boundary_edges"] == 3
        assert document["output_file"] == str(model)
        assert document["score"] <= 4


class TestOutputFiles:
    """Regression: _oriented was always .stl while later steps kept the input format,
    so the agent was sent to a file that did not match what it had asked for."""

    def test_glb_steps_chain_and_keep_the_format(self, capsys, tmp_path):
        lying = cup()
        lying.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
        code, document, err = run_json(capsys, save(lying, tmp_path / "cup.glb"), "--height", 60, "--orient")
        assert document["written_files"] == [str(tmp_path / "cup_scaled.glb"),
                                             str(tmp_path / "cup_scaled_oriented.glb")]
        assert document["output_file"] == str(tmp_path / "cup_scaled_oriented.glb")
        assert f"Use this file: {document['output_file']}" in err
        final = trimesh.load(document["output_file"], force="mesh")
        assert final.extents == pytest.approx(document["geometry"]["dimensions_mm"], abs=0.01)
        assert document["geometry"]["dimensions_mm"][2] == pytest.approx(135)  # 90 mm cup at x1.5
        assert any("--height 60 was applied before --orient" in note for note in document["notes"])

    def test_unwritable_format_falls_back_to_stl(self, capsys, tmp_path):
        code, document, _ = run_json(capsys, save(box(10, 10, 10), tmp_path / "part.ply"), "--height", 20)
        assert document["output_file"] == str(tmp_path / "part_scaled.stl")

    def test_three_mf_round_trip(self, capsys, tmp_path):
        code, document, _ = run_json(capsys, save(box(10, 10, 10), tmp_path / "part.3mf"), "--height", 30)
        assert code == 0
        assert trimesh.load(document["output_file"], force="mesh").extents == pytest.approx([30, 30, 30])

    def test_human_output_ends_with_the_file_to_use(self, capsys, tmp_path):
        model = save(box(10, 10, 10), tmp_path / "part.stl")
        assert analyze.main([str(model), "--height", "20"]) == 0
        last = capsys.readouterr().out.strip().splitlines()[-1]
        assert last == f"➡️ Use this file: {tmp_path / 'part_scaled.stl'}"


class TestChecksThroughTheCli:
    def test_42_degree_wedge_is_not_an_overhang_for_pla(self, capsys, tmp_path):
        """Regression: with PLA's old 50 degree limit the inverted threshold flagged 42."""
        code, document, _ = run_json(capsys, save(wedge(42), tmp_path / "w.stl"), "--material", "PLA")
        overhangs = next(c for c in document["checks"] if c["id"] == "overhangs")
        assert (overhangs["status"], overhangs["area_pct"], overhangs["limit_deg"]) == ("pass", 0.0, 45.0)

    def test_build_volume_message_uses_the_printer_table(self, capsys, tmp_path):
        usable = BUILD_VOLUMES["A1"]
        code, document, _ = run_json(capsys, save(box(usable[0] + 20, 20, 20), tmp_path / "long.stl"),
                                     "--printer", "A1")
        fit = next(c for c in document["checks"] if c["id"] == "build_volume")
        assert fit["status"] == "fail"
        assert " x ".join(f"{v:g}" for v in usable) + " mm usable" in fit["summary"]
        assert "mm^3" not in json.dumps(document)

    def test_printer_names_match_case_insensitively(self, capsys, tmp_path):
        name = next(iter(BUILD_VOLUMES))
        code, document, _ = run_json(capsys, save(box(10, 10, 10), tmp_path / "p.stl"), "--printer", name.upper())
        assert document["printer"] == name


class TestArguments:
    @pytest.mark.parametrize("flag", ["--render", "--no-clean", "--no-simplify", "--output-dir=x"])
    def test_removed_flags_explain_and_exit_2(self, capsys, tmp_path, flag):
        assert analyze.main([str(tmp_path / "x.stl"), flag]) == analyze.EXIT_USAGE
        assert "was removed" in capsys.readouterr().err

    def test_unknown_printer_is_a_usage_error(self, capsys, tmp_path):
        code, document, _ = run_json(capsys, save(box(10, 10, 10), tmp_path / "p.stl"), "--printer", "X9")
        assert code == analyze.EXIT_USAGE
        assert "Known:" in document["error"]["message"]

    def test_unknown_material_says_what_was_used(self, capsys, tmp_path):
        code, document, _ = run_json(capsys, save(box(10, 10, 10), tmp_path / "p.stl"), "--material", "PLA-CF")
        assert document["material"] == "PLA"
        assert any("Unknown material 'PLA-CF'" in note for note in document["notes"])

    def test_unreadable_file_exits_1(self, capsys, tmp_path):
        bad = tmp_path / "bad.stl"
        bad.write_text("not a mesh", encoding="utf-8")
        code, document, _ = run_json(capsys, bad)
        assert code == analyze.EXIT_FAILED
        assert document["error"]["type"] == "file"

    def test_help_lists_the_documented_flags(self, capsys):
        with pytest.raises(SystemExit):
            analyze.main(["--help"])
        text = capsys.readouterr().out
        for flag in ("--height", "--orient", "--repair", "--material", "--printer", "--json",
                     "--purpose", "--unit", "--keep-main", "--no-auto-repair"):
            assert flag in text
