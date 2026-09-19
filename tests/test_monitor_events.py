"""Event detection for the print monitor (pure logic, no printer)."""

from dataclasses import replace

import pytest

from bambu_studio_ai.monitor import Limits, MonitorState, evaluate
from bambu_studio_ai.printer import parse_status

LIMITS = Limits(nozzle_c=300, bed_c=120)
MIN = 60.0


def status(**fields):
    base = {"gcode_state": "RUNNING", "mc_percent": 10, "layer_num": 5, "total_layer_num": 100,
            "mc_remaining_time": 90, "subtask_name": "cat", "nozzle_temper": 220, "bed_temper": 60}
    base.update(fields)
    return parse_status(base)


def kinds(events):
    return [e.kind for e in events]


def test_idle_printer_produces_nothing():
    state = MonitorState()
    assert evaluate(status(gcode_state="IDLE"), state, 0, LIMITS) == []
    assert state.watching is False


def test_start_then_finish():
    state = MonitorState()
    assert kinds(evaluate(status(), state, 0, LIMITS)) == ["started"]
    assert kinds(evaluate(status(gcode_state="FINISH", mc_percent=100), state, 5 * MIN, LIMITS)) == ["finished"]
    assert state.watching is False


def test_cancelled_print_is_reported_as_stopped():
    state = MonitorState()
    evaluate(status(), state, 0, LIMITS)
    assert kinds(evaluate(status(gcode_state="IDLE"), state, MIN, LIMITS)) == ["stopped"]


def test_failed_print_is_critical():
    state = MonitorState()
    evaluate(status(), state, 0, LIMITS)
    (event,) = evaluate(status(gcode_state="FAILED", print_error=50348044), state, MIN, LIMITS)
    assert (event.kind, event.severity) == ("failed", "critical")
    assert "0300400C" in event.message


def test_pause_is_announced_once_per_pause():
    state = MonitorState()
    evaluate(status(), state, 0, LIMITS)
    assert kinds(evaluate(status(gcode_state="PAUSE"), state, MIN, LIMITS)) == ["paused"]
    assert evaluate(status(gcode_state="PAUSE"), state, 2 * MIN, LIMITS) == []
    evaluate(status(layer_num=6), state, 3 * MIN, LIMITS)
    assert kinds(evaluate(status(gcode_state="PAUSE", layer_num=6), state, 4 * MIN, LIMITS)) == ["paused"]


def test_stall_needs_no_layer_and_no_time_change():
    state = MonitorState()
    evaluate(status(), state, 0, LIMITS)
    # Layer changes keep resetting the clock: no stall even after a long time.
    for minute in range(5, 60, 5):
        assert "alert" not in kinds(evaluate(status(layer_num=5 + minute), state, minute * MIN, LIMITS))
    frozen = status(layer_num=55)
    evaluate(frozen, state, 60 * MIN, LIMITS)
    assert "alert" not in kinds(evaluate(frozen, state, 70 * MIN, LIMITS))
    assert "Print may be stuck" in [e.title for e in evaluate(frozen, state, 81 * MIN, LIMITS)]
    assert "alert" not in kinds(evaluate(frozen, state, 90 * MIN, LIMITS))  # announced once


def test_preparing_printer_is_not_a_stall():
    # Calibration before the first layer can take 20+ minutes.
    state = MonitorState()
    prepare = status(gcode_state="PREPARE", layer_num=0)
    evaluate(prepare, state, 0, LIMITS)
    assert evaluate(prepare, state, 40 * MIN, LIMITS) == []


def test_error_and_hms_codes_are_announced_once():
    state = MonitorState()
    evaluate(status(), state, 0, LIMITS)
    faulty = status(print_error=50348044, hms=[{"attr": 50331904, "code": 131079}])
    assert [e.severity for e in evaluate(faulty, state, MIN, LIMITS)] == ["critical", "warning"]
    assert evaluate(faulty, state, 2 * MIN, LIMITS) == []


@pytest.mark.parametrize(("nozzle", "alert"), [(305, False), (315, True)])
def test_temperature_alert_uses_printer_rating(nozzle, alert):
    state = MonitorState()
    evaluate(status(), state, 0, LIMITS)
    events = evaluate(status(nozzle_temper=nozzle), state, MIN, LIMITS)
    assert ("Nozzle too hot" in [e.title for e in events]) is alert


def test_high_temp_printer_allows_350c():
    state = MonitorState()
    evaluate(status(), state, 0, Limits(nozzle_c=350))
    assert evaluate(status(nozzle_temper=345), state, MIN, Limits(nozzle_c=350)) == []


def test_progress_every_30_minutes():
    state = MonitorState()
    evaluate(status(), state, 0, LIMITS)
    assert evaluate(status(layer_num=6), state, 29 * MIN, LIMITS) == []
    assert kinds(evaluate(status(layer_num=7), state, 31 * MIN, LIMITS)) == ["progress"]


def test_state_round_trips_through_json():
    state = MonitorState()
    evaluate(status(), state, 0, LIMITS)
    again = MonitorState.from_dict({**state.to_dict(), "unknown_future_key": 1})
    assert again == replace(state)
