"""bambu.py: read-only status CLI."""

import json
from pathlib import Path

import pytest

import bambu
from bambu_studio_ai.printer import PrinterAuthError, PrinterConnectionError

FIXTURE = Path(__file__).parent / "fixtures" / "printer" / "p1s_printing.json"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("BAMBU_IP", "192.168.1.50")
    monkeypatch.setenv("BAMBU_SERIAL", "01P00A000000000")
    monkeypatch.setenv("BAMBU_ACCESS_CODE", "12345678")
    monkeypatch.setenv("BAMBU_MODEL", "P1S")


@pytest.fixture
def printer_report(monkeypatch):
    report = json.loads(FIXTURE.read_text())["print"]
    monkeypatch.setattr(bambu, "read_report", lambda settings: report)
    return report


@pytest.mark.parametrize("command", ["print", "pause", "gcode", "snapshot", "light", "speed"])
def test_removed_commands_explain_why(command, capsys):
    assert bambu.main([command, "x"]) == bambu.EXIT_CONFIG
    err = capsys.readouterr().err
    assert "was removed" in err
    assert "bambu.py open" in err


def test_status_not_configured_is_exit_2_with_json_error(capsys):
    assert bambu.main(["status", "--json"]) == bambu.EXIT_CONFIG
    out = capsys.readouterr().out
    assert json.loads(out)["error"]["type"] == "not_configured"


def test_status_json_is_one_document(configured, printer_report, capsys):
    assert bambu.main(["status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "RUNNING"
    assert data["model"] == "P1S"
    assert data["layer"] == 57
    assert data["trays"][1]["active"] is True


def test_status_human_output(configured, printer_report, capsys):
    assert bambu.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "RUNNING · 42% · layer 57/136 · 1 h 11 min left" in out
    assert "Light off" in out
    assert "▶ A2" in out


def test_ams_json(configured, printer_report, capsys):
    assert bambu.main(["ams", "--json"]) == 0
    trays = json.loads(capsys.readouterr().out)["trays"]
    assert [t["color"] for t in trays] == ["#FFFFFF", "#FF6A13", "#000000"]


@pytest.mark.parametrize(("error", "kind"), [
    (PrinterAuthError("printer refused the connection: Not authorized"), "auth"),
    (PrinterConnectionError("no report"), "unreachable"),
])
def test_connection_errors_exit_1(configured, monkeypatch, capsys, error, kind):
    def boom(settings):
        raise error
    monkeypatch.setattr(bambu, "read_report", boom)
    assert bambu.main(["status", "--json"]) == bambu.EXIT_FAILED
    assert json.loads(capsys.readouterr().out)["error"]["type"] == kind


def test_info_needs_no_connection(configured, capsys):
    assert bambu.main(["info", "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["configured"] is True
    assert info["serial"] == "01P0…000"
    assert "12345678" not in json.dumps(info)
