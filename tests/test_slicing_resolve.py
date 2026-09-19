"""Choosing presets from the profile graph (bambu_studio_ai.slicing.resolve).

Runs against a trimmed copy of Bambu Studio 02.07.01.62's BBL profiles. Several tests
are regressions for the old name-guessing resolver (audit S-2, S-3, S-11).
"""

from pathlib import Path

import pytest

from bambu_studio_ai.slicing import (
    PRINTER_FAMILIES,
    PrintRequest,
    ProfileLibrary,
    ResolveError,
    printer_key,
    resolve_profiles,
)

PROFILES = Path(__file__).parent / "fixtures" / "slicing" / "profiles"


@pytest.fixture(scope="module")
def library():
    return ProfileLibrary(PROFILES)


def resolve(library, printer, **kwargs):
    return resolve_profiles(library, PrintRequest(printer=printer, **kwargs))


def test_config_model_keys_map_to_bambu_studio_families():
    assert PRINTER_FAMILIES == {
        "A1 Mini": "Bambu Lab A1 mini", "A1": "Bambu Lab A1", "A2L": "Bambu Lab A2L",
        "P1P": "Bambu Lab P1P", "P1S": "Bambu Lab P1S", "P2S": "Bambu Lab P2S",
        "X1C": "Bambu Lab X1 Carbon", "X1E": "Bambu Lab X1E", "X2D": "Bambu Lab X2D",
        "H2C": "Bambu Lab H2C", "H2S": "Bambu Lab H2S", "H2D": "Bambu Lab H2D",
        "H2D Pro": "Bambu Lab H2D Pro",
    }


@pytest.mark.parametrize(("typed", "key"), [
    ("P1S", "P1S"), ("p1s", "P1S"), ("a1 mini", "A1 Mini"), ("A1mini", "A1 Mini"),
    ("A1", "A1"), ("X1 Carbon", "X1C"), ("h2d-pro", "H2D Pro"), ("H2D", "H2D"),
    ("Bambu Lab P2S", "P2S"), ("X1", None), ("Unknown", None), ("", None),
])
def test_printer_names_are_normalised(typed, key):
    assert printer_key(typed) == key


def test_a1_gets_a1_presets_not_a1_mini(library):
    # Regression: the old glob "A1*" matched A1 mini presets.
    choice = resolve(library, "A1")
    assert choice.machine == "Bambu Lab A1 0.4 nozzle"
    assert choice.process == "0.20mm Standard @BBL A1"
    assert choice.filament == "Bambu PLA Basic @BBL A1"

    mini = resolve(library, "A1 Mini")
    assert mini.machine == "Bambu Lab A1 mini 0.4 nozzle"
    assert mini.process == "0.20mm Standard @BBL A1M"
    assert mini.filament == "Bambu PLA Basic @BBL A1M"


def test_h2d_gets_h2d_presets_not_h2d_pro(library):
    choice = resolve(library, "H2D", material="Bambu PETG HF")
    assert choice.machine == "Bambu Lab H2D 0.4 nozzle"
    assert choice.process == "0.20mm Standard @BBL H2D"
    # Regression: the old resolver picked "Bambu PETG HF @BBL H2DP 0.2 nozzle".
    assert choice.filament == "Bambu PETG HF @BBL H2D 0.4 nozzle"

    pro = resolve(library, "H2D Pro")
    assert (pro.machine, pro.process, pro.filament) == (
        "Bambu Lab H2D Pro 0.4 nozzle", "0.20mm Standard @BBL H2DP", "Bambu PLA Basic @BBL H2DP",
    )


def test_p2s_uses_its_own_presets(library):
    # Regression: P2S was sliced with P1S profiles (different bed exclusion, speed, start G-code).
    choice = resolve(library, "P2S")
    assert choice.machine == "Bambu Lab P2S 0.4 nozzle"
    assert choice.process == "0.20mm Standard @BBL P2S"
    assert choice.filament == "Bambu PLA Basic @BBL P2S"


