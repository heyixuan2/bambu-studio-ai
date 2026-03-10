"""
Shared constants, config loading, and utilities for Bambu Studio AI scripts.
Eliminates duplication across analyze.py, generate.py, colorize/, preview.py,
slice.py, monitor.py, and bambu.py.
"""

__version__ = "1.0.0"

import os
import json
import platform
import subprocess
import threading

# ─── Paths ──────────────────────────────────────────────────────────

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


# ─── Config Loading ─────────────────────────────────────────────────

def load_config(include_secrets=False):
    """Load config.json and optionally .secrets.json. Returns merged dict.
    Handles malformed JSON gracefully (prints warning, returns partial config).
    """
    cfg = {}
    files = [os.path.join(SKILL_DIR, "config.json")]
    if include_secrets:
        files.append(os.path.join(SKILL_DIR, ".secrets.json"))
    for path in files:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    cfg.update(json.load(f))
            except (json.JSONDecodeError, ValueError) as e:
                print(f"⚠️ Malformed {os.path.basename(path)}: {e}")
    return cfg


def get_config(env_key, config_dict, config_key, default=""):
    """Get config value: env var > config dict > default."""
    val = os.environ.get(env_key, "")
    if val:
        return val
    return config_dict.get(config_key, default)


# ─── Build Volumes (with 10% safety margin) ─────────────────────────

BUILD_VOLUMES = {
    "A1 Mini":  (162, 162, 162),
    "A1":       (230, 230, 230),
    "P1S":      (230, 230, 230),
    "P2S":      (230, 230, 230),
    "X1C":      (230, 230, 230),
    "X1E":      (230, 230, 230),
    "H2C":      (230, 230, 230),
    "H2S":      (306, 288, 306),
    "H2D":      (315, 288, 292),
}

# ─── Materials ──────────────────────────────────────────────────────

MATERIALS = {
    "PLA":  {"min_wall": 1.2, "min_temp": 190, "max_temp": 220, "bed": 60,  "infill_deco": 15, "infill_func": 30, "enclosed": False},
    "PLA+": {"min_wall": 1.2, "min_temp": 200, "max_temp": 230, "bed": 60,  "infill_deco": 15, "infill_func": 30, "enclosed": False},
    "PETG": {"min_wall": 1.2, "min_temp": 220, "max_temp": 250, "bed": 80,  "infill_deco": 20, "infill_func": 40, "enclosed": False},
    "TPU":  {"min_wall": 1.6, "min_temp": 210, "max_temp": 240, "bed": 50,  "infill_deco": 10, "infill_func": 30, "enclosed": False},
    "ABS":  {"min_wall": 1.2, "min_temp": 230, "max_temp": 260, "bed": 100, "infill_deco": 15, "infill_func": 30, "enclosed": True},
    "ASA":  {"min_wall": 1.2, "min_temp": 230, "max_temp": 260, "bed": 100, "infill_deco": 15, "infill_func": 30, "enclosed": True},
    "PA":   {"min_wall": 1.5, "min_temp": 250, "max_temp": 280, "bed": 80,  "infill_deco": 20, "infill_func": 40, "enclosed": True},
    "PC":   {"min_wall": 1.5, "min_temp": 260, "max_temp": 300, "bed": 100, "infill_deco": 20, "infill_func": 40, "enclosed": True},
    "PEEK": {"min_wall": 2.0, "min_temp": 330, "max_temp": 350, "bed": 120, "infill_deco": 25, "infill_func": 50, "enclosed": True},
}

ENCLOSED_PRINTERS = {"P1S", "P2S", "X1C", "X1E", "H2C", "H2S", "H2D"}
HIGH_TEMP_PRINTERS = {"H2C", "H2D"}

# ─── Named Constants ─────────────────────────────────────────────

MAX_FACES_NO_SIMPLIFY = 500_000
TOKEN_TTL_SECONDS = 7_776_000  # 90 days
MAX_POLL_ITERATIONS = 120
MERGE_DOUBLES_DIST = 0.0001
ACHROMATIC_BLOCK_DIST = 1e12
ASSIGN_CHUNK_SIZE = 500_000


# ─── Platform-Aware Tool Paths ────────────────────────────────────

_SYSTEM = platform.system()

if _SYSTEM == "Darwin":
    BLENDER_PATHS = [
        "/Applications/Blender.app/Contents/MacOS/Blender",
        os.path.expanduser("~/Applications/Blender.app/Contents/MacOS/Blender"),
        "blender",
    ]
    ORCASLICER_PATHS = [
        "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer",
        os.path.expanduser("~/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
    ]
    BAMBU_STUDIO_PROFILE_PATHS = [
        "/Applications/BambuStudio.app/Contents/Resources/profiles/BBL",
        os.path.expanduser("~/Library/Application Support/BambuStudio/system/BBL"),
    ]
elif _SYSTEM == "Linux":
    BLENDER_PATHS = [
        "blender",
        "/usr/bin/blender",
        "/snap/bin/blender",
    ]
    ORCASLICER_PATHS = [
        "OrcaSlicer",
        os.path.expanduser("~/OrcaSlicer/OrcaSlicer"),
    ]
    BAMBU_STUDIO_PROFILE_PATHS = [
        os.path.expanduser("~/.config/BambuStudio/system/BBL"),
    ]
else:  # Windows
    _pf = os.environ.get("PROGRAMFILES", "C:\\Program Files")
    BLENDER_PATHS = [
        os.path.join(_pf, "Blender Foundation", "Blender", "blender.exe"),
        "blender",
    ]
    ORCASLICER_PATHS = [
        os.path.join(_pf, "OrcaSlicer", "orca-slicer.exe"),
    ]
    BAMBU_STUDIO_PROFILE_PATHS = [
        os.path.join(os.environ.get("APPDATA", ""), "BambuStudio", "system", "BBL"),
    ]


def find_blender():
    """Find Blender executable. Returns path or None."""
    for p in BLENDER_PATHS:
        if os.path.isfile(p):
            return p
        try:
            result = subprocess.run(
                ["where" if _SYSTEM == "Windows" else "which", p],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0]
        except Exception:
            pass
    return None


def find_orcaslicer():
    """Find OrcaSlicer executable. Returns path or None."""
    for p in ORCASLICER_PATHS:
        if os.path.exists(p):
            return p
    return None


def find_bambu_studio_profiles():
    """Find Bambu Studio profile directory. Returns path or None."""
    for p in BAMBU_STUDIO_PROFILE_PATHS:
        if os.path.isdir(p):
            return p
    return None


# ─── Cross-Platform Timeout ─────────────────────────────────────────

def run_with_timeout(func, args=(), kwargs=None, timeout_sec=30, default=None):
    """Run a function with a timeout. Works on all platforms (uses threading).
    Returns (result, timed_out). On timeout, returns (default, True).
    """
    if kwargs is None:
        kwargs = {}
    result = [default]
    exception = [None]
    timed_out = [False]

    def _worker():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            exception[0] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        timed_out[0] = True
        return default, True
    if exception[0] is not None:
        raise exception[0]
    return result[0], False


def safe_split_mesh(mesh, timeout_sec=30):
    """Split mesh into connected components with cross-platform timeout.
    Returns (bodies, timed_out)."""
    def _split():
        return mesh.split(only_watertight=False)

    try:
        bodies, timed_out = run_with_timeout(_split, timeout_sec=timeout_sec, default=[mesh])
        if timed_out:
            print(f"⚠️ mesh.split() timed out after {timeout_sec}s")
            return [mesh], True
        return bodies, False
    except Exception:
        return [mesh], False
