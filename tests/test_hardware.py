"""bambu_studio_ai.hardware: printer and material data, lookup, fit and compatibility."""

import json
from pathlib import Path

import pytest

from bambu_studio_ai import _json, hardware

REAL_ASSETS = Path(hardware.__file__).resolve().parents[2] / "assets"
MODEL_KEYS = ["A1 Mini", "A1", "A2L", "P1P", "P1S", "P2S", "X1C", "X1E", "X2D",
              "H2C", "H2S", "H2D", "H2D Pro"]


def test_printer_table_has_exactly_the_supported_models():
    assert list(hardware.printers()) == MODEL_KEYS


@pytest.mark.parametrize("name, key", [
    ("a1 mini", "A1 Mini"), ("A1M", "A1 Mini"), ("Bambu Lab A1 mini", "A1 Mini"),
    ("X1 Carbon", "X1C"), ("x1-carbon", "X1C"), ("BL-P001", "X1C"),
    ("H2D Pro", "H2D Pro"), ("h2dpro", "H2D Pro"), ("H2DP", "H2D Pro"), ("O1E", "H2D Pro"),
    ("h2d", "H2D"), ("a2l", "A2L"), ("O1C2", "H2C"), ("  p1s ", "P1S"),
])
def test_printer_lookup_accepts_names_aliases_and_model_ids(name, key):
    assert hardware.printer(name).key == key


def test_unknown_printer_lists_the_known_ones():
    with pytest.raises(hardware.UnknownHardwareError, match="Known printers: A1 Mini, A1, A2L"):
        hardware.printer("Ender 3")


def test_h2c_volume_is_the_real_plate_not_a_placeholder():
    """Regression (audit M-1): the H2C was listed as 230³ although it has a 330 × 320 mm plate."""
    h2c = hardware.printer("H2C")
    assert h2c.build_volume_mm == (330, 320, 325)
    assert h2c.volumes["left"] == (325, 320, 320)
    assert h2c.volumes["right"] == (305, 320, 325)
    assert h2c.extruders[1].max_hotends == 6


def test_a2l_and_h2d_pro_are_known():
    assert hardware.printer("A2L").build_volume_mm == (330, 320, 325)
    assert hardware.printer("H2D Pro").max_nozzle_c == 350


@pytest.mark.parametrize("key, nozzle, bed", [
    ("H2S", 350, 120), ("H2D Pro", 350, 120), ("X1E", 320, 110), ("A1 Mini", 300, 80), ("A2L", 300, 80),
])
def test_rated_temperatures(key, nozzle, bed):
    printer = hardware.printer(key)
    assert (printer.max_nozzle_c, printer.max_bed_c) == (nozzle, bed)


def test_discontinued_models():
    gone = {key for key, p in hardware.printers().items() if p.discontinued}
    assert gone == {"P1P", "X1C", "X1E"}
    assert hardware.printer("X1C").status == "discontinued 2026-03-31"


@pytest.mark.parametrize("printer", MODEL_KEYS)
def test_printer_record_is_consistent(printer):
    p = hardware.printer(printer)
    assert p.enclosed == (p.chamber != "none")
    assert (p.chamber_max_c is not None) == p.chamber.startswith("heated")
    assert p.nozzle in {"hardened_steel", "stainless_steel"}
    assert p.sources and p.retrieved
    plate = p.build_volume_mm
    for region in p.volumes.values():
        assert all(r <= full for r, full in zip(region, plate))
    if p.dual_nozzle_volume_mm is not None:
        assert len(p.extruders) == 2
        for extruder in p.extruders:
            assert all(d <= e for d, e in zip(p.dual_nozzle_volume_mm, extruder.volume_mm))


# ─── usable_volume ────────────────────────────────────────────────────


def test_usable_volume_takes_the_margin_off_each_side_but_not_the_top():
    assert hardware.usable_volume(hardware.printer("A1"), 5) == (246, 246, 256)
    assert hardware.usable_volume(hardware.printer("A1"), 0) == (256, 256, 256)


def test_usable_volume_defaults_to_the_region_both_nozzles_reach():
    """A part checked against the whole H2D plate could need both nozzles to reach it."""
    h2d = hardware.printer("H2D")
    assert h2d.fit_region == "dual_nozzle"
    assert hardware.usable_volume(h2d) == (290, 310, 320)
    assert hardware.usable_volume(h2d, region="right") == (315, 310, 325)
    assert hardware.usable_volume(h2d, region="plate") == (340, 310, 325)


def test_usable_volume_x2d_dual_region_is_fractional():
    assert hardware.usable_volume(hardware.printer("X2D"), 0) == (235.5, 256, 256)