def test_nozzle_selects_machine_process_and_filament(library):
    choice = resolve(library, "P1S", nozzle_mm=0.8)
    assert choice.nozzle == "0.8"
    assert choice.machine == "Bambu Lab P1S 0.8 nozzle"
    assert choice.process == "0.40mm Standard @BBL X1C 0.8 nozzle"
    assert choice.filament == "Bambu PLA Basic @BBL X1C 0.8 nozzle"
    assert choice.layer_height_mm == pytest.approx(0.4)


def test_draft_on_a_04_nozzle_is_never_an_08_nozzle_preset(library):
    # Regression: "0.24mm*@BBL X1C*" matched "0.24mm Standard @BBL X1C 0.8 nozzle".
    choice = resolve(library, "P1S", quality="draft")
    assert choice.process == "0.24mm Draft @BBL X1C"
    assert choice.layer_height_mm == pytest.approx(0.24)


def test_default_filament_is_the_one_made_for_this_machine(library):
    # Regression: "Bambu PLA Basic @BBL X1C" was chosen for a P1S, which it doesn't list.
    choice = resolve(library, "P1S")
    assert choice.filament == "Bambu PLA Basic @BBL P1S 0.4 nozzle"
    assert choice.material == "PLA"


@pytest.mark.parametrize(("printer", "material", "filament"), [
    ("P1S", "PLA", "Bambu PLA Basic @BBL P1S 0.4 nozzle"),  # the default is already PLA
    ("P1S", "pla", "Bambu PLA Basic @BBL P1S 0.4 nozzle"),
    ("P1S", "PETG", "Generic PETG"),
    ("A1", "PETG", "Generic PETG @BBL A1"),
    ("A1", "Bambu PLA Basic", "Bambu PLA Basic @BBL A1"),
    ("A1", "Bambu PLA Basic @BBL A1", "Bambu PLA Basic @BBL A1"),
])
def test_materials_by_type_or_name(library, printer, material, filament):
    assert resolve(library, printer, material=material).filament == filament


def test_unknown_material_lists_what_the_printer_can_use(library):
    with pytest.raises(ResolveError) as error:
        resolve(library, "P1S", material="PEEK")
    assert "No PEEK filament profile for Bambu Lab P1S 0.4 nozzle" in str(error.value)
    assert "PETG" in str(error.value)
    assert "PLA" in str(error.value)


@pytest.mark.parametrize(("printer", "quality", "process"), [
    ("P1S", "standard", "0.20mm Standard @BBL X1C"),
    ("P1S", "fine", "0.12mm Fine @BBL X1C"),  # not the slower "0.12mm High Quality"
    ("A1", "draft", "0.24mm Draft @BBL A1"),
    ("H2D", "draft", "0.24mm Standard @BBL H2D"),  # no "Draft" preset: nearest to 0.6 x nozzle
    ("H2D", "fine", "0.12mm Fine @BBL H2D"),
])
def test_quality_levels(library, printer, quality, process):
    assert resolve(library, printer, quality=quality).process == process


def test_exact_layer_height_prefers_the_everyday_preset(library):
    choice = resolve(library, "P1S", layer_height_mm=0.16)
    assert choice.process == "0.16mm Optimal @BBL X1C"


def test_layer_height_without_a_preset_lists_the_available_ones(library):
    with pytest.raises(ResolveError, match=r"No 0.3 mm process .* 0.12, 0.16, 0.2, 0.24"):
        resolve(library, "P1S", layer_height_mm=0.3)


def test_missing_nozzle_lists_the_available_ones(library):
    with pytest.raises(ResolveError, match=r"Bambu Lab P2S has no 0.6 mm nozzle .* Nozzles: 0.4 mm"):
        resolve(library, "P2S", nozzle_mm=0.6)


def test_printer_missing_from_the_installed_profiles_asks_for_an_update(library):
    with pytest.raises(ResolveError, match="Update Bambu Studio"):
        resolve(library, "X2D")


def test_unknown_printer_key(library):
    with pytest.raises(ResolveError, match="Unknown printer"):
        resolve(library, "Ender 3")


def test_bed_type_is_the_printers_default_plate(library):
    assert resolve(library, "A1 Mini").bed_type == "Textured PEI Plate"
