"""Loading and flattening Bambu Studio profiles (bambu_studio_ai.slicing.profiles).

The fixture tree is a trimmed copy of Bambu Studio 02.07.01.62's own BBL profiles
(profile bundle 02.07.00.08): every preset used here plus its parents and includes,
with long G-code cut to its first lines.
"""

import json
from pathlib import Path

import pytest

from bambu_studio_ai.slicing import ProfileError, ProfileLibrary

PROFILES = Path(__file__).parent / "fixtures" / "slicing" / "profiles"


@pytest.fixture(scope="module")
def library():
    return ProfileLibrary(PROFILES)


def write_bundle(root, presets):
    """A tiny vendor bundle: presets is [(kind, name, sub_path, data)]."""
    index = {"version": "01.00.00.00", "machine_list": [], "process_list": [], "filament_list": []}
    root.mkdir(parents=True, exist_ok=True)
    for kind, name, sub_path, data in presets:
        index[f"{kind}_list"].append({"name": name, "sub_path": sub_path})
        path = root / "BBL" / sub_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    (root / "BBL.json").write_text(json.dumps(index), encoding="utf-8")
    return ProfileLibrary(root)


def test_filament_keeps_its_own_name_after_include(library):
    # Regression (audit S-6): merging the include template overwrote the leaf's name,
    # so the sliced 3MF named its filament "fdm_filament_template_direct_dual".
    leaf = "Bambu PLA Basic @BBL P1S 0.4 nozzle"
    assert library.raw("filament", leaf)["include"] == ["fdm_filament_template_direct_dual"]

    flat = library.flatten("filament", leaf)

    assert flat["name"] == leaf
    assert flat["setting_id"] == "GFSA00_34"
    assert flat["instantiation"] == "true"
    assert flat["from"] == "system"
    assert flat["type"] == "filament"
    assert flat["filament_id"] == "GFA00"  # the product id comes from the @base parent
    assert flat["filament_flow_ratio"] == ["0.98", "0.985"]  # own value, not the template's
    assert "inherits" not in flat
    assert "include" not in flat


def test_machine_is_flattened_through_its_whole_parent_chain(library):
    raw = library.raw("machine", "Bambu Lab P1S 0.4 nozzle")
    assert "printable_area" not in raw

    flat = library.flatten("machine", "Bambu Lab P1S 0.4 nozzle")

    assert flat["name"] == "Bambu Lab P1S 0.4 nozzle"
    assert flat["setting_id"] == "GM014"
    assert flat["printable_area"] == ["0x0", "256x0", "256x256", "0x256"]  # from 001_common
    assert flat["printer_model"] == "Bambu Lab P1S"
    assert flat["default_print_profile"] == "0.20mm Standard @BBL X1C"


def test_gcode_templates_are_copied_verbatim(library):
    flat = library.flatten("machine", "Bambu Lab P1S 0.4 nozzle")
    for template in library.raw("machine", "Bambu Lab P1S 0.4 nozzle")["include"]:
        for key, value in library.raw("machine", template).items():
            if key.endswith("_gcode"):
                assert flat[key] == value, key


def test_own_include_beats_the_parents_include(library):
    # The 0.8 nozzle machine inherits the 0.4 one (and so its start G-code) but
    # includes its own start G-code template, which must win.
    flat = library.flatten("machine", "Bambu Lab P1S 0.8 nozzle")
    own = library.raw("machine", "Bambu Lab P1S 0.8 nozzle template machine_start_gcode")

    assert flat["machine_start_gcode"] == own["machine_start_gcode"]
    assert flat["machine_start_gcode"].startswith(";===== machine: P1S-0.8")
    assert flat["setting_id"] == "GM017"
    assert flat["nozzle_diameter"] == ["0.8"]


def test_flatten_returns_a_copy(library):
    first = library.flatten("process", "0.20mm Standard @BBL X1C")
    first["layer_height"] = "9"
    assert library.flatten("process", "0.20mm Standard @BBL X1C")["layer_height"] == "0.2"


def test_instances_are_only_user_selectable_presets(library):
    names = [name for name, _ in library.instances("filament")]
    assert "Bambu PLA Basic @BBL A1" in names
    assert "Bambu PLA Basic @base" not in names
    assert "fdm_filament_template_direct_dual" not in names


def test_preset_names_come_from_the_index_not_file_names(tmp_path):
    # Bambu names some files differently from their presets ("PA/PET" -> "PA PET.json").
    lib = write_bundle(tmp_path, [
        ("filament", "Support For PA/PET", "filament/Support For PA PET.json",
         {"name": "Support For PA/PET", "instantiation": "true", "filament_type": ["PA"]}),
    ])
    assert lib.flatten("filament", "Support For PA/PET")["filament_type"] == ["PA"]


def test_setting_id_is_never_inherited(tmp_path):
    lib = write_bundle(tmp_path, [
        ("machine", "parent", "machine/parent.json", {"name": "parent", "setting_id": "GM001"}),
        ("machine", "child", "machine/child.json", {"name": "child", "inherits": "parent"}),
    ])
    assert "setting_id" not in lib.flatten("machine", "child")


def test_missing_parent_is_an_error(tmp_path):
    lib = write_bundle(tmp_path, [
        ("process", "child", "process/child.json", {"name": "child", "inherits": "gone"}),
    ])
    with pytest.raises(ProfileError, match="gone"):
        lib.flatten("process", "child")


def test_inheritance_loop_is_an_error(tmp_path):
    lib = write_bundle(tmp_path, [
        ("process", "a", "process/a.json", {"name": "a", "inherits": "b"}),
        ("process", "b", "process/b.json", {"name": "b", "inherits": "a"}),
    ])
    with pytest.raises(ProfileError, match="loops"):
        lib.flatten("process", "a")


def test_index_cannot_point_outside_the_bundle(tmp_path):
    lib = write_bundle(tmp_path / "bundle", [
        ("process", "x", "../../secret.json", {"name": "x"}),
    ])
    assert (tmp_path / "secret.json").is_file()
    with pytest.raises(ProfileError, match="outside"):
        lib.raw("process", "x")


def test_missing_index_is_an_error(tmp_path):
    with pytest.raises(ProfileError, match=r"BBL\.json"):
        ProfileLibrary(tmp_path)
