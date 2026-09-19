"""Tests for monitor.py loop control (no printer needed)."""

import pytest

import monitor


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "SNAPSHOT_DIR", str(tmp_path))
    monkeypatch.setattr(monitor, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(monitor, "LOG_FILE", str(tmp_path / "log.json"))
    monkeypatch.setattr(monitor.time, "sleep", lambda s: None)
    events = []
    monkeypatch.setattr(monitor, "notify", lambda title, msg, snapshot=None: events.append(title))
    return events


def _feed(monkeypatch, results):
    it = iter(results)
    monkeypatch.setattr(monitor, "monitor_once", lambda auto_pause=False: next(it))


def test_idle_without_wait_stops_immediately(isolated, monkeypatch, capsys):
    _feed(monkeypatch, [{"printing": False}])
    monitor.monitor_loop(interval=1)
    assert "monitor stopped" in capsys.readouterr().out


def test_wait_start_waits_then_monitors_until_done(isolated, monkeypatch):
    _feed(monkeypatch, [{"printing": False}, {"printing": False},
                        {"printing": True}, {"printing": True}, {"printing": False}])
    monitor.monitor_loop(interval=1, wait_start_min=5)
    assert "Print Started 🖨️" in isolated


def test_wait_start_gives_up_after_deadline(isolated, monkeypatch, capsys):
    _feed(monkeypatch, [{"printing": False}])
    loop_time = iter([0.0, 10_000.0])
    monkeypatch.setattr(monitor.time, "time", lambda: next(loop_time))
    monitor.monitor_loop(interval=1, wait_start_min=1)
    assert "No print started" in capsys.readouterr().out


def test_unreachable_printer_is_a_failure_not_idle(isolated, monkeypatch):
    _feed(monkeypatch, [{"printing": False, "error": True}] * 5)
    monitor.monitor_loop(interval=1)
    assert "Monitor Error ⛔" in isolated


def test_status_error_from_bambu_py_is_reported(monkeypatch):
    class R:
        returncode = 1
        stdout = "❌ Printer not reachable"
        stderr = ""
    monkeypatch.setattr(monitor.subprocess, "run", lambda *a, **k: R())
    assert "error" in monitor.get_status_dict()
