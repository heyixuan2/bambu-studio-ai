#!/usr/bin/env python3
"""
Bambu Studio AI — Dependency Doctor
Run before first use to verify all dependencies and API compatibility.

Usage: python3 scripts/doctor.py
"""

import sys, os, importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (
    find_blender, find_orcaslicer, find_bambu_studio, BLENDER_PATHS, ORCASLICER_PATHS,
    SKILL_DIR, home_dir, user_file, output_dir, __version__,
)

REQUIRED = {
    "requests": {"min": "2.31", "import": "requests"},
    "trimesh": {"min": "4.10", "import": "trimesh"},
    "numpy": {"min": "1.24", "import": "numpy"},
    "Pillow": {"min": "9.0", "import": "PIL"},
    "scipy": {"min": "1.10", "import": "scipy"},
    "pygltflib": {"min": "0", "import": "pygltflib"},
    "cryptography": {"min": "42.0", "import": "cryptography"},
}

OPTIONAL = {
    "bambulabs-api": {"import": "bambulabs_api", "purpose": "LAN printer control"},
    "bambu-lab-cloud-api": {"import": "bambulab", "purpose": "Cloud printer control"},
    "scikit-learn": {"import": "sklearn", "purpose": "Better colorize k-means clustering"},
    "paho-mqtt": {"import": "paho.mqtt", "purpose": "LAN MQTT printer control"},
    "manifold3d": {"import": "manifold3d", "purpose": "Parametric modeling (functional parts)"},
    "rembg": {"import": "rembg", "purpose": "Image-to-3D background removal"},
    "pymeshlab": {"import": "pymeshlab", "purpose": "Advanced mesh repair"},
}

def check_version(pkg_name, min_ver, import_name):
    try:
        mod = importlib.import_module(import_name)
        ver = getattr(mod, "__version__", getattr(mod, "VERSION", "unknown"))
        return True, ver
    except ImportError:
        return False, None

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

def check_api_symbols():
    """Check bambulabs-api has required methods."""
    issues = []
    try:
        from bambulabs_api import Printer
        p_methods = dir(Printer)
        for method in ["connect", "disconnect"]:
            if method not in p_methods:
                issues.append(f"Printer missing .{method}()")
        # Check speed method (either name)
        if "set_print_speed" not in p_methods and "set_speed_level" not in p_methods:
            issues.append("Printer missing speed control method")
        # Check AMS method (either name)
        if "get_ams" not in p_methods and "ams_hub" not in p_methods:
            issues.append("Printer missing AMS accessor")
    except ImportError:
        issues.append("bambulabs-api not installed (needed for LAN mode)")
    return issues

def check_cloud_api_symbols():
    """Check bambu-lab-cloud-api has required classes."""
    issues = []
    try:
        from bambulab import BambuClient
        from bambulab import BambuAuthenticator
        c_methods = dir(BambuClient)
        for method in ["get_devices"]:
            if method not in c_methods:
                issues.append(f"BambuClient missing .{method}()")
        a_methods = dir(BambuAuthenticator)
        if "login" not in a_methods:
            issues.append("BambuAuthenticator missing .login()")
    except ImportError:
        issues.append("bambu-lab-cloud-api not installed (needed for Cloud mode)")
    except Exception as e:
        issues.append(f"bambu-lab-cloud-api import error: {e}")
    return issues

def check_search_backend():
    """Check search dependencies."""
    try:
        from ddgs import DDGS
        return True, "ddgs"
    except ImportError:
        try:
            from duckduckgo_search import DDGS
            return True, "duckduckgo_search"
        except ImportError:
            return False, None

def main():
    print(f"🩺 Bambu Studio AI — Dependency Doctor (v{__version__})\n")
    print(f"Python: {sys.executable} ({sys.version.split()[0]})\n")
    all_ok = True
    
    print("Required packages:")
    for name, info in REQUIRED.items():
        ok, ver = check_version(name, info["min"], info["import"])
        status = f"✅ {ver}" if ok else "❌ NOT FOUND"
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

    print("\nSystem tools:")
    import shutil
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        print(f"  ✅ ffmpeg found: {ffmpeg_path}")
    else:
        print("  ⚠️ ffmpeg not found (needed for camera snapshots in LAN mode)")
        print("     Install: brew install ffmpeg (macOS) / apt install ffmpeg (Linux) / winget install ffmpeg (Windows)")

    print("\nAPI compatibility (LAN):")
    issues = check_api_symbols()
    if issues:
        for issue in issues:
            print(f"  ⚠️ {issue}")
    else:
        print("  ✅ bambulabs-api symbols verified")

    print("\nAPI compatibility (Cloud):")
    cloud_issues = check_cloud_api_symbols()
    if cloud_issues:
        for issue in cloud_issues:
            print(f"  ⚠️ {issue}")
    else:
        print("  ✅ bambu-lab-cloud-api symbols verified")


    print("\nSearch backend:")
    search_ok, search_pkg = check_search_backend()
    if search_ok:
        print(f"  ✅ {search_pkg}")
    else:
        print("  ⚠️ Not found — install: pip install ddgs")
    
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
    sys.exit(main())