def test_usable_volume_rejects_bad_arguments():
    a1 = hardware.printer("A1")
    with pytest.raises(ValueError, match="no 'left' region"):
        hardware.usable_volume(a1, region="left")
    with pytest.raises(ValueError, match="negative"):
        hardware.usable_volume(a1, -1)
    with pytest.raises(ValueError, match="leaves no room"):
        hardware.usable_volume(a1, 200)


# ─── Materials ────────────────────────────────────────────────────────


@pytest.mark.parametrize("name, key", [
    ("pla", "PLA"), ("PLA+", "PLA"), ("TPU", "TPU 95A"), ("tpu 95a hf", "TPU 95A"),
    ("PAHT-CF", "PA-CF"), ("Support W", "Support for PLA"), ("TPU-AMS", "TPU for AMS"),
])
def test_material_lookup(name, key):
    assert hardware.material(name).key == key


def test_peek_is_explicitly_unsupported():
    """Regression: PEEK was listed as printable at 330–350 °C on the H2C/H2D."""
    assert "PEEK" not in hardware.materials()
    with pytest.raises(hardware.UnsupportedMaterialError, match="350 °C"):
        hardware.material("peek")
    for key in ("H2C", "H2D", "H2S", "H2D Pro"):
        assert hardware.printer(key).max_nozzle_c <= 350


def test_only_tpu_for_ams_goes_through_the_ams():
    tpus = {key: m.ams_compatible for key, m in hardware.materials().items() if m.key.startswith("TPU")}
    assert tpus == {"TPU 95A": False, "TPU 90A": False, "TPU 85A": False, "TPU for AMS": True}


def test_fibre_filled_materials_are_abrasive():
    abrasive = {key for key, m in hardware.materials().items() if m.abrasive}
    assert abrasive == {"PLA-CF", "PETG-CF", "PA-CF", "PPA-CF", "PPS-CF"}


def test_every_material_names_known_printers():
    known = set(hardware.printers())
    for m in hardware.materials().values():
        assert set(m.printers) <= known, m.key
        assert m.nozzle_c[0] < m.nozzle_c[1]


def test_pps_cf_is_limited_to_heated_chamber_printers():
    pps = hardware.material("PPS-CF")
    assert pps.needs_heated_chamber
    assert set(pps.printers) == {"X1E", "H2C", "H2S", "H2D", "H2D Pro"}


def test_material_issues_on_a_suitable_pair_is_empty():
    assert hardware.material_issues(hardware.printer("H2D"), hardware.material("PPS-CF")) == []
    assert hardware.material_issues(hardware.printer("A1"), hardware.material("PLA")) == []


def test_material_issues_explains_each_problem():
    issues = hardware.material_issues(hardware.printer("P1S"), hardware.material("PPS-CF"))
    assert any("nozzle reaches 300 °C" in i for i in issues)
    assert any("heated chamber" in i for i in issues)
    assert any("hardened-steel" in i for i in issues)
    assert any("no PPS-CF profile" in i for i in issues)
    assert hardware.material_issues(hardware.printer("A1"), hardware.material("ABS")) == [
        "ABS needs an enclosed printer; the A1 is open-frame."
    ]
    assert hardware.material_issues(hardware.printer("A1 Mini"), hardware.material("ABS"))[-1] == (
        "Bambu Studio has no ABS profile for the A1 mini."
    )


# ─── Data errors ──────────────────────────────────────────────────────


@pytest.fixture
def assets(tmp_path, monkeypatch):
    """Point the loader at a scratch assets folder with fresh caches."""
    monkeypatch.setattr(_json, "ASSETS_DIR", tmp_path)
    hardware._printer_table.cache_clear()
    yield tmp_path
    hardware._printer_table.cache_clear()


def test_missing_asset_is_a_data_file_error(assets):
    with pytest.raises(_json.DataFileError, match="printers.json"):
        hardware.printers()


def test_malformed_printer_names_the_field(assets):
    good = json.loads((REAL_ASSETS / "printers.json").read_text("utf-8"))
    good["printers"]["A1"]["chamber"] = "warm"
    (assets / "printers.json").write_text(json.dumps(good), encoding="utf-8")
    with pytest.raises(_json.DataFileError, match="A1.chamber"):
        hardware.printers()


def test_duplicate_names_are_rejected(assets):
    good = json.loads((REAL_ASSETS / "printers.json").read_text("utf-8"))
    good["printers"]["A1"]["aliases"] = ["A1 mini"]
    (assets / "printers.json").write_text(json.dumps(good), encoding="utf-8")
    with pytest.raises(_json.DataFileError, match="also names"):
        hardware.printers()
