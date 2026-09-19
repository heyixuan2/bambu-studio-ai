#!/usr/bin/env python3
"""
Bambu Lab Print Monitor — Smart anomaly detection with notifications.

Monitoring: every 2 min
Notifications:
  - ALERT: anomaly detected (stalled, temp spike, failure, pause) → immediate
  - PROGRESS: every 30 min summary
  - COMPLETE: print finished

Usage:
  python3 scripts/monitor.py                     # Start monitoring (2min interval)
  python3 scripts/monitor.py --once              # Single check
  python3 scripts/monitor.py --status            # Show log (offline, no printer needed)
  python3 scripts/monitor.py --interval 60       # Custom interval
  python3 scripts/monitor.py --auto-pause        # Auto-pause on anomaly
  python3 scripts/monitor.py --wait-start 30     # Wait up to 30 min for the user to start a print

Output is one line per event (📢 NOTIFY: ...), line-buffered, so an agent can run this
in the background and relay events. Snapshots/logs go to <output dir>/snapshots/.
"""

import os, sys, time, argparse, subprocess, json
from datetime import datetime, timedelta

# ─── Config ───
from common import use_utf8_stdio
from common import load_config, get_config, output_dir, desktop_notify, HIGH_TEMP_PRINTERS
_cfg = load_config(include_secrets=True)

BAMBU_IP = get_config("BAMBU_IP", _cfg, "printer_ip")
BAMBU_ACCESS_CODE = get_config("BAMBU_ACCESS_CODE", _cfg, "access_code")
SNAPSHOT_DIR = output_dir("snapshots", create=False)
LOG_FILE = os.path.join(SNAPSHOT_DIR, "monitor-log.json")
STATE_FILE = os.path.join(SNAPSHOT_DIR, "monitor-state.json")

# Thresholds
STALL_MINUTES = 10       # Alert if progress unchanged for this long
# °C — above the printer's rated maximum (300 °C, or 350 °C on H2C/H2D) is an anomaly
TEMP_MAX_NOZZLE = 355 if get_config("BAMBU_MODEL", _cfg, "model") in HIGH_TEMP_PRINTERS else 305
TEMP_MAX_BED = 120       # °C
PROGRESS_REPORT_MIN = 30 # Minutes between progress reports

# ─── Helpers ───

