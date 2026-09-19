"""assets/filaments.json and its loader: Bambu Lab's official colour table."""

import json
import re
from pathlib import Path

import pytest

from bambu_studio_ai.filaments import PLAIN_FINISHES, filament_colors

FILAMENTS_JSON = Path(__file__).resolve().parent.parent / "assets" / "filaments.json"


@pytest.fixture(scope="module")
def document():
    return json.loads(FILAMENTS_JSON.read_text(encoding="utf-8"))


def test_every_colour_is_well_formed(document):
    finishes = set(document["finishes"])
    for color in document["colors"]:
        assert re.fullmatch(r"#[0-9A-F]{6}", color["hex"]), color
        assert all(re.fullmatch(r"#[0-9A-F]{6}", h) for h in color.get("hexes", [color["hex"]])), color
        assert color["finish"] in finishes, color
        assert color["pattern"] in {"solid", "gradient", "multicolor"}, color
        assert color["line"] in document["lines"], color
        assert re.fullmatch(r"\d{5}", color["code"]), color
        assert color["name"], color


def test_no_duplicate_colours(document):
    codes = [c["code"] for c in document["colors"]]
    names = [(c["line"], c["name"]) for c in document["colors"]]
    assert len(codes) == len(set(codes))
    assert len(names) == len(set(names))


def test_records_which_bambu_studio_it_came_from(document):
    assert re.fullmatch(r"\d\d\.\d\d\.\d\d\.\d\d", document["bambu_studio"]["profiles_version"])
    assert document["retrieved"]


@pytest.mark.parametrize("line, name, hex_value", [
    # Values from Bambu Lab's published hex-code PDFs that the old hand-made palette got wrong.
    ("PLA Basic", "Orange", "#FF6A13"),
    ("PLA Basic", "Yellow", "#F4EE2A"),
    ("PLA Basic", "Brown", "#9D432C"),
    ("PLA Matte", "Charcoal", "#000000"),
    ("PLA Matte", "Lilac Purple", "#AE96D4"),
    ("PLA Translucent", "Purple", "#8344B0"),
    ("PLA Silk+", "Gold", "#F4A925"),
])
def test_matches_bambus_published_hex_codes(line, name, hex_value):
    match = [c for c in filament_colors() if c.line == line and c.name == name]
    assert [c.hex for c in match] == [hex_value]


def test_lines_the_old_palette_lacked_are_present():
    lines = {c.line for c in filament_colors()}
    assert {"PETG HF", "ABS", "PLA Silk+", "PLA Matte", "TPU for AMS"} <= lines


def test_translucent_silk_and_glow_are_not_plain():
    by_line = {}
    for color in filament_colors():
        by_line.setdefault(color.line, set()).add(color.plain)
    assert by_line["PLA Translucent"] == {False}
    assert by_line["PLA Silk+"] == {False}
    assert by_line["PLA Glow"] == {False}
    assert by_line["PLA Matte"] == {True}


def test_gradients_keep_every_colour():
    gradient = next(c for c in filament_colors() if c.name == "Arctic Whisper")
    assert gradient.pattern == "gradient"
    assert gradient.hexes == ("#FFFFFF", "#9CDBD9")
    assert not gradient.plain


def test_translucent_colours_in_opaque_lines_are_flagged():
    """PC Transparent sits in the (opaque) PC line; its alpha makes it translucent."""
    clear = next(c for c in filament_colors() if c.line == "PC" and c.name == "Transparent")
    assert clear.finish == "translucent"
    assert "translucent" not in PLAIN_FINISHES
