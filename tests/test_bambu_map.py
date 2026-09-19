"""colorize --bambu-map: which Bambu filaments may be suggested for a colour."""

import os
import subprocess
import sys

import numpy as np

from colorize.bambu_map import load_bambu_palette, map_colors_to_filaments, write_bambu_map
from colorize.color_science import srgb_to_lab

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")


def _selected(hex_value):
    rgb = np.array([int(hex_value[i:i + 2], 16) / 255.0 for i in (1, 3, 5)])
    return [{"lab": srgb_to_lab(rgb[np.newaxis, :])[0], "rgb": rgb, "family": "test", "percentage": 100.0}]


def test_default_palette_is_plain_pla_only():
    palette = load_bambu_palette()
    assert palette
    assert {p["finish"] for p in palette} <= {"opaque", "matte"}
    assert {"PLA Basic", "PLA Matte"} <= {p["line"] for p in palette}
    assert not any(p["line"].startswith("Support") for p in palette)


def test_opaque_colour_is_not_matched_to_a_translucent_filament():
    """Regression: an opaque #1E3CC7 region was matched to 'PLA Translucent Blue'."""
    best = map_colors_to_filaments(_selected("#1E3CC7"), load_bambu_palette())[0]["best"]
    assert best["line"] in {"PLA Basic", "PLA Matte", "PLA Lite", "PLA Pure", "PLA Tough", "PLA Tough+"}


def test_other_finishes_compete_when_asked_for():
    palette = load_bambu_palette({"opaque", "matte", "translucent"})
    best = map_colors_to_filaments(_selected("#1E3CC7"), palette)[0]["best"]
    assert best["line"] == "PLA Translucent"


def test_exact_bambu_colour_matches_itself():
    best = map_colors_to_filaments(_selected("#FF6A13"), load_bambu_palette())[0]["best"]
    assert (best["line"], best["name"], best["delta_e"]) == ("PLA Basic", "Orange", 0.0)


def test_color_map_file_names_the_suggestion(tmp_path):
    mappings = map_colors_to_filaments(_selected("#FF6A13"), load_bambu_palette())
    path = write_bambu_map(mappings, str(tmp_path / "model_multicolor.obj"))
    assert path == str(tmp_path / "model_multicolor_color_map.txt")
    assert "PLA Basic / Orange #FF6A13" in (tmp_path / "model_multicolor_color_map.txt").read_text()


def test_unknown_finish_is_a_usage_error():
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "colorize"), "model.glb", "--bambu-finish", "shiny"],
                       capture_output=True, encoding="utf-8", env=os.environ.copy())
    assert r.returncode == 2
    assert "unknown finish shiny" in r.stderr