def _load_state():
    """Load persistent monitor state."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "last_progress": None,
        "last_progress_time": None,
        "last_report_time": None,
        "alerts_sent": [],
        "print_started": None,
    }

def _save_state(state):
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def take_snapshot():
    """Capture a frame from printer camera via RTSP."""
    from urllib.parse import quote
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    outpath = os.path.join(SNAPSHOT_DIR, f"snap_{ts}.jpg")
    safe_code = quote(BAMBU_ACCESS_CODE, safe='')
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-rtsp_transport", "tcp", "-loglevel", "error",
             "-i", f"rtsps://bblp:{safe_code}@{BAMBU_IP}:322/streaming/live/1",
             "-frames:v", "1", outpath],
            capture_output=True, timeout=15)
        return outpath if r.returncode == 0 and os.path.exists(outpath) else None
    except Exception:
        return None

def get_status_dict():
    """Get structured printer status via bambu.py."""
    script = os.path.join(os.path.dirname(__file__), "bambu.py")
    try:
        r = subprocess.run(
            [sys.executable, script, "status", "--json"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BAMBU_MODE": get_config("BAMBU_MODE", _cfg, "mode", "local")})
        if r.returncode == 0:
            return json.loads(r.stdout)
    except Exception:
        pass
    # Fallback: parse text output
    try:
        r = subprocess.run(
            [sys.executable, script, "status"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BAMBU_MODE": get_config("BAMBU_MODE", _cfg, "mode", "local")})
        if r.returncode != 0:
            return {"error": (r.stdout + r.stderr).strip()[-300:] or f"bambu.py exited {r.returncode}"}
        return {"raw": r.stdout.strip()}
    except Exception as e:
        return {"error": str(e)}

def notify(title, message, snapshot=None):
    """Print an event line (for the agent reading stdout) and show a desktop notification."""
    one_line = " | ".join(part.strip() for part in message.splitlines() if part.strip())
    print(f"📢 NOTIFY: {title} — {one_line}" + (f" [snapshot: {snapshot}]" if snapshot else ""), flush=True)
    desktop_notify(title, one_line)

def log_event(event_type, details, snapshot=None):
    """Append to monitor log (keep last 200)."""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        "details": details,
        "snapshot": snapshot
    }
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                logs = json.load(f)
        except Exception:
            pass
    logs.append(entry)
    if len(logs) > 200:
        logs = logs[-200:]
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

def pause_print():
    """Send pause command."""
    script = os.path.join(os.path.dirname(__file__), "bambu.py")
    try:
        r = subprocess.run([sys.executable, script, "pause"],
                          capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False

# ─── Anomaly Detection ───

def check_anomalies(status, state):
    """Check for anomalies. Returns list of (severity, message) tuples."""
    alerts = []
    now = datetime.now()
    
    progress = status.get("progress")
    nozzle = status.get("nozzle_temp")
    bed = status.get("bed_temp")
    printer_state = str(status.get("state", "")).upper()
    
    # 1. Print failure/error states
    for bad_state in ["FAILED", "ERROR", "FAULT", "ABORT"]:
        if bad_state in printer_state:
            alerts.append(("critical", f"🚨 Print error state: {printer_state}"))
    
    # 2. Unexpected pause (not by us)
    if "PAUSE" in printer_state and "auto_pause" not in [a.get("type") for a in state.get("alerts_sent", [])[-3:]]:
        alerts.append(("warning", f"⏸️ Printer paused (state: {printer_state})"))
    
    # 3. Temperature anomaly
    try:
        if nozzle and float(nozzle) > TEMP_MAX_NOZZLE:
            alerts.append(("critical", f"🔥 Nozzle temp too high: {nozzle}°C (max {TEMP_MAX_NOZZLE}°C)"))
        if bed and float(bed) > TEMP_MAX_BED:
            alerts.append(("critical", f"🔥 Bed temp too high: {bed}°C (max {TEMP_MAX_BED}°C)"))
    except (ValueError, TypeError):
        pass
    
    # 4. Progress stall detection
    if progress is not None:
        try:
            progress = float(progress)
        except Exception:
            progress = None
    
    if progress is not None:
        last_p = state.get("last_progress")
        last_t = state.get("last_progress_time")
        
        if last_p is not None and last_t:
            try:
                last_time = datetime.fromisoformat(last_t)
                minutes_since = (now - last_time).total_seconds() / 60
                
                if float(last_p) == progress and minutes_since >= STALL_MINUTES:
                    alerts.append(("warning", 
                        f"⚠️ Progress stalled: {progress}% stalled for {minutes_since:.0f} min unchanged"))
            except Exception:
                pass
        
        # Update progress tracking
        if last_p is None or float(last_p) != progress:
            state["last_progress"] = progress
            state["last_progress_time"] = now.isoformat()
    
    return alerts

# ─── Main Monitor ───

def monitor_once(auto_pause=False):
    """Single monitoring cycle with anomaly detection."""
    status = get_status_dict()
    state = _load_state()
    now = datetime.now()
    
    # Handle raw/error responses
    if "error" in status:
        print(f"❌ Status error: {status['error']}")
        return {"printing": False, "error": True, "status": status}
    
    if "raw" in status:
        raw = status["raw"]
        if "IDLE" in raw.upper() or "No active" in raw:
            # Check if we were tracking a print (= just finished)
            if state.get("print_started"):
                notify("Print Complete ✅", f"Print finished! Started at {state['print_started']}")
                state["print_started"] = None
                _save_state(state)
                log_event("complete", "Print finished")
            return {"printing": False, "status": status}
        print(f"📊 {raw}")
        return {"printing": True, "status": status}
    
    printer_state = str(status.get("state", "")).upper()
    progress = status.get("progress")
    
    # Not printing
    if "IDLE" in printer_state or progress is None:
        if state.get("print_started"):
            notify("Print Complete ✅", f"Print finished!")
            state["print_started"] = None
            _save_state(state)
            log_event("complete", "Print finished")
        return {"printing": False, "status": status}
    
    # Mark print start
    if not state.get("print_started"):
        state["print_started"] = now.isoformat()
    
    # Take snapshot
    snapshot = take_snapshot()
    
    # Check anomalies
    alerts = check_anomalies(status, state)
    
    # Handle alerts
    for severity, message in alerts:
        snapshot_note = f"\n📸 Snapshot saved: {snapshot}" if snapshot else ""
        remaining = status.get("remaining", "?")
        context = f"\nProgress: {progress}% | Remaining: {remaining}"
        
        notify(f"Print Alert {'🚨' if severity == 'critical' else '⚠️'}", 
               message + context + snapshot_note, snapshot)
        
        if severity == "critical" and auto_pause:
            if pause_print():
                notify("Auto-paused ⏸️", f"Reason: {message}")
        
        state.setdefault("alerts_sent", []).append({
            "type": severity, "message": message, "time": now.isoformat()
        })
        # Keep only last 20 alerts in state
        state["alerts_sent"] = state["alerts_sent"][-20:]
        
        log_event(f"alert_{severity}", message, snapshot)
    
    # Progress report (every 30 min, only if no alerts this cycle)
    if not alerts:
        last_report = state.get("last_report_time")
        should_report = False
        if not last_report:
            should_report = True
        else:
            try:
                minutes_since_report = (now - datetime.fromisoformat(last_report)).total_seconds() / 60
                if minutes_since_report >= PROGRESS_REPORT_MIN:
                    should_report = True
            except Exception:
                should_report = True
        
        if should_report:
            remaining = status.get("remaining", "?")
            nozzle = status.get("nozzle_temp", "?")
            bed = status.get("bed_temp", "?")
            file_name = status.get("file", "")
            
            msg = f"📊 Progress: {progress}%"
            if remaining and remaining != "?":
                msg += f" | Remaining: {remaining}"
            msg += f"\n🔥 Nozzle: {nozzle}°C | 🛏️ Bed: {bed}°C"
            if file_name:
                msg += f"\n📁 {file_name}"
            
            notify("Print Progress", msg)
            state["last_report_time"] = now.isoformat()
            log_event("progress_report", {"progress": progress, "remaining": remaining})
    
    _save_state(state)
    
    # Console output
    print(f"📊 Progress: {progress}% | State: {printer_state}")
    if snapshot:
        print(f"📸 {snapshot}")
    if alerts:
        print(f"🚨 {len(alerts)} alert(s)")
    
    log_event("check", {
        "progress": progress, "state": printer_state,
        "alerts": len(alerts)
    }, snapshot)
    
    return {"printing": True, "status": status, "alerts": alerts, "snapshot": snapshot}

def monitor_loop(interval=120, auto_pause=False, wait_start_min=0):
    """Continuous monitoring loop.

    wait_start_min > 0: if nothing is printing yet, keep polling (every <=30s) for up to
    that many minutes for a print to start — e.g. right after handing a model to
    Bambu Studio — instead of exiting immediately.
    """
    print(f"🔍 Print monitor started")
    print(f"   Check interval: {interval}s")
    print(f"   Auto-pause: {'Yes' if auto_pause else 'No'}")
    print(f"   Progress report: Every {PROGRESS_REPORT_MIN} min")
    print(f"   Anomaly alert: Realtime")
    print(f"   Snapshot dir: {SNAPSHOT_DIR}")
    if wait_start_min:
        print(f"   Waiting up to {wait_start_min} min for a print to start")
    print()
    
    # Reset state for new session
    state = _load_state()
    state["last_report_time"] = None  # Force first report
    if wait_start_min:
        state["print_started"] = None  # Stale state from an old run would fake a "complete" event
    _save_state(state)
    
    cycle = 0
    consecutive_failures = 0
    max_failures = 5
    seen_printing = False
    wait_deadline = time.time() + wait_start_min * 60 if wait_start_min else 0
    
    while True:
        cycle += 1
        print(f"--- Cycle {cycle} ({datetime.now().strftime('%H:%M:%S')}) ---")
        
        try:
            result = monitor_once(auto_pause)
            if result.get("error"):
                raise RuntimeError("printer status unavailable")
            consecutive_failures = 0
            
            if result.get("printing"):
                if not seen_printing and wait_start_min:
                    notify("Print Started 🖨️", "Print detected — monitoring started")
                seen_printing = True
            elif not seen_printing and time.time() < wait_deadline:
                print("⏳ No print running yet — waiting for it to start...")
                time.sleep(min(interval, 30))
                continue
            elif not seen_printing and wait_start_min:
                print(f"⌛ No print started within {wait_start_min} min, monitor stopped.")
                break
            else:
                print("🏁 Print complete or idle, monitor stopped.")
                break
        except Exception as e:
            consecutive_failures += 1
            print(f"❌ Check failed ({consecutive_failures}/{max_failures}): {e}")
            if consecutive_failures >= max_failures:
                notify("Monitor Error ⛔", f"Consecutive {max_failures} check failures, monitor stopped: {e}")
                break
        
        time.sleep(interval)

def main():
    parser = argparse.ArgumentParser(
        description="Bambu Lab Print Monitor — smart anomaly detection",
        epilog="Ask the user before starting the monitor or enabling --auto-pause.")
    parser.add_argument("--interval", type=int, default=120,
                       help="Check interval in seconds (default: 120)")
    parser.add_argument("--auto-pause", action="store_true",
                       help="Auto-pause on critical anomaly")
    parser.add_argument("--once", action="store_true",
                       help="Single check then exit")
    parser.add_argument("--wait-start", type=int, default=0, metavar="MIN",
                       help="If idle, wait up to MIN minutes for a print to start, then monitor it")
    parser.add_argument("--status", action="store_true",
                       help="Show log summary (offline, no printer needed)")
    args = parser.parse_args()

    # Line-buffer stdout so agents tailing a background run see each event immediately.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    
    if args.status:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                logs = json.load(f)
            print(f"📋 Monitor Log: {len(logs)} entries")
            for entry in logs[-10:]:
                print(f"  [{entry['timestamp'][:19]}] {entry['type']}: {str(entry.get('details',''))[:80]}")
        else:
            print("📋 No monitor log yet")
        
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                state = json.load(f)
            if state.get("print_started"):
                print(f"\n🖨️ Active print since: {state['print_started'][:19]}")
            if state.get("last_progress"):
                print(f"   Last progress: {state['last_progress']}%")
        return
    
    if not BAMBU_IP or not BAMBU_ACCESS_CODE:
        print("❌ Monitor requires LAN mode settings:")
        print("   python3 scripts/configure.py set printer_ip <ip>")
        print("   python3 scripts/configure.py secret access_code")
        print("   Or: export BAMBU_IP='x.x.x.x' BAMBU_ACCESS_CODE='xxxxxxxx'")
        sys.exit(1)
    
    if args.once:
        monitor_once(args.auto_pause)
    else:
        monitor_loop(args.interval, args.auto_pause, wait_start_min=args.wait_start)

if __name__ == "__main__":
    use_utf8_stdio()
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️ Cancelled.")
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"❌ Monitor error: {e}", file=sys.stderr)
        sys.exit(1)
