"""monitor.py: loop control and CLI (no printer needed)."""

import json

import pytest

import monitor
from bambu_studio_ai.printer import PrinterConnectionError, parse_status


@pytest.fixture
def printer(monkeypatch):
    """Feed monitor.check() a scripted sequence of printer reports."""
    monkeypatch.setenv("BAMBU_IP", "192.168.1.50")
    monkeypatch.setenv("BAMBU_SERIAL", "01P00A000000000")
    monkeypatch.setenv("BAMBU_ACCESS_CODE", "12345678")
    monkeypatch.setattr(monitor.time, "sleep", lambda s: None)
    monkeypatch.setattr(monitor, "desktop_notify", lambda *a: None)
    reports = []

    def fake_read(settings):
        item = reports.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(monitor, "read_report", fake_read)
    return reports


RUNNING = {"gcode_state": "RUNNING", "mc_percent": 10, "layer_num": 5, "total_layer_num": 100}
IDLE = {"gcode_state": "IDLE", "mc_percent": 0}
FINISH = {"gcode_state": "FINISH", "mc_percent": 100}


def test_idle_without_wait_stops_immediately(printer, capsys):
    printer.append(IDLE)
    assert monitor.main([]) == 0
    assert "No print running" in capsys.readouterr().err


def test_wait_start_then_watch_until_finished(printer, capsys):
    printer.extend([IDLE, IDLE, RUNNING, {**RUNNING, "layer_num": 6}, FINISH])
    assert monitor.main(["--wait-start", "5"]) == 0
    out = capsys.readouterr().out
    assert "📢 NOTIFY: Watching print" in out
    assert "📢 NOTIFY: Print finished" in out


def test_json_events_are_one_object_per_line(printer, capsys):
    printer.extend([RUNNING, FINISH])
    assert monitor.main(["--json"]) == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e["kind"] for e in events] == ["started", "finished"]


def test_lost_printer_gives_up_after_max_failures(printer, capsys):
    printer.extend([RUNNING] + [PrinterConnectionError("no report")] * monitor.MAX_FAILURES)
    assert monitor.main([]) == monitor.EXIT_FAILED
    assert "Monitor stopped" in capsys.readouterr().out


def test_once_keeps_state_between_runs(printer, capsys):
    printer.extend([RUNNING, FINISH])
    assert monitor.main(["--once"]) == 0
    assert monitor.main(["--once"]) == 0
    out = capsys.readouterr().out
    assert "Watching print" in out and "Print finished" in out


def test_status_reads_the_log_offline(printer, capsys):
    printer.extend([RUNNING, FINISH])
    monitor.main([])
    capsys.readouterr()
    assert monitor.main(["--status"]) == 0
    assert "Print finished" in capsys.readouterr().out


def test_auto_pause_flag_explains_removal(capsys):
    assert monitor.main(["--auto-pause"]) == monitor.EXIT_CONFIG
    assert "removed" in capsys.readouterr().err


def test_not_configured_is_exit_2(capsys):
    assert monitor.main(["--once"]) == monitor.EXIT_CONFIG


@pytest.mark.parametrize("model, nozzle, bed", [
    ("H2D", 350, 120),
    ("H2S", 350, 120),      # regression: was 300 °C, so every H2S print raised a false alarm
    ("H2D Pro", 350, 120),  # regression: missing, fell back to 300 °C
    ("X1E", 320, 110),
    ("A1 Mini", 300, 80),
    ("a2l", 300, 80),
    ("X1 Carbon", 300, 110),
])
def test_limits_come_from_printers_json(model, nozzle, bed):
    limits = monitor.limits_for(model)
    assert (limits.nozzle_c, limits.bed_c) == (nozzle, bed)


@pytest.mark.parametrize("model", ["", "Ender 3", None])
def test_unknown_printer_gets_the_highest_limits(model):
    """An unidentified printer must never raise a false over-temperature alert."""
    limits = monitor.limits_for(model)
    assert (limits.nozzle_c, limits.bed_c) == (350, 120)
