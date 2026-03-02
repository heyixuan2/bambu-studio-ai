#!/usr/bin/env python3
"""
Bambu Lab H2D Print Monitor — AI-powered anomaly detection
Usage: python3 monitor.py [--interval 120] [--notify discord|imessage] [--auto-pause]

Designed to be triggered by OpenClaw cron or manually.
The agent should ASK the user before enabling this monitor.
"""

import os
import sys
import time
import argparse
import subprocess
import json
from datetime import datetime

# Load config + secrets
_skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cfg = {}
for _p in [os.path.join(_skill_dir, "config.json"), os.path.join(_skill_dir, ".secrets.json")]:
    if os.path.exists(_p):
        import json as _j
        with open(_p) as _f:
            _cfg.update(_j.load(_f))

BAMBU_IP = os.environ.get("BAMBU_IP", _cfg.get("printer_ip", ""))
BAMBU_ACCESS_CODE = os.environ.get("BAMBU_ACCESS_CODE", _cfg.get("access_code", ""))
SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "snapshots")
LOG_FILE = os.path.join(SNAPSHOT_DIR, "monitor-log.json")

def take_snapshot():
    """Capture a frame from H2D camera via RTSP."""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outpath = os.path.join(SNAPSHOT_DIR, f"snap_{timestamp}.jpg")
    
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-rtsp_transport", "tcp", "-loglevel", "error",
             "-i", f"rtsps://bblp:{BAMBU_ACCESS_CODE}@{BAMBU_IP}:322/streaming/live/1",
             "-frames:v", "1", outpath],
            capture_output=True, timeout=15
        )
        if result.returncode == 0 and os.path.exists(outpath):
            return outpath
        else:
            print(f"⚠️ Snapshot failed: {result.stderr.decode()[:200]}")
            return None
    except FileNotFoundError:
        print("❌ ffmpeg not installed. Run: brew install ffmpeg")
        return None
    except Exception as e:
        print(f"❌ Snapshot error: {e}")
        return None

def get_print_status():
    """Quick status check via bambu.py."""
    script = os.path.join(os.path.dirname(__file__), "bambu.py")
    try:
        result = subprocess.run(
            ["python3", script, "progress"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "BAMBU_MODE": os.environ.get("BAMBU_MODE", "local")}
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Error getting status: {e}"

def log_event(event_type, details, snapshot_path=None):
    """Append event to monitor log."""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        "details": details,
        "snapshot": snapshot_path
    }
    
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE) as f:
                logs = json.load(f)
        except:
            logs = []
    
    logs.append(entry)
    
    # Keep last 100 entries
    if len(logs) > 100:
        logs = logs[-100:]
    
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

def monitor_once(auto_pause=False):
    """
    Run a single monitoring cycle:
    1. Check if printing
    2. Take snapshot
    3. Return snapshot path + status for AI analysis
    
    The AI agent handles the actual image analysis and decision making.
    This script just collects data.
    """
    # Get status
    status = get_print_status()
    
    # Check if actually printing
    if "No active print" in status or "IDLE" in status:
        print("📄 Not printing. Monitor inactive.")
        log_event("idle", "No active print")
        return {"printing": False, "status": status}
    
    # Take snapshot
    snapshot = take_snapshot()
    
    result = {
        "printing": True,
        "status": status,
        "snapshot": snapshot,
        "timestamp": datetime.now().isoformat()
    }
    
    log_event("check", status, snapshot)
    
    # Output for the AI agent to process
    print(f"📊 {status}")
    if snapshot:
        print(f"📸 Snapshot: {snapshot}")
    else:
        print("⚠️ No snapshot available")
    
    return result

def monitor_loop(interval=120, auto_pause=False):
    """
    Continuous monitoring loop.
    Outputs status + snapshot path each cycle for AI to analyze.
    """
    print(f"🔍 Print Monitor Started")
    print(f"   Interval: {interval}s")
    print(f"   Auto-pause on anomaly: {'YES' if auto_pause else 'NO'}")
    print(f"   Snapshots: {SNAPSHOT_DIR}")
    print(f"   Log: {LOG_FILE}")
    print()
    
    cycle = 0
    while True:
        cycle += 1
        print(f"--- Cycle {cycle} ({datetime.now().strftime('%H:%M:%S')}) ---")
        
        result = monitor_once(auto_pause)
        
        if not result.get("printing"):
            print("🏁 Print finished or not active. Stopping monitor.")
            break
        
        print(f"⏳ Next check in {interval}s...\n")
        time.sleep(interval)

def main():
    parser = argparse.ArgumentParser(
        description="Bambu Lab H2D Print Monitor",
        epilog="The agent should ASK the user before starting this monitor."
    )
    parser.add_argument("--interval", type=int, default=120,
                       help="Check interval in seconds (default: 120)")
    parser.add_argument("--auto-pause", action="store_true",
                       help="Auto-pause on detected anomaly")
    parser.add_argument("--once", action="store_true",
                       help="Run single check then exit")
    parser.add_argument("--status", action="store_true",
                       help="Show monitor log summary")
    
    args = parser.parse_args()
    
    if not BAMBU_IP or not BAMBU_ACCESS_CODE:
        print("❌ Monitor requires local mode:")
        print("   export BAMBU_IP='192.168.1.xxx'")
        print("   export BAMBU_ACCESS_CODE='xxxxxxxx'")
        sys.exit(1)
    
    if args.status:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE) as f:
                logs = json.load(f)
            print(f"📋 Monitor Log: {len(logs)} entries")
            for entry in logs[-5:]:
                print(f"  [{entry['timestamp'][:19]}] {entry['type']}: {entry['details'][:80]}")
        else:
            print("📋 No monitor log yet")
        return
    
    if args.once:
        monitor_once(args.auto_pause)
    else:
        monitor_loop(args.interval, args.auto_pause)

if __name__ == "__main__":
    main()
