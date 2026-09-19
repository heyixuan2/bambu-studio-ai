#!/usr/bin/env python3
"""
Bambu Studio AI — configuration helper.

Writes config.json / .secrets.json in the user config dir (~/.bambu-studio-ai/,
override with BAMBU_STUDIO_AI_HOME), so settings survive skill reinstalls and updates.

Usage:
  python3 scripts/configure.py show                       # Current settings (secrets masked)
  python3 scripts/configure.py set model "A1 Mini"        # Non-secret setting
  python3 scripts/configure.py set mode local printer_ip 192.168.1.50 serial 01P00A000000000
  printf '%s' "$CODE" | python3 scripts/configure.py secret access_code   # Secret from stdin
  python3 scripts/configure.py secret 3d_api_key --value msy_xxx          # Secret from argument
  python3 scripts/configure.py unset output_dir
  python3 scripts/configure.py migrate                    # Move v1.x files out of the skill folder
"""

import argparse
import json
import os
import shutil
import sys

from common import use_utf8_stdio
from common import (
    SKILL_DIR, BUILD_VOLUMES, ENV_TO_CONFIG, home_dir, user_file, write_private_json,
)

PRINTER_MODELS = list(BUILD_VOLUMES)
PROVIDERS = ["meshy", "tripo", "printpal", "3daistudio", "rodin"]

# key -> validator/coercer. Unknown keys are accepted with a warning.
CONFIG_KEYS = {
    "model": lambda v: _choice(v, PRINTER_MODELS),
    "mode": lambda v: _choice(v.lower(), ["local", "cloud"]),
    "print_mode": lambda v: _choice(v.lower(), ["manual", "auto"]),
    "printer_ip": str,
    "serial": str,
    "email": str,
    "device_id": str,
    "printer_name": str,
    "3d_provider": lambda v: _choice(v.lower(), PROVIDERS),
    "rodin_tier": str,
    "output_dir": str,
    "preferred_format": lambda v: _choice(v.lower(), ["3mf", "stl", "obj"]),
    "monitor_interval": int,
    "monitor_level": str,
    "auto_pause": lambda v: _bool(v),
    "monitor_enabled": lambda v: _bool(v),
}
SECRET_KEYS = ["access_code", "password", "3d_api_key"] + [f"{p}_api_key" for p in PROVIDERS]

LEGACY_FILES = {
    "config.json": "config.json",
    ".secrets.json": ".secrets.json",
    ".token_cache.json": ".token_cache.json",
    "bambu_connect_cert.pem": os.path.join("references", "bambu_connect_cert.pem"),
    "bambu_connect_key.pem": os.path.join("references", "bambu_connect_key.pem"),
}


def _choice(value, options):
    for opt in options:
        if value.lower() == opt.lower():
            return opt
    raise ValueError(f"must be one of: {', '.join(options)}")


def _bool(value):
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ValueError("must be true or false")


def _read(name):
    path = user_file(name)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"⚠️ Ignoring malformed {path}: {e}")
    return {}


def _write(name, data):
    # Always write to the home dir. Reading via user_file() first means a v1.x
    # file in the skill folder gets carried over instead of silently shadowed.
    path = os.path.join(home_dir(), name)
    write_private_json(path, data)
    return path


def _mask(value):
    s = str(value)
    return "(empty)" if not s else ("*" * max(len(s) - 4, 4) + s[-4:] if len(s) > 6 else "****")


def cmd_show():
    print(f"Config dir: {home_dir()}")
    cfg_path, sec_path = user_file("config.json"), user_file(".secrets.json")
    for label, path in (("config.json", cfg_path), (".secrets.json", sec_path)):
        state = "✅" if os.path.exists(path) else "—  (not created yet)"
        legacy = "  ⚠️ legacy location inside skill folder — run: configure.py migrate" \
            if os.path.exists(path) and path.startswith(SKILL_DIR + os.sep) else ""
        print(f"  {label:14s} {state} {path if os.path.exists(path) else ''}{legacy}")

    cfg = _read("config.json")
    print("\nSettings:")
    if not cfg:
        print("  (none)")
    for k, v in cfg.items():
        print(f"  {k:18s} {v}")

    sec = _read(".secrets.json")
    print("\nSecrets:")
    if not sec:
        print("  (none)")
    for k, v in sec.items():
        print(f"  {k:18s} {_mask(v)}")

    overrides = [k for k in ENV_TO_CONFIG if os.environ.get(k)]
    if overrides:
        print(f"\nEnvironment overrides active: {', '.join(overrides)}")

    missing = []
    mode = os.environ.get("BAMBU_MODE") or cfg.get("mode", "local")
    if not (os.environ.get("BAMBU_MODEL") or cfg.get("model")):
        missing.append("model")
    if mode == "local":
        for k, env in (("printer_ip", "BAMBU_IP"), ("serial", "BAMBU_SERIAL")):
            if not (os.environ.get(env) or cfg.get(k)):
                missing.append(k)
        if not (os.environ.get("BAMBU_ACCESS_CODE") or sec.get("access_code")):
            missing.append("access_code (secret)")
    else:
        if not (os.environ.get("BAMBU_EMAIL") or cfg.get("email")):
            missing.append("email")
        if not (os.environ.get("BAMBU_PASSWORD") or sec.get("password")):
            missing.append("password (secret)")
    if missing:
        print(f"\nPrinter connection not ready ({mode} mode) — missing: {', '.join(missing)}")
    else:
        print(f"\nPrinter connection configured ({mode} mode).")
    return 0


