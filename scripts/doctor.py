#!/usr/bin/env python3
"""
Bambu Studio AI — Dependency Doctor
Run before first use to verify all dependencies and API compatibility.

Usage: python3 scripts/doctor.py
"""

import sys, os, importlib

REQUIRED = {
    "requests": {"min": "2.31", "import": "requests"},
    "trimesh": {"min": "4.10", "import": "trimesh"},
    "numpy": {"min": "1.24", "import": "numpy"},
    "Pillow": {"min": "9.0", "import": "PIL"},
}

OPTIONAL = {
    "bambulabs-api": {"import": "bambulabs_api", "purpose": "LAN printer control"},
    "bambu-lab-cloud-api": {"import": "bambu_lab_cloud_api", "purpose": "Cloud printer control"},
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
    for path in ["/Applications/Blender.app/Contents/MacOS/Blender", "blender"]:
        try:
            r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                ver = r.stdout.split("\n")[0]
                return True, ver, path
        except Exception:
            continue
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
        from bambu_lab_cloud_api import BambuClient
        from bambu_lab_cloud_api import BambuAuthenticator
        c_methods = dir(BambuClient)
        for method in ["get_device_list"]:
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
    print("🩺 Bambu Studio AI — Dependency Doctor\n")
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
    

    # Check pygltflib (fast texture extraction)
    try:
        import pygltflib
        print("  pygltflib: ✅")
    except ImportError:
        print("  pygltflib: ❌ (pip3 install pygltflib — fast texture extraction)")
    print("\nBlender:")
    ok, ver, path = check_blender()
    if ok:
        print(f"  ✅ {ver}")
        print(f"     Path: {path}")
    else:
        print("  ⚠️ Not found (needed for multi-color)")

    print("\nOrcaSlicer (for slicing):")
    orca_paths = [
        "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer",
        os.path.expanduser("~/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
    ]
    orca_found = False
    for op in orca_paths:
        if os.path.exists(op):
            print(f"  ✅ OrcaSlicer found")
            print(f"     Path: {op}")
            orca_found = True
            break
    if not orca_found:
        print("  ⚠️ OrcaSlicer not installed (needed for slice.py)")
        print("     Install from: https://github.com/SoftFever/OrcaSlicer")

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

    print("\nPreview rendering:")
    blender_ok2, blender_ver2, _ = check_blender()
    if blender_ok2:
        print(f"  ✅ Blender (required for preview + colorize)")
    else:
        print("  ❌ Blender not found (brew install --cask blender) — needed for preview + colorize")


    print("\nSearch backend:")
    search_ok, search_pkg = check_search_backend()
    if search_ok:
        print(f"  ✅ {search_pkg}")
    else:
        print("  ⚠️ Not found — install: pip install ddgs")
    
    print("\nConfig files:")
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fname in ["config.json", ".secrets.json"]:
        path = os.path.join(skill_dir, fname)
        if os.path.exists(path):
            print(f"  ✅ {fname}")
        else:
            print(f"  ℹ️ {fname} — not yet created (will be set up during first use)")
    
    print()
    if all_ok:
        print("✅ All checks passed — ready to use!")
    else:
        print("❌ Some required dependencies missing. Run:")
        print("   pip install -r requirements.txt")
    
    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
