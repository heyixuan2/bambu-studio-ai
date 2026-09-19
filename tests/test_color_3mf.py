"""Bambu Studio project 3MF and vertex-colour OBJ output (bambu_studio_ai.color)."""

import io
import json
import re
import zipfile

import numpy as np
import pytest
import trimesh

from bambu_studio_ai.color import ColorizeOptions, build_obj, build_project, colorize, paint_code, read_project
from bambu_studio_ai.color.bambu_3mf import paint_filament, project_settings
from bambu_studio_ai.color.obj import vertex_labels
from glb_builder import bands, box, grid, png, textured, write_glb

# Filament -> paint_color, from Bambu Studio's TriangleSelector serialisation.
BAMBU_CODES = {1: "4", 2: "8", 3: "0C", 4: "1C", 5: "2C", 6: "3C", 7: "4C", 8: "5C"}
PER_FILAMENT_PROBES = ("filament_diameter", "filament_type", "filament_settings_id", "nozzle_temperature",
                       "filament_extruder_variant", "filament_ids")


def test_paint_codes_match_bambu_studio():
    assert {filament: paint_code(filament) for filament in BAMBU_CODES} == BAMBU_CODES
    assert all(paint_filament(code) == filament for filament, code in BAMBU_CODES.items())
    assert paint_filament("0C0") is None  # a split triangle is not a whole-triangle code
    with pytest.raises(ValueError, match="between 1 and"):
        paint_code(0)


@pytest.mark.parametrize("count", [1, 2, 4, 8])
def test_every_per_filament_setting_has_one_entry_per_filament(count):
    # The slicer only splits painted regions when filament_diameter has > 1 entry and sizes
    # them by filament_colour; the audit's hand-patched project had 2 colours and 1 diameter.
    colours = [f"#{i:02X}{i:02X}{i:02X}" for i in range(count)]
    settings = project_settings(colours)
    assert settings["filament_colour"] == colours
    for key in PER_FILAMENT_PROBES:
        assert len(settings[key]) == count, key
    assert settings["filament_self_index"] == [str(i + 1) for i in range(count)]
    assert len(settings["flush_volumes_matrix"]) == count * count
    assert len(settings["flush_volumes_vector"]) == 2 * count
    assert len(settings["different_settings_to_system"]) == count + 2
    assert settings["printer_settings_id"] == "Bambu Lab A1 0.4 nozzle"


def _cube_result(tmp_path, height=None):
    corners, faces, uv = box((0.04, 0.04, 0.04))
    path = write_glb(tmp_path / "cube.glb", [{"positions": corners, "faces": faces, "uv": uv, "material": 0}],
                     [textured(0)], [png(bands([(200, 30, 30), (30, 180, 40), (30, 60, 200)]))])
    return colorize(path, ColorizeOptions(height_mm=height))


def test_project_paint_codes_match_the_labels(tmp_path):
    result = _cube_result(tmp_path)
    data = build_project(result.vertices, result.faces, result.labels, result.palette.hex, "cube")
    project = read_project(data)
    np.testing.assert_array_equal(project.filaments, result.labels + 1)
    np.testing.assert_array_equal(project.faces, result.faces)
    assert project.settings["filament_colour"] == result.palette.hex
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        mesh = archive.read("3D/Objects/object_1.model").decode()
        root = archive.read("3D/3dmodel.model").decode()
    # Upper case only: Bambu Studio's reader treats lower-case digits as unpainted.
    assert set(re.findall(r'paint_color="([^"]*)"', mesh)) == {"4", "8", "0C"}
    assert "BambuStudio-02.07" in root  # makes Bambu Studio open it as a project


def test_project_is_z_up_on_the_bed_centre_with_the_requested_height(tmp_path):
    result = _cube_result(tmp_path, height=25)
    project = read_project(build_project(result.vertices, result.faces, result.labels, result.palette.hex, "c"))
    placed = project.vertices + project.build_offset
    assert placed[:, 2].min() == pytest.approx(0, abs=1e-4)
    assert placed[:, 2].max() == pytest.approx(25, abs=1e-4)
    centre = (placed.min(axis=0) + placed.max(axis=0)) / 2
    assert centre[:2] == pytest.approx((128, 128), abs=1e-3)  # A1 bed is 256 x 256
    assert trimesh.Trimesh(project.vertices, project.faces, process=False).is_watertight


def test_object_name_is_escaped(tmp_path):
    result = _cube_result(tmp_path)
    data = build_project(result.vertices, result.faces, result.labels, result.palette.hex, 'fox & "friends"')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        settings = archive.read("Metadata/model_settings.config").decode()
        json.loads(archive.read("Metadata/project_settings.config"))
    assert 'value="fox &amp; &quot;friends&quot;"' in settings


def test_obj_has_srgb_vertex_colours_z_up(tmp_path):
    result = _cube_result(tmp_path, height=40)
    text = build_obj(result.vertices, result.faces, result.labels, result.palette.rgb)
    loaded = trimesh.load(io.BytesIO(text.encode()), file_type="obj", process=False)
    assert loaded.extents == pytest.approx((40, 40, 40))
    lines = [line.split() for line in text.splitlines() if line.startswith("v ")]
    colours = {tuple(round(float(v) * 255) for v in line[4:7]) for line in lines}
    assert colours <= {(200, 30, 30), (30, 180, 40), (30, 60, 200)}


def test_vertex_takes_the_majority_colour_of_its_triangles():
    positions, faces, _ = grid(2)
    labels = np.zeros(len(faces), np.int64)
    labels[:3] = 1
    by_vertex = vertex_labels(len(positions), faces, labels, 2)
    corner_only_in_label_0 = [v for v in range(len(positions)) if not np.isin(v, faces[:3]).any()]
    assert (by_vertex[corner_only_in_label_0] == 0).all()
