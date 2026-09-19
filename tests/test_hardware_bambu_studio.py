"""The shipped hardware data agrees with the installed Bambu Studio's own files.

Skipped when Bambu Studio isn't installed (CI). Set ``BAMBU_STUDIO_RESOURCES`` to its
``Resources`` folder to run these on Linux.
"""

import json
from pathlib import Path

import pytest

from bambu_studio_ai import hardware
from datagen import bambu_studio as bs
from datagen import import_bambu_studio

ASSETS = Path(__file__).resolve().parent.parent / "assets"
RESOURCES = bs.resources_dir()

pytestmark = pytest.mark.skipif(RESOURCES is None, reason="Bambu Studio is not installed")


@pytest.fixture(scope="module")
def caps():
    return bs.capabilities(RESOURCES)


def _recorded_version(name):
    return json.loads((ASSETS / name).read_text(encoding="utf-8"))["bambu_studio"]["profiles_version"]


@pytest.mark.parametrize("key", list(hardware.printers()))
def test_volumes_match_the_machine_profile(key):
    printer = hardware.printer(key)
    studio = bs.machine_volumes(RESOURCES, printer.machine)
    assert printer.build_volume_mm == tuple(studio["plate"])
    assert printer.dual_nozzle_volume_mm == (tuple(studio["dual_nozzle"]) if studio["dual_nozzle"] else None)
    if printer.extruders:
        assert [e.volume_mm for e in printer.extruders] == [tuple(v) for v in studio["extruders"]]
        assert [e.max_hotends for e in printer.extruders] == studio["max_hotends"]
        assert [e.drive for e in printer.extruders] == [t.lower() for t in studio["extruder_types"]]
    assert printer.nozzle == studio["nozzle_type"]


@pytest.mark.parametrize("key", list(hardware.printers()))
def test_limits_match_the_device_file(key, caps):
    printer = hardware.printer(key)
    studio = caps[printer.machine]
    assert set(printer.model_ids) == set(studio["model_ids"])
    assert printer.max_nozzle_c == studio["max_nozzle_c"]
    if studio["max_bed_c"] is not None:  # Bambu Studio has no bed limit for the X1 Carbon
        assert printer.max_bed_c == studio["max_bed_c"]
    assert printer.chamber_max_c == studio["chamber_max_c"]
    assert printer.enclosed == studio["enclosed"]


def test_every_bambu_studio_printer_is_known(caps):
    """A new printer in Bambu Studio should be added to assets/printers.json."""
    known = {p.machine for p in hardware.printers().values()}
    # The original X1 (BL-P002) was never sold widely and shares the X1 Carbon's limits.
    assert set(caps) - known <= {"Bambu Lab X1"}


def test_materials_and_filaments_are_current():
    installed = bs.versions(RESOURCES)["profiles"]
    for name in ("materials.json", "filaments.json"):
        if _recorded_version(name) != installed:
            pytest.skip(f"Bambu Studio profiles {installed} installed, {name} is from "
                        f"{_recorded_version(name)}: run python3 tests/datagen/import_bambu_studio.py --write")
    assert import_bambu_studio.main([]) == 0, "run python3 tests/datagen/import_bambu_studio.py --write"
