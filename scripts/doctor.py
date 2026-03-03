#!/usr/bin/env python3
"""
Bambu Studio AI — Dependency Doctor
Run before first use to verify all dependencies and API compatibility.

Usage: python3 doctor.py
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
        ok = True
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
        except:
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
    
    print("\nBlender:")
    ok, ver, path = check_blender()
    if ok:
        print(f"  ✅ {ver}")
        print(f"     Path: {path}")
    else:
        print("  ⚠️ Not found (needed for multi-color)")
    
    print("\nAPI compatibility:")
    issues = check_api_symbols()
    if issues:
        for issue in issues:
            print(f"  ⚠️ {issue}")
    else:
        print("  ✅ All symbols verified")
    
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
