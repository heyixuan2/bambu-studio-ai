"""The legacy tables in common.py, now derived from assets/*.json for the older scripts."""

import pytest

import common
from bambu_studio_ai import hardware


def test_build_volumes_cover_every_printer_with_a_per_side_margin():
    from common import BUILD_VOLUMES

    assert list(BUILD_VOLUMES) == list(hardware.printers())
    assert BUILD_VOLUMES["A1"] == (246, 246, 256)
    assert BUILD_VOLUMES["A2L"] == (320, 310, 325)
    # Regression (audit M-1): the H2C was 230³; its shared two-nozzle region is 300 × 320 × 320.
    assert BUILD_VOLUMES["H2C"] == (290, 310, 320)
    assert BUILD_VOLUMES["X2D"] == (225.5, 246, 256)


def test_materials_have_every_key_analyze_reads():
    from common import MATERIALS

    for name in ("PLA", "PETG", "TPU", "ABS", "ASA", "PA", "PC", "PLA-CF", "TPU FOR AMS", "SUPPORT FOR PLA"):
        props = MATERIALS[name]
        assert set(props) == {"min_wall", "min_temp", "max_temp", "bed", "infill_deco", "infill_func", "enclosed"}
        assert props["min_temp"] < props["max_temp"]
    assert MATERIALS["ABS"]["enclosed"] and not MATERIALS["PLA"]["enclosed"]


def test_peek_is_gone():
    from common import MATERIALS

    assert "PEEK" not in MATERIALS


def test_printer_sets():
    from common import ENCLOSED_PRINTERS, HIGH_TEMP_PRINTERS

    assert HIGH_TEMP_PRINTERS == {"H2C", "H2S", "H2D", "H2D Pro"}
    assert ENCLOSED_PRINTERS == {"P1S", "P2S", "X1C", "X1E", "X2D", "H2C", "H2S", "H2D", "H2D Pro"}


def test_unknown_attribute_still_raises():
    with pytest.raises(AttributeError):
        common.NOT_A_TABLE  # noqa: B018
