"""
Shared constants, config loading, and utilities for Bambu Studio AI scripts.
Eliminates duplication across analyze.py, generate.py, colorize/, preview.py,
slice.py, monitor.py, and bambu.py.
"""

__version__ = "2.0.0"

import os
import json
import platform
import shutil
import subprocess
import sys
import threading

# ─── Paths ──────────────────────────────────────────────────────────
#
# The skill folder itself is treated as read-only: agents install it into
# ~/.claude/skills, ~/.codex/skills, .agents/skills, ... and `npx skills update`
# or `git pull` replaces it. User state therefore lives elsewhere:
#
#   home dir   (config, secrets)
#              $BAMBU_STUDIO_AI_HOME  or  ~/.bambu-studio-ai/
#   output dir (models, previews, snapshots, logs)
#              $BAMBU_OUTPUT_DIR  or  config "output_dir"  or  ./bambu-output/
#
# Files left in the skill folder by v1.x are still read as a fallback.

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def home_dir():
    """User-level directory for config and secrets."""
    base = os.environ.get("BAMBU_STUDIO_AI_HOME") or os.path.join("~", ".bambu-studio-ai")
    return os.path.abspath(os.path.expanduser(base))


def user_file(name, legacy=None):
    """Path of a user state file in home_dir().

    If it doesn't exist there but a v1.x copy exists inside the skill folder,
    return the legacy path so existing installs keep working.
    `legacy` is the path relative to SKILL_DIR (defaults to `name`).
    """
    path = os.path.join(home_dir(), name)
    old = os.path.join(SKILL_DIR, legacy or name)
    if not os.path.exists(path) and os.path.exists(old):
        return old
    return path


def output_dir(*sub, create=True):
    """Directory for generated files. Relative to the current working directory
    by default, so outputs land in the user's project rather than the skill folder."""
    base = (os.environ.get("BAMBU_OUTPUT_DIR")
            or load_config().get("output_dir")
            or "bambu-output")
    path = os.path.join(os.path.abspath(os.path.expanduser(base)), *sub)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def write_private_json(path, data):
    """Write JSON readable only by the current user (chmod 600)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def use_utf8_stdio():
    """Write UTF-8 to stdout/stderr on every platform.

    On Windows, a piped stdout (which is how agents run these scripts) defaults to
    the ANSI code page and raises UnicodeEncodeError on the first emoji.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


# ─── Config Loading ─────────────────────────────────────────────────

# Env var → config/secrets key. Env vars always win over files.
ENV_TO_CONFIG = {
    "BAMBU_MODEL": "model",
    "BAMBU_IP": "printer_ip",
    "BAMBU_SERIAL": "serial",
    "BAMBU_ACCESS_CODE": "access_code",
    "BAMBU_3D_PROVIDER": "3d_provider",
    "BAMBU_3D_API_KEY": "3d_api_key",
}


def load_config(include_secrets=False):
    """Load config.json and optionally .secrets.json. Returns merged dict.
    Handles malformed JSON gracefully (prints warning, returns partial config).
    """
    cfg = {}
    files = [user_file("config.json")]
    if include_secrets:
        files.append(user_file(".secrets.json"))
    for path in files:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    cfg.update(json.load(f))
            except (json.JSONDecodeError, ValueError) as e:
                # stderr, so a broken config can't corrupt a command's --json output
                print(f"⚠️ Malformed {os.path.basename(path)}: {e}", file=sys.stderr)
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
    "X2D":      (230, 230, 234),
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

ENCLOSED_PRINTERS = {"P1S", "P2S", "X1C", "X1E", "H2C", "H2S", "H2D", "X2D"}
HIGH_TEMP_PRINTERS = {"H2C", "H2D"}

# ─── Named Constants ─────────────────────────────────────────────

MAX_FACES_NO_SIMPLIFY = 500_000
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


def find_bambu_studio():
    """Return the command (list) that launches Bambu Studio, or None if not installed.
    The model path gets appended to this list."""
    if _SYSTEM == "Darwin":
        for app in ("/Applications/BambuStudio.app",
                    os.path.expanduser("~/Applications/BambuStudio.app")):
            if os.path.isdir(app):
                return ["open", "-a", app]
        return None
    if _SYSTEM == "Windows":
        pf = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        exe = os.path.join(pf, "Bambu Studio", "bambu-studio.exe")
        if os.path.isfile(exe):
            return [exe]
        found = shutil.which("bambu-studio")
        return [found] if found else None
    for name in ("bambu-studio", "BambuStudio", "bambustudio"):
        found = shutil.which(name)
        if found:
            return [found]
    if shutil.which("flatpak"):
        try:
            r = subprocess.run(["flatpak", "info", "com.bambulab.BambuStudio"],
                               capture_output=True, timeout=10)
            if r.returncode == 0:
                return ["flatpak", "run", "com.bambulab.BambuStudio"]
        except Exception:
            pass
    return None


def open_in_bambu_studio(path):
    """Open a model file in Bambu Studio without blocking. Returns (ok, message)."""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return False, f"File not found: {path}"
    cmd = find_bambu_studio()
    if not cmd:
        return False, ("Bambu Studio not found. Install it from https://bambulab.com/en/download/studio "
                       f"and open this file manually: {path}")
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if _SYSTEM != "Windows":
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd + [path], **kwargs)
    except Exception as e:
        return False, f"Could not launch Bambu Studio ({e}). Open this file manually: {path}"
    return True, f"Opened in Bambu Studio: {path}"


def desktop_notify(title, message):
    """Best-effort local desktop notification (macOS / Linux). Never raises."""
    try:
        if _SYSTEM == "Darwin":
            def esc(s):
                return s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{esc(message)}" with title "Bambu Studio AI" subtitle "{esc(title)}"'],
                capture_output=True, timeout=5)
        elif _SYSTEM == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", f"Bambu Studio AI: {title}", message],
                           capture_output=True, timeout=5)
    except Exception:
        pass


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
