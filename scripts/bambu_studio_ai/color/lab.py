"""Colour maths: sRGB, linear light, CIELAB and the CIEDE2000 colour difference.

sRGB follows IEC 61966-2-1 with the D65 white point (the space glTF textures and
Bambu Studio's ``#RRGGBB`` filament colours are in). CIEDE2000 follows Sharma, Wu and
Dalal (2005), "The CIEDE2000 colour-difference formula: implementation notes".
"""

from __future__ import annotations

import re

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

# sRGB (linear) -> CIE XYZ, D65, from IEC 61966-2-1.
_RGB_TO_XYZ: FloatArray = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
_XYZ_TO_RGB: FloatArray = np.asarray(np.linalg.inv(_RGB_TO_XYZ), dtype=np.float64)
_WHITE_D65: FloatArray = np.array([0.95047, 1.0, 1.08883], dtype=np.float64)
_EPSILON = 216 / 24389  # CIE 1976 constants, exact rational forms
_KAPPA = 24389 / 27
_HEX_COLOUR = re.compile(r"#?([0-9a-fA-F]{6})")
_POW7_25 = 25.0**7
_SRGB_KNEE = 0.04045  # below these the sRGB curve is a straight line
_LINEAR_KNEE = 0.0031308
_HALF_TURN = 180.0
_FULL_TURN = 360.0


def srgb_to_linear(srgb: FloatArray) -> FloatArray:
    """Decode sRGB values in [0, 1] to linear light."""
    srgb = np.asarray(srgb, dtype=np.float64)
    return np.where(srgb <= _SRGB_KNEE, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def unit_clip(values: FloatArray) -> FloatArray:
    """Clamp to [0, 1]."""
    return np.minimum(np.maximum(np.asarray(values, dtype=np.float64), 0.0), 1.0)


def linear_to_srgb(linear: FloatArray) -> FloatArray:
    """Encode linear-light values in [0, 1] as sRGB."""
    linear = unit_clip(linear)
    return np.where(linear <= _LINEAR_KNEE, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)


def srgb_to_lab(srgb: FloatArray) -> FloatArray:
    """Convert sRGB colours in [0, 1], shape ``(..., 3)``, to CIELAB (D65)."""
    xyz: FloatArray = np.matmul(srgb_to_linear(srgb), np.transpose(_RGB_TO_XYZ)) / _WHITE_D65
    f: FloatArray = np.where(xyz > _EPSILON, np.cbrt(xyz), (_KAPPA * xyz + 16) / 116)
    lightness = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([lightness, a, b], axis=-1)


def lab_to_srgb(lab: FloatArray) -> FloatArray:
    """Convert CIELAB (D65) to sRGB in [0, 1], clipping colours outside the gamut."""
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    f = np.stack([fx, fy, fz], axis=-1)
    xyz = np.where(f**3 > _EPSILON, f**3, (116 * f - 16) / _KAPPA) * _WHITE_D65
    return linear_to_srgb(np.matmul(xyz, np.transpose(_XYZ_TO_RGB)))


def delta_e_2000(lab1: FloatArray, lab2: FloatArray) -> FloatArray:
    """CIEDE2000 colour difference between Lab colours (broadcasting over leading axes)."""
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    l1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    l2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]
    c_mean = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    g = 0.5 * (1 - np.sqrt(c_mean**7 / (c_mean**7 + _POW7_25)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % _FULL_TURN
    h2p = np.degrees(np.arctan2(b2, a2p)) % _FULL_TURN

    delta_l = l2 - l1
    delta_c = c2p - c1p
    chroma_product = c1p * c2p
    dh = h2p - h1p
    dh = np.where(dh > _HALF_TURN, dh - _FULL_TURN, np.where(dh < -_HALF_TURN, dh + _FULL_TURN, dh))
    dh = np.where(chroma_product == 0, 0.0, dh)
    delta_h = 2 * np.sqrt(chroma_product) * np.sin(np.radians(dh / 2))

    l_mean = (l1 + l2) / 2
    cp_mean = (c1p + c2p) / 2
    h_sum = h1p + h2p
    hp_mean = np.where(
        chroma_product == 0,
        h_sum,
        np.where(
            np.abs(h1p - h2p) <= _HALF_TURN,
            h_sum / 2,
            np.where(h_sum < _FULL_TURN, (h_sum + _FULL_TURN) / 2, (h_sum - _FULL_TURN) / 2),
        ),
    )
    t = (
        1
        - 0.17 * np.cos(np.radians(hp_mean - 30))
        + 0.24 * np.cos(np.radians(2 * hp_mean))
        + 0.32 * np.cos(np.radians(3 * hp_mean + 6))
        - 0.20 * np.cos(np.radians(4 * hp_mean - 63))
    )
    delta_theta = 30 * np.exp(-(((hp_mean - 275) / 25) ** 2))
    r_c = 2 * np.sqrt(cp_mean**7 / (cp_mean**7 + _POW7_25))
    s_l = 1 + 0.015 * (l_mean - 50) ** 2 / np.sqrt(20 + (l_mean - 50) ** 2)
    s_c = 1 + 0.045 * cp_mean
    s_h = 1 + 0.015 * cp_mean * t
    r_t = -np.sin(np.radians(2 * delta_theta)) * r_c
    return np.sqrt(
        (delta_l / s_l) ** 2
        + (delta_c / s_c) ** 2
        + (delta_h / s_h) ** 2
        + r_t * (delta_c / s_c) * (delta_h / s_h)
    )


def parse_hex(text: str) -> FloatArray:
    """``"#FF8800"`` or ``"ff8800"`` -> sRGB ``[1.0, 0.533, 0.0]``.

    Raises:
        ValueError: if ``text`` is not a six-digit hex colour.
    """
    match = _HEX_COLOUR.fullmatch(text.strip())
    if match is None:
        raise ValueError(f"not a hex colour: {text!r} (expected #RRGGBB)")
    digits = match.group(1)
    return np.array([int(digits[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float64) / 255


def to_hex(srgb: FloatArray) -> str:
    """Format sRGB in [0, 1] as ``"#RRGGBB"`` (upper case, as Bambu Studio writes it)."""
    red, green, blue = (round(float(v) * 255) for v in unit_clip(srgb))
    return f"#{red:02X}{green:02X}{blue:02X}"
