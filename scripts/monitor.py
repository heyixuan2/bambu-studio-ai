#!/usr/bin/env python3
"""
Watch a print and report what matters: start, progress every 30 min, pauses, printer
errors and HMS warnings, a stalled print, and the end (finished, failed or cancelled).

Read-only: it never pauses or changes the print. It reads the printer's status over
local MQTT, so the printer stays in normal cloud mode and the Bambu Handy app keeps
working (and can pause the print if needed).

Usage:
  python3 scripts/monitor.py                    # watch until the print ends (check every 2 min)
  python3 scripts/monitor.py --wait-start 30    # also wait up to 30 min for a print to start
  python3 scripts/monitor.py --once             # one check (for schedulers; state is kept between runs)
  python3 scripts/monitor.py --status           # recent events from the log (no printer needed)
  python3 scripts/monitor.py --json             # one JSON object per event instead of text

Each event is one line on stdout, flushed immediately:
  📢 NOTIFY: <title> — <message>
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

from bambu_studio_ai import hardware
from bambu_studio_ai.monitor import Event, Limits, MonitorState, evaluate
from bambu_studio_ai.printer import PrinterAuthError, PrinterConnectionError, parse_status, read_report
from bambu import printer_settings
from common import desktop_notify, get_config, home_dir, load_config, output_dir, use_utf8_stdio

EXIT_OK, EXIT_FAILED, EXIT_CONFIG = 0, 1, 2
MAX_FAILURES = 10            # consecutive failed checks before giving up (~20 min at the default interval)
WAIT_POLL_SECONDS = 30
LOG_KEEP_LINES = 500


def state_path():
    return os.path.join(home_dir(), "monitor-state.json")


def log_path():
    return os.path.join(output_dir("monitor", create=False), "events.jsonl")


def limits_for(model):
    """Rated maximum temperatures for a printer model (assets/printers.json).

    An unknown or unset model gets the highest ratings in the table, so a printer we
    can't identify never raises a false over-temperature alert.
    """
    try:
        printer = hardware.printer(model or "")
    except hardware.UnknownHardwareError:
        known = hardware.printers().values()
        return Limits(nozzle_c=float(max(p.max_nozzle_c for p in known)),
                      bed_c=float(max(p.max_bed_c for p in known)))
    return Limits(nozzle_c=float(printer.max_nozzle_c), bed_c=float(printer.max_bed_c))


def load_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            return MonitorState.from_dict(json.load(f))
    except (OSError, ValueError):
        return MonitorState()


def save_state(state):
    path = state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f)
    os.replace(tmp, path)


def append_log(event):
    path = log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": datetime.now().isoformat(timespec="seconds"), **event.to_dict()}) + "\n")
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) > 2 * LOG_KEEP_LINES:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines[-LOG_KEEP_LINES:])


def announce(event, *, as_json):
    if as_json:
        print(json.dumps(event.to_dict()), flush=True)
    else:
        print(f"📢 NOTIFY: {event.title} — {event.message}", flush=True)
    append_log(event)
    if event.kind != "progress":
        desktop_notify(event.title, event.message)


class Monitor:
    """One printer, one state; call :meth:`check` on a schedule."""

    def __init__(self, config, *, as_json):
        self.settings = printer_settings(config)
        self.limits = limits_for(get_config("BAMBU_MODEL", config, "model"))
        self.as_json = as_json
        self.state = load_state()

    def check(self):
        """Read the printer once and announce any events. Returns the status (raises on failure)."""
        status = parse_status(read_report(self.settings))
        for event in evaluate(status, self.state, time.time(), self.limits):
            announce(event, as_json=self.as_json)
        save_state(self.state)
        return status


def run_loop(monitor, *, interval, wait_start_min):
    """Watch until the print ends. Returns an exit code."""
    deadline = time.time() + wait_start_min * 60
    failures = 0
    seen_print = False
    while True:
        try:
            status = monitor.check()
            failures = 0
        except PrinterAuthError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return EXIT_FAILED
        except PrinterConnectionError as exc:
            failures += 1
            print(f"⚠️ Check failed ({failures}/{MAX_FAILURES}): {exc}", file=sys.stderr)
            if failures >= MAX_FAILURES:
                announce(Event("alert", "warning", "Monitor stopped",
                               f"Lost contact with the printer after {MAX_FAILURES} tries."), as_json=monitor.as_json)
                return EXIT_FAILED
            time.sleep(interval)
            continue

        if monitor.state.watching or status.active:
            seen_print = True
            time.sleep(interval)
        elif seen_print:
            return EXIT_OK  # the print ended and evaluate() announced how
        elif time.time() < deadline:
            time.sleep(WAIT_POLL_SECONDS)
        else:
            reason = f"No print started within {wait_start_min} min" if wait_start_min else "No print running"
            print(f"{reason}; monitor stopped.", file=sys.stderr)
            return EXIT_OK


def show_log():
    try:
        with open(log_path(), encoding="utf-8") as f:
            entries = [json.loads(line) for line in f if line.strip()]
    except OSError:
        print("No monitor events yet.")
        return EXIT_OK
    for entry in entries[-15:]:
        print(f"[{entry['time']}] {entry['title']}: {entry['message']}")
    state = load_state()
    if state.watching:
        print(f"\nWatching: {state.job or 'current print'}")
    return EXIT_OK


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--auto-pause" in argv:
        print("--auto-pause was removed in v2.1: pausing needs LAN Only + Developer Mode, which disconnects "
              "Bambu Handy. The monitor alerts you instead; pause from the printer screen or Bambu Handy.",
              file=sys.stderr)
        return EXIT_CONFIG
    parser = argparse.ArgumentParser(description="Watch a Bambu Lab print and report important events (read-only).")
    parser.add_argument("--interval", type=int, default=120, help="seconds between checks (default 120)")
    parser.add_argument("--wait-start", type=int, default=0, metavar="MIN",
                        help="if nothing is printing, wait up to MIN minutes for a print to start")
    parser.add_argument("--once", action="store_true", help="check once and exit (state persists between runs)")
    parser.add_argument("--status", action="store_true", help="show recent events; no printer needed")
    parser.add_argument("--json", action="store_true", help="print one JSON object per event")
    args = parser.parse_args(argv)
    if args.interval < 10:
        parser.error("--interval must be at least 10 seconds")

    if args.status:
        return show_log()
    config = load_config(include_secrets=True)
    monitor = Monitor(config, as_json=args.json)
    missing = monitor.settings.missing()
    if missing:
        print("❌ Printer not configured: missing " + ", ".join(missing)
              + ". See: python3 scripts/configure.py show", file=sys.stderr)
        return EXIT_CONFIG
    if args.once:
        try:
            monitor.check()
        except PrinterConnectionError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return EXIT_FAILED
        return EXIT_OK
    monitor.state = MonitorState()  # a new watch session; don't inherit a stale job from an old --once run
    return run_loop(monitor, interval=args.interval, wait_start_min=args.wait_start)


if __name__ == "__main__":
    use_utf8_stdio()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
