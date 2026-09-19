#!/usr/bin/env python3
"""
Bambu Studio AI — Dependency Doctor
Run before first use to verify all dependencies and API compatibility.

Usage: python3 scripts/doctor.py
"""

import importlib
import importlib.metadata
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import use_utf8_stdio
from common import (
    find_blender, find_orcaslicer, find_bambu_studio, BLENDER_PATHS, ORCASLICER_PATHS,
    SKILL_DIR, home_dir, user_file, output_dir, __version__,
)

REQUIRED = {
    "requests": {"min": "2.31", "import": "requests"},  # also model search (MakerWorld + Printables APIs)
    "trimesh": {"min": "4.10", "import": "trimesh"},
    "numpy": {"min": "1.24", "import": "numpy"},
    "Pillow": {"min": "9.0", "import": "PIL"},
    "scipy": {"min": "1.10", "import": "scipy"},
    "pygltflib": {"min": "0", "import": "pygltflib"},
    "networkx": {"min": "3.2", "import": "networkx"},
}

OPTIONAL = {
    "scikit-learn": {"import": "sklearn", "purpose": "Better colorize k-means clustering"},
    "paho-mqtt": {"import": "paho.mqtt", "purpose": "Printer status (bambu.py status, monitor.py)"},
    "manifold3d": {"import": "manifold3d", "purpose": "Parametric modeling (functional parts)"},
    "rembg": {"import": "rembg", "purpose": "Image-to-3D background removal"},
    "pymeshlab": {"import": "pymeshlab", "purpose": "Advanced mesh repair"},
}

def _version_tuple(text):
    parts = []
    for piece in str(text).split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def check_version(pkg_name, min_ver, import_name):
    """Return (importable_and_new_enough, installed_version)."""
    try:
        importlib.import_module(import_name)
    except ImportError:
        return False, None
    try:
        ver = importlib.metadata.version(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        return True, "unknown"
    return _version_tuple(ver) >= _version_tuple(min_ver or "0"), ver

def check_blender():
    import subprocess
    path = find_blender()
    if path:
        try:
            r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                ver = r.stdout.split("\n")[0]
                return True, ver, path
        except Exception:
            pass
    return False, None, None

def main():
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__.strip())
        return 0
    print(f"🩺 Bambu Studio AI — Dependency Doctor (v{__version__})\n")
    print(f"Python: {sys.executable} ({sys.version.split()[0]})\n")
    all_ok = True
    
    print("Required packages:")
    for name, info in REQUIRED.items():
        ok, ver = check_version(name, info["min"], info["import"])
        if ok:
            status = f"✅ {ver}"
        elif ver:
            status = f"❌ {ver} is too old (need {info['min']}+)"
        else:
            status = "❌ NOT FOUND"
        if not ok: all_ok = False
        print(f"  {name:20s} {status}")
    
    print("\nOptional packages:")
    for name, info in OPTIONAL.items():
        ok, ver = check_version(name, "0", info["import"])
        status = f"✅ {ver}" if ok else f"⚠️ not installed ({info['purpose']})"
        print(f"  {name:20s} {status}")
    

    print("\nBambu Studio (model review + slicing):")
    bs_cmd = find_bambu_studio()
    if bs_cmd:
        print(f"  ✅ {' '.join(bs_cmd)}")
    else:
        print("  ⚠️ Not found — install from https://bambulab.com/en/download/studio")

    print("\nBlender:")
    ok, ver, path = check_blender()
    if ok:
        print(f"  ✅ {ver}")
        print(f"     Path: {path}")
    else:
        print("  ⚠️ Not found (needed for preview.py and colorize) — https://www.blender.org/download/")

    print("\nOrcaSlicer (for slicing):")
    orca_path = find_orcaslicer()
    if orca_path:
        print(f"  ✅ OrcaSlicer found")
        print(f"     Path: {orca_path}")
    else:
        print("  ⚠️ OrcaSlicer not installed (needed for slice.py)")
        print("     Install from: https://github.com/SoftFever/OrcaSlicer")

    print(f"\nConfig ({home_dir()}):")
    legacy_in_use = False
    for fname in ["config.json", ".secrets.json"]:
        path = user_file(fname)
        if not os.path.exists(path):
            print(f"  ℹ️ {fname} — not created yet (run: python3 scripts/configure.py show)")
        elif path.startswith(SKILL_DIR + os.sep):
            legacy_in_use = True
            print(f"  ⚠️ {fname} — found in the skill folder (v1.x location): {path}")
        else:
            print(f"  ✅ {fname}")
    if legacy_in_use:
        print("     Skill updates may overwrite it. Move it: python3 scripts/configure.py migrate")
    print(f"\nOutput dir: {output_dir(create=False)}")
    
    print()
    if all_ok:
        print("✅ All checks passed — ready to use!")
    else:
        print("❌ Some required dependencies missing. Run:")
        print(f"   {sys.executable} -m pip install -r {os.path.join(SKILL_DIR, 'requirements.txt')}")
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    use_utf8_stdio()
    sys.exit(main())
