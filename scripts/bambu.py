#!/usr/bin/env python3
"""
Read-only printer status for Bambu Lab printers, plus "open in Bambu Studio".

Reads status and AMS contents over the printer's local MQTT broker. Needs the
printer's IP, serial number and LAN access code; the printer stays in normal cloud
mode, so the Bambu Handy app keeps working. Nothing here starts, pauses or changes a
print: prints are started from Bambu Studio.

Usage:
  python3 scripts/bambu.py status [--json]     # state, progress, temperatures, AMS
  python3 scripts/bambu.py ams [--json]        # loaded filaments only
  python3 scripts/bambu.py info [--json]       # configured printer (no connection)
  python3 scripts/bambu.py open model.3mf      # open a file in Bambu Studio

Exit codes: 0 ok · 1 printer unreachable · 2 not configured / bad arguments ·
3 missing dependency (paho-mqtt).
"""

import argparse
import json
import sys

from bambu_studio_ai.printer import (
    PrinterAuthError,
    PrinterConnectionError,
    PrinterSettings,
    PrinterStatus,
    Tray,
    parse_status,
    read_report,
)
from common import get_config, load_config, open_in_bambu_studio, use_utf8_stdio

EXIT_OK, EXIT_FAILED, EXIT_CONFIG, EXIT_DEPENDENCY = 0, 1, 2, 3

REMOVED_COMMANDS = {
    "print", "upload", "gcode", "pause", "resume", "cancel", "stop",
    "light", "speed", "snapshot", "progress", "notify",
}
REMOVED_MESSAGE = """\
`bambu.py {command}` was removed in v2.1.

Controlling a printer from third-party software requires LAN Only Mode plus Developer
Mode, which disconnects the Bambu Handy app and cloud printing. This skill keeps the
printer in normal mode and only reads its status.

  • Start a print: python3 scripts/bambu.py open model.3mf, then press Print in Bambu Studio
  • Progress:      python3 scripts/bambu.py status
  • Pause/cancel:  on the printer's screen or in the Bambu Handy app
"""


def printer_settings(config):
    """Printer connection settings from env vars and the user's config/secrets."""
    return PrinterSettings(
        ip=get_config("BAMBU_IP", config, "printer_ip"),
        serial=get_config("BAMBU_SERIAL", config, "serial"),
        access_code=get_config("BAMBU_ACCESS_CODE", config, "access_code"),
    )


def fail(message, code, *, as_json, kind):
    """Report an error on stderr (and as JSON on stdout with --json); return the exit code."""
    if as_json:
        print(json.dumps({"error": {"type": kind, "message": message}}))
    print(f"❌ {message}", file=sys.stderr)
    return code


def fetch_status(config, *, as_json):
    """Connect and return (status, exit_code). status is None on failure."""
    settings = printer_settings(config)
    missing = settings.missing()
    if missing:
        hint = ("Printer not configured: missing " + ", ".join(missing) + ". "
                "Find them on the printer under Settings → Network (IP, access code) "
                "and Settings → Device (serial), then run: python3 scripts/configure.py show")
        return None, fail(hint, EXIT_CONFIG, as_json=as_json, kind="not_configured")
    try:
        return parse_status(read_report(settings)), EXIT_OK
    except ImportError:
        return None, fail("paho-mqtt is not installed: pip install -r requirements.txt",
                          EXIT_DEPENDENCY, as_json=as_json, kind="dependency")
    except PrinterAuthError as exc:
        return None, fail(f"{exc}. Check the access code on the printer (Settings → Network).",
                          EXIT_FAILED, as_json=as_json, kind="auth")
    except PrinterConnectionError as exc:
        return None, fail(str(exc), EXIT_FAILED, as_json=as_json, kind="unreachable")


def tray_label(tray: Tray):
    """Slot name as Bambu Studio shows it: A1…D4, HT1…, or Ext."""
    if tray.unit is None:
        return "Ext"
    if tray.unit >= 128:
        return f"HT{tray.unit - 127}"
    return f"{chr(ord('A') + tray.unit)}{tray.slot + 1}"


def format_tray(tray: Tray):
    name = tray.name or tray.material or "?"
    parts = [("▶ " if tray.active else "  ") + tray_label(tray), name, tray.color or "colour unknown"]
    if tray.remaining_pct is not None:
        parts.append(f"{tray.remaining_pct}% left")
    return "  ".join(parts)


def format_minutes(minutes):
    hours, mins = divmod(minutes, 60)
    return f"{hours} h {mins:02d} min" if hours else f"{mins} min"


def format_temp(current, target):
    if current is None:
        return "—"
    if target:
        return f"{current:.0f}/{target:.0f} °C"
    return f"{current:.0f} °C"


