"""Color science utilities: sRGB ↔ CIELAB conversion and HSV pixel classification."""

import numpy as np

FAMILY_NAMES = [
    "black", "dark_gray", "light_gray", "white",
    "red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink",
]

ACHROMATIC_FAMILIES = {"black", "dark_gray", "light_gray", "white"}

# Legacy family groups (empty — all 12 families independent since v0.22.20)
FAMILY_GROUPS = {}


def srgb_to_lab(rgb):
    """Vectorized sRGB [0,1] (N,3) → CIELAB (N,3)."""
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    r, g, b = linear[:, 0], linear[:, 1], linear[:, 2]
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    x /= 0.95047; z /= 1.08883
    def f(t):
        return np.where(t > 0.008856, t ** (1/3), 7.787 * t + 16/116)
    return np.stack([116*f(y)-16, 500*(f(x)-f(y)), 200*(f(y)-f(z))], axis=1)


def classify_pixels(pixels):
    """Classify each pixel into a color family by HSV. Returns int32 array of family IDs."""
    N = len(pixels)
    r, g, b = pixels[:, 0], pixels[:, 1], pixels[:, 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc

    s = np.zeros(N, dtype=np.float64)
    np.divide(delta, maxc, out=s, where=maxc > 0)
    v = maxc

    h = np.zeros(N)
    mr = (maxc == r) & (delta > 0)
    mg = (maxc == g) & (delta > 0)
    mb = (maxc == b) & (delta > 0)
    h[mr] = 60 * (((g[mr] - b[mr]) / delta[mr]) % 6)
    h[mg] = 60 * ((b[mg] - r[mg]) / delta[mg] + 2)
    h[mb] = 60 * ((r[mb] - g[mb]) / delta[mb] + 4)

    pf = np.full(N, 1, dtype=np.int32)  # default: dark_gray
    achro = (s < 0.15) | (v < 0.1)
    pf[achro & (v < 0.2)] = 0                          # black
    pf[achro & (v >= 0.2) & (v < 0.5)] = 1             # dark_gray
    pf[achro & (v >= 0.5) & (v < 0.8)] = 2             # light_gray
    pf[achro & (v >= 0.8)] = 3                          # white
    chro = ~achro
    pf[chro & ((h < 15) | (h >= 345))] = 4             # red
    pf[chro & (h >= 15) & (h < 40)] = 5                # orange
    pf[chro & (h >= 40) & (h < 70)] = 6                # yellow
    pf[chro & (h >= 70) & (h < 160)] = 7               # green
    pf[chro & (h >= 160) & (h < 200)] = 8              # cyan
    pf[chro & (h >= 200) & (h < 260)] = 9              # blue
    pf[chro & (h >= 260) & (h < 310)] = 10             # purple
    pf[chro & (h >= 310) & (h < 345)] = 11             # pink

    return pf


def name_from_rgb(median_rgb):
    """Name a color by closest HSV family from 0-1 float RGB."""
    r, g, b = int(median_rgb[0] * 255), int(median_rgb[1] * 255), int(median_rgb[2] * 255)
    maxc = max(r, g, b)
    minc = min(r, g, b)
    v = maxc / 255.0
    s = (maxc - minc) / maxc if maxc > 0 else 0
    if s < 0.15 or v < 0.1:
        if v < 0.2: return "black"
        elif v < 0.5: return "dark_gray"
        elif v < 0.8: return "light_gray"
        else: return "white"
    diff = maxc - minc
    if diff == 0: h = 0
    elif maxc == r: h = 60 * ((g - b) / diff % 6)
    elif maxc == g: h = 60 * ((b - r) / diff + 2)
    else: h = 60 * ((r - g) / diff + 4)
    if h < 0: h += 360
    if h < 15 or h >= 345: return "red"
    elif h < 40: return "orange"
    elif h < 70: return "yellow"
    elif h < 160: return "green"
    elif h < 200: return "cyan"
    elif h < 260: return "blue"
    elif h < 310: return "purple"
    else: return "pink"
