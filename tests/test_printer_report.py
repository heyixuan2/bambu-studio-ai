"""Parsing of the printer's MQTT status report (bambu_studio_ai.printer)."""

import json
from pathlib import Path

import pytest

from bambu_studio_ai.printer.client import PrinterSettings, ReportCollector
from bambu_studio_ai.printer.report import parse_status, parse_trays

FIXTURE = Path(__file__).parent / "fixtures" / "printer" / "p1s_printing.json"


@pytest.fixture
def report():
    return json.loads(FIXTURE.read_text())["print"]


def test_status_fields(report):
    status = parse_status(report)
    assert status.state == "RUNNING"
    assert status.active is True
    assert status.progress_pct == 42
    assert status.remaining_min == 71
    assert (status.layer, status.total_layers) == (57, 136)
    assert status.file == "cat_figurine"
    assert (status.nozzle_temp, status.nozzle_target) == (219.8, 220.0)
    assert (status.bed_temp, status.bed_target) == (59.9, 60.0)
    assert status.speed == "standard"


def test_light_off_is_reported_as_off(report):
    # Regression: v2.0 printed "Light: ON" because the string "off" is truthy.
    assert parse_status(report).light == "off"


def test_error_and_hms_codes(report):
    status = parse_status(report)
    assert status.print_error is None
    assert status.hms == ("0300_0100_0002_0007",)
    report["print_error"] = 50348044
    assert parse_status(report).print_error == "0300400C"


def test_trays_skip_empty_slots_and_mark_active(report):
    trays = parse_trays(report)
    assert [(t.unit, t.slot) for t in trays] == [(0, 0), (0, 1), (0, 3)]
    assert trays[1].color == "#FF6A13"
    assert trays[1].name == "PLA Basic"
    assert [t.active for t in trays] == [False, True, False]
    assert trays[2].remaining_pct is None  # -1 means unknown


def test_external_spool_is_listed_when_loaded(report):
    report["vt_tray"] = {"id": "254", "tray_type": "TPU", "tray_color": "112233FF"}
    report["ams"]["tray_now"] = "254"
    external = parse_trays(report)[-1]
    assert (external.unit, external.material, external.active) == (None, "TPU", True)


def test_idle_printer_is_not_active():
    status = parse_status({"gcode_state": "IDLE", "mc_percent": 0})
    assert status.active is False
    assert status.trays == ()


def test_missing_fields_become_none():
    status = parse_status({})
    assert status.state == "UNKNOWN"
    assert status.nozzle_temp is None
    assert status.speed is None
    assert status.light is None


def test_status_is_json_serialisable(report):
    data = json.loads(json.dumps(parse_status(report).to_dict()))
    assert data["trays"][1]["color"] == "#FF6A13"


def test_collector_waits_for_a_full_report():
    collector = ReportCollector("SERIAL")
    collector.feed(b'{"print": {"nozzle_temper": 30}}')
    assert not collector.done.is_set()
    collector.feed(b"not json")
    collector.feed(b'{"info": {}}')
    collector.feed(b'{"print": {"gcode_state": "IDLE", "mc_percent": 0}}')
    assert collector.done.is_set()
    assert collector.report == {"nozzle_temper": 30, "gcode_state": "IDLE", "mc_percent": 0}


def test_settings_report_missing_keys():
    assert PrinterSettings(ip="", serial="S", access_code="").missing() == ["printer_ip", "access_code"]
