"""Reading Bambu Studio's estimates (bambu_studio_ai.slicing.estimate).

``result_p1s_box.json`` and ``plate_1_header.gcode`` come from one real slice with
Bambu Studio 02.07.01.62 (P1S, 0.20 mm, Bambu PLA Basic, a 20 x 20 x 30 mm box).
"""

import json
import zipfile
from pathlib import Path

import pytest

from bambu_studio_ai.slicing import EstimateError
from bambu_studio_ai.slicing.estimate import (
    estimate_from_3mf,
    parse_duration,
    parse_gcode_header,
    parse_result_json,
)

FIXTURES = Path(__file__).parent / "fixtures" / "slicing"
RESULT = json.loads((FIXTURES / "result_p1s_box.json").read_text(encoding="utf-8"))
HEADER = (FIXTURES / "plate_1_header.gcode").read_text(encoding="utf-8")


def sliced_3mf(path, plates):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("3D/3dmodel.model", "<model/>")
        for number, gcode in enumerate(plates, start=1):
            archive.writestr(f"Metadata/plate_{number}.gcode", gcode)
    return path


def test_result_json_total_includes_the_start_sequence():
    estimate = parse_result_json(RESULT)

    # total_predication (18 min 46 s), not main_predication (12 min 2 s)
    assert estimate.print_time_s == pytest.approx(1125.9, abs=0.1)
    assert estimate.filament_g == pytest.approx(5.08, abs=0.01)
    assert [(use.slot, use.filament_id) for use in estimate.filaments] == [(1, "GFA00")]
    assert estimate.plates == 1
    assert estimate.source == "result.json"
    assert estimate.warnings == ()


def test_gcode_header_gives_the_same_estimate():
    estimate = parse_gcode_header(HEADER.splitlines(keepends=True))

    assert estimate.print_time_s == 18 * 60 + 45
    assert estimate.print_time_s == pytest.approx(parse_result_json(RESULT).print_time_s, abs=1)
    assert estimate.filament_g == pytest.approx(5.08)
    assert estimate.filaments[0].filament_id == "GFA00"
    assert estimate.source == "gcode"


def test_multi_filament_header():
    header = [
        "; model printing time: 1h 2m 3s; total estimated time: 1h 10m 0s\n",
        "; total filament weight [g] : 3.72,1.20\n",
        "; CONFIG_BLOCK_START\n",
        "; filament_ids = GFA00;GFB00\n",
        "; CONFIG_BLOCK_END\n",
    ]
    estimate = parse_gcode_header(header)
    assert estimate.print_time_s == 4200
    assert [(u.slot, u.filament_id, u.grams) for u in estimate.filaments] == [
        (1, "GFA00", 3.72), (2, "GFB00", 1.20),
    ]


def test_result_json_sums_plates_and_keeps_warnings():
    plate = RESULT["sliced_plates"][0]
    second = {**plate, "id": 2, "warning_message": "Floating regions"}
    estimate = parse_result_json({**RESULT, "sliced_plates": [plate, second]})
    assert estimate.plates == 2
    assert estimate.print_time_s == pytest.approx(2 * 1125.9, abs=0.1)
    assert estimate.filament_g == pytest.approx(2 * 5.08, abs=0.01)
    assert estimate.warnings == ("Floating regions",)


def test_result_json_of_a_failed_slice_has_no_estimate():
    failed = {"return_code": -61, "error_string": "Filaments are not compatible with the plate type."}
    with pytest.raises(EstimateError, match="no sliced plates"):
        parse_result_json(failed)


def test_3mf_fallback_sums_every_plate(tmp_path):
    path = sliced_3mf(tmp_path / "two.3mf", [HEADER, HEADER])
    estimate = estimate_from_3mf(path)
    assert estimate.plates == 2
    assert estimate.print_time_s == 2 * 1125
    assert estimate.filament_g == pytest.approx(10.16)


def test_3mf_without_gcode_is_an_error(tmp_path):
    with pytest.raises(EstimateError, match="no plate G-code"):
        estimate_from_3mf(sliced_3mf(tmp_path / "unsliced.3mf", []))


def test_header_without_time_is_an_error():
    with pytest.raises(EstimateError, match="no total estimated time"):
        parse_gcode_header(["; HEADER_BLOCK_START\n", "; CONFIG_BLOCK_END\n"])


@pytest.mark.parametrize(("text", "seconds"), [
    ("18m 45s", 1125), ("1h 2m 3s", 3723), ("1d 0h 0m 1s", 86401), ("45s", 45),
])
def test_durations(text, seconds):
    assert parse_duration(text) == seconds


def test_duration_without_numbers_is_an_error():
    with pytest.raises(EstimateError):
        parse_duration("soon")
