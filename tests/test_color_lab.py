"""Colour maths (bambu_studio_ai.color.lab): sRGB, CIELAB and CIEDE2000 against published values."""

import numpy as np
import pytest

from bambu_studio_ai.color.lab import (
    delta_e_2000,
    lab_to_srgb,
    linear_to_srgb,
    parse_hex,
    srgb_to_lab,
    srgb_to_linear,
    to_hex,
)

# Sharma, Wu & Dalal (2005), "The CIEDE2000 colour-difference formula", Table 1.
SHARMA_PAIRS = [
    ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
    ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
    ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
    ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
    ((50.0, 2.5, 0.0), (61.0, -5.0, 29.0), 22.8977),
    ((50.0, 2.5, 0.0), (56.0, -27.0, -3.0), 31.9030),
    ((50.0, 2.5, 0.0), (58.0, 24.0, 15.0), 19.4535),
    ((50.0, 2.5, 0.0), (50.0, 3.1736, 0.5854), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]


@pytest.mark.parametrize(("lab1", "lab2", "expected"), SHARMA_PAIRS)
def test_ciede2000_matches_sharma_reference_data(lab1, lab2, expected):
    assert delta_e_2000(np.array(lab1), np.array(lab2)) == pytest.approx(expected, abs=1e-4)
    # The formula is symmetric in its arguments.
    assert delta_e_2000(np.array(lab2), np.array(lab1)) == pytest.approx(expected, abs=1e-4)


def test_ciede2000_broadcasts_over_arrays():
    first = np.array([pair[0] for pair in SHARMA_PAIRS])
    second = np.array([pair[1] for pair in SHARMA_PAIRS])
    expected = [pair[2] for pair in SHARMA_PAIRS]
    np.testing.assert_allclose(delta_e_2000(first, second), expected, atol=1e-4)


@pytest.mark.parametrize(("hex_colour", "lab"), [
    ("#FF0000", (53.24, 80.09, 67.20)),
    ("#00FF00", (87.73, -86.18, 83.18)),
    ("#0000FF", (32.30, 79.19, -107.86)),
    ("#FFFFFF", (100.0, 0.0, 0.0)),
    ("#000000", (0.0, 0.0, 0.0)),
    ("#808080", (53.59, 0.0, 0.0)),
])
def test_srgb_to_lab_reference_values(hex_colour, lab):
    np.testing.assert_allclose(srgb_to_lab(parse_hex(hex_colour)), lab, atol=0.05)


def test_lab_round_trip_is_exact_enough_for_hex():
    rng = np.random.default_rng(1)
    colours = rng.integers(0, 256, (500, 3)) / 255
    back = lab_to_srgb(srgb_to_lab(colours))
    np.testing.assert_allclose(back, colours, atol=1e-6)


def test_srgb_transfer_curve_round_trip_and_mid_grey():
    grey = np.array([0.5])
    assert srgb_to_linear(grey)[0] == pytest.approx(0.21404, abs=1e-5)
    np.testing.assert_allclose(linear_to_srgb(srgb_to_linear(np.linspace(0, 1, 11))), np.linspace(0, 1, 11))


def test_hex_parsing_and_formatting():
    assert to_hex(parse_hex("#c81e1e")) == "#C81E1E"
    assert to_hex(parse_hex("7b7b7b")) == "#7B7B7B"
    for bad in ("#12345", "red", "#GG0000", ""):
        with pytest.raises(ValueError, match="hex colour"):
            parse_hex(bad)