def cmd_set(pairs):
    if len(pairs) % 2:
        print("❌ Usage: configure.py set KEY VALUE [KEY VALUE ...]")
        return 2
    cfg = _read("config.json")
    for key, raw in zip(pairs[::2], pairs[1::2]):
        if key in SECRET_KEYS:
            print(f"❌ '{key}' is a secret — use: configure.py secret {key}")
            return 2
        conv = CONFIG_KEYS.get(key)
        if conv is None:
            print(f"⚠️ Unknown key '{key}' — saving anyway")
            conv = str
        try:
            cfg[key] = conv(raw)
        except ValueError as e:
            print(f"❌ {key}: {e}")
            return 2
    path = _write("config.json", cfg)
    print(f"✅ Saved {', '.join(pairs[::2])} → {path}")
    return 0


def cmd_unset(keys):
    cfg, sec = _read("config.json"), _read(".secrets.json")
    for key in keys:
        cfg.pop(key, None)
        sec.pop(key, None)
    _write("config.json", cfg)
    _write(".secrets.json", sec)
    print(f"✅ Removed: {', '.join(keys)}")
    return 0


def cmd_secret(name, value=None):
    if name not in SECRET_KEYS:
        print(f"❌ Unknown secret '{name}'. Known: {', '.join(SECRET_KEYS)}")
        return 2
    if value is None:
        if sys.stdin.isatty():
            import getpass
            value = getpass.getpass(f"{name}: ")
        else:
            value = sys.stdin.read()
    value = value.strip()
    if not value:
        print("❌ Empty value — nothing saved")
        return 2
    sec = _read(".secrets.json")
    sec[name] = value
    path = _write(".secrets.json", sec)
    print(f"✅ Saved secret '{name}' → {path} (chmod 600)")
    return 0


def cmd_migrate():
    moved = 0
    dest_dir = home_dir()
    os.makedirs(dest_dir, exist_ok=True)
    for new_name, legacy_rel in LEGACY_FILES.items():
        src = os.path.join(SKILL_DIR, legacy_rel)
        dst = os.path.join(dest_dir, new_name)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            print(f"⏭️  {new_name}: already exists in {dest_dir}, left {src} untouched")
            continue
        shutil.move(src, dst)
        try:
            os.chmod(dst, 0o600)
        except OSError:
            pass
        print(f"✅ {legacy_rel} → {dst}")
        moved += 1
    print(f"\n{moved} file(s) moved." if moved else "Nothing to migrate.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Bambu Studio AI configuration")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("show", help="Show current settings (secrets masked)")
    p = sub.add_parser("set", help="Set non-secret settings: KEY VALUE [KEY VALUE ...]")
    p.add_argument("pairs", nargs="+")
    p = sub.add_parser("unset", help="Remove settings or secrets")
    p.add_argument("keys", nargs="+")
    p = sub.add_parser("secret", help="Store a secret (value from --value or stdin)")
    p.add_argument("name", choices=SECRET_KEYS)
    p.add_argument("--value", default=None)
    sub.add_parser("migrate", help="Move v1.x config/secrets/certs out of the skill folder")
    sub.add_parser("path", help="Print the config directory")
    args = parser.parse_args()

    if args.command == "show":
        return cmd_show()
    if args.command == "set":
        return cmd_set(args.pairs)
    if args.command == "unset":
        return cmd_unset(args.keys)
    if args.command == "secret":
        return cmd_secret(args.name, args.value)
    if args.command == "migrate":
        return cmd_migrate()
    if args.command == "path":
        print(home_dir())
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    use_utf8_stdio()
    sys.exit(main())
