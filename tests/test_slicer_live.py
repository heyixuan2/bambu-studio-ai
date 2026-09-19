"""Slice a real model with the installed Bambu Studio (opt-in: ``pytest -m slicer``).

Needs Bambu Studio 02.05.02 or newer. Skipped when it isn't found.
"""

import json
import zipfile

import pytest

import slice as slice_cli
from bambu_studio_ai.slicing import ProfileLibrary, find_cli, find_profiles_dir

pytestmark = pytest.mark.slicer

_CUBE_FACES = (  # two triangles per face of a unit cube, outward normals
    ((0, 0, -1), [(0, 0, 0), (0, 1, 0), (1, 1, 0)]), ((0, 0, -1), [(0, 0, 0), (1, 1, 0), (1, 0, 0)]),
    ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1)]), ((0, 0, 1), [(0, 0, 1), (1, 1, 1), (0, 1, 1)]),
    ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1)]), ((0, -1, 0), [(0, 0, 0), (1, 0, 1), (0, 0, 1)]),
    ((0, 1, 0), [(0, 1, 0), (0, 1, 1), (1, 1, 1)]), ((0, 1, 0), [(0, 1, 0), (1, 1, 1), (1, 1, 0)]),
    ((-1, 0, 0), [(0, 0, 0), (0, 0, 1), (0, 1, 1)]), ((-1, 0, 0), [(0, 0, 0), (0, 1, 1), (0, 1, 0)]),
    ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1)]), ((1, 0, 0), [(1, 0, 0), (1, 1, 1), (1, 0, 1)]),
)


def write_cube(path, size_mm=20.0):
    lines = ["solid cube"]
    for normal, triangle in _CUBE_FACES:
        lines.append("facet normal {} {} {}".format(*normal))
        lines.append("outer loop")
        lines += ["vertex {} {} {}".format(*(c * size_mm for c in v)) for v in triangle]
        lines += ["endloop", "endfacet"]
    path.write_text("\n".join([*lines, "endsolid cube", ""]), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def bambu_studio():
    cli = find_cli()
    root = find_profiles_dir(cli=cli)
    if cli is None or root is None:
        pytest.skip("Bambu Studio is not installed")
    return ProfileLibrary(root)


@pytest.mark.parametrize(("printer", "machine"), [
    ("P1S", "Bambu Lab P1S 0.4 nozzle"),
    ("A1", "Bambu Lab A1 0.4 nozzle"),
])
def test_slices_a_20mm_cube(bambu_studio, printer, machine, tmp_path, capsys):
    cube = write_cube(tmp_path / "cube.stl")

    assert slice_cli.main([str(cube), "--printer", printer, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["machine_profile"] == machine
    assert data["print_time_s"] > 0
    assert data["filament_g"] > 0
    with zipfile.ZipFile(data["output_file"]) as project:
        gcode = project.read("Metadata/plate_1.gcode").decode("utf-8")
    # Bambu's own start sequence is in the print, not a generic replacement.
    start = bambu_studio.flatten("machine", machine)["machine_start_gcode"]
    first_line = start.splitlines()[0]
    body = gcode.split("; EXECUTABLE_BLOCK_START", 1)[1]
    assert first_line in body
    assert "G29" in body  # bed levelling