def format_status(status: PrinterStatus, model):
    headline = [status.state]
    if status.active and status.progress_pct is not None:
        headline.append(f"{status.progress_pct}%")
    if status.active and status.layer is not None and status.total_layers:
        headline.append(f"layer {status.layer}/{status.total_layers}")
    if status.active and status.remaining_min is not None:
        headline.append(f"{format_minutes(status.remaining_min)} left")
    lines = [f"🖨️ {model or 'Printer'}: " + " · ".join(headline)]
    if status.file and status.active:
        lines.append(f"File: {status.file}")
    temps = [f"Nozzle {format_temp(status.nozzle_temp, status.nozzle_target)}",
             f"Bed {format_temp(status.bed_temp, status.bed_target)}"]
    if status.chamber_temp is not None:
        temps.append(f"Chamber {format_temp(status.chamber_temp, None)}")
    lines.append(" · ".join(temps))
    extras = [f"Speed {status.speed}" if status.speed else "", f"Light {status.light}" if status.light else ""]
    if any(extras):
        lines.append(" · ".join(e for e in extras if e))
    if status.print_error:
        lines.append(f"⚠️ Printer error {status.print_error} (details on the printer screen or in Bambu Handy)")
    if status.hms:
        lines.append("⚠️ HMS: " + ", ".join(status.hms) + " (look the code up in Bambu Handy or wiki.bambulab.com)")
    lines.append(format_trays(status.trays))
    return "\n".join(lines)


def format_trays(trays):
    if not trays:
        return "Filament: no AMS or spool information reported"
    return "Filament (▶ = feeding):\n" + "\n".join(format_tray(t) for t in trays)


def cmd_status(config, *, as_json):
    status, code = fetch_status(config, as_json=as_json)
    if status is None:
        return code
    model = get_config("BAMBU_MODEL", config, "model")
    if as_json:
        print(json.dumps({"schema": 1, "model": model or None, **status.to_dict()}))
    else:
        print(format_status(status, model))
    return EXIT_OK


def cmd_ams(config, *, as_json):
    status, code = fetch_status(config, as_json=as_json)
    if status is None:
        return code
    if as_json:
        print(json.dumps({"schema": 1, "trays": status.to_dict()["trays"]}))
    else:
        print(format_trays(status.trays))
    return EXIT_OK


def cmd_info(config, *, as_json):
    settings = printer_settings(config)
    info = {
        "model": get_config("BAMBU_MODEL", config, "model") or None,
        "printer_ip": settings.ip or None,
        "serial": (settings.serial[:4] + "…" + settings.serial[-3:]) if len(settings.serial) > 8 else None,
        "access_code_set": bool(settings.access_code),
        "configured": not settings.missing(),
        "missing": settings.missing(),
    }
    if as_json:
        print(json.dumps(info))
        return EXIT_OK
    print(f"Model:       {info['model'] or 'not set'}")
    print(f"Printer IP:  {info['printer_ip'] or 'not set'}")
    print(f"Serial:      {info['serial'] or 'not set'}")
    print(f"Access code: {'set' if info['access_code_set'] else 'not set'}")
    if info["missing"]:
        print("To read status, set: " + ", ".join(info["missing"]) + " (python3 scripts/configure.py)")
    return EXIT_OK


def cmd_open(path):
    ok, message = open_in_bambu_studio(path)
    print(("✅ " if ok else "❌ ") + message, file=sys.stdout if ok else sys.stderr)
    return EXIT_OK if ok else EXIT_FAILED


def build_parser():
    parser = argparse.ArgumentParser(
        description="Read-only Bambu Lab printer status, and 'open in Bambu Studio'.",
        epilog="Prints are started, paused and cancelled in Bambu Studio, on the printer or in Bambu Handy.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("status", "state, progress, temperatures and loaded filaments"),
                            ("ams", "loaded filaments (AMS trays and external spool)"),
                            ("info", "the configured printer, without connecting")):
        sub.add_parser(name, help=help_text).add_argument("--json", action="store_true", help="print one JSON object")
    sub.add_parser("open", help="open a model or project in Bambu Studio").add_argument("filename")
    return parser


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] in REMOVED_COMMANDS:
        print(REMOVED_MESSAGE.format(command=argv[0]), file=sys.stderr)
        return EXIT_CONFIG
    args = build_parser().parse_args(argv)
    if args.command == "open":
        return cmd_open(args.filename)
    config = load_config(include_secrets=True)
    handler = {"status": cmd_status, "ams": cmd_ams, "info": cmd_info}[args.command]
    return handler(config, as_json=args.json)


if __name__ == "__main__":
    use_utf8_stdio()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
