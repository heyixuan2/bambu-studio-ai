#!/usr/bin/env python3
"""
Bambu Lab Printer Control (All Models) — Dual Mode (Cloud API + Local MQTT)
Usage: python3 scripts/bambu.py <command> [args]

Modes:
  BAMBU_MODE=cloud  → Remote via Bambu Cloud API (anywhere)
  BAMBU_MODE=local  → Local via MQTT (same network)
"""

import os
import sys
import time
import argparse

MODE = os.environ.get("BAMBU_MODE", "").lower()

# Load config.json + .secrets.json (fallback for env vars)
_config = {}
_skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cpath = os.path.join(_skill_dir, "config.json")
if os.path.exists(_cpath):
    import json as _j
    with open(_cpath) as _f:
        _config = _j.load(_f)

# Load secrets
_secrets_path = os.path.join(_skill_dir, ".secrets.json")
if os.path.exists(_secrets_path):
    import json as _j
    with open(_secrets_path) as _f:
        _config.update(_j.load(_f))

# Config.json values as fallbacks for env vars
if not MODE:
    MODE = _config.get("mode", "local").lower()
for _k, _e in [("printer_ip", "BAMBU_IP"), ("serial", "BAMBU_SERIAL"),
               ("access_code", "BAMBU_ACCESS_CODE"), ("email", "BAMBU_EMAIL"),
               ("password", "BAMBU_PASSWORD"), ("device_id", "BAMBU_DEVICE_ID")]:
    if not os.environ.get(_e) and _config.get(_k):
        os.environ[_e] = _config[_k]

# ─── Cloud API Backend ───────────────────────────────────────────────

class CloudBackend:
    def __init__(self):
        try:
            from bambulab import BambuClient, BambuAuthenticator
        except ImportError:
            print("❌ bambu-lab-cloud-api not installed.")
            print("   Run: pip3 install --break-system-packages bambu-lab-cloud-api")
            sys.exit(1)

        email = os.environ.get("BAMBU_EMAIL", "")
        password = os.environ.get("BAMBU_PASSWORD", "")
        if not email or not password:
            print("❌ Missing cloud credentials:")
            if not email: print("   export BAMBU_EMAIL='your@email.com'")
            if not password: print("   export BAMBU_PASSWORD='your_password'")
            sys.exit(1)

        # Token cache: avoid re-login every run
        _token_cache = os.path.join(_skill_dir, ".token_cache.json")
        cached_token = None
        if os.path.exists(_token_cache):
            try:
                import json as _tj
                with open(_token_cache) as _tf:
                    _tc = _tj.load(_tf)
                    cached_token = _tc.get("token")
                    cache_time = _tc.get("timestamp", 0)
                    import time
                    # Token valid for 24 hours
                    if time.time() - cache_time > 86400:
                        cached_token = None
                        print("🔄 Cached token expired, re-authenticating...")
            except Exception:
                cached_token = None

        if cached_token:
            try:
                self.client = BambuClient(token=cached_token)
                print("✅ Using cached login token")
                return
            except Exception:
                print("⚠️ Cached token invalid, re-authenticating...")
                cached_token = None

        try:
            auth = BambuAuthenticator()
            # First attempt — may trigger verification code
            try:
                token = auth.login(email, password)
            except Exception as login_err:
                err_msg = str(login_err).lower()
                if "verify" in err_msg or "code" in err_msg or "captcha" in err_msg:
                    print("📧 Verification code required!")
                    print("   Check your email for the code from Bambu Lab.")
                    print("")
                    # Check for code via env var or file (non-blocking for autonomous agents)
                    verify_code = os.environ.get("BAMBU_VERIFY_CODE", "")
                    verify_file = os.path.join(_skill_dir, ".verify_code")
                    if not verify_code and os.path.exists(verify_file):
                        with open(verify_file) as _vf:
                            verify_code = _vf.read().strip()
                        os.remove(verify_file)  # One-time use
                    if not verify_code:
                        print("   To provide the code, either:")
                        print("   1. Set env: export BAMBU_VERIFY_CODE=123456")
                        print("   2. Write to file: echo 123456 > .verify_code")
                        print("   3. Re-run with: BAMBU_VERIFY_CODE=123456 python3 scripts/bambu.py status")
                        print("")
                        print("   💡 TIP: Use LAN mode instead to avoid verification entirely.")
                        sys.exit(1)
                    token = auth.login(email, password, verify_code=verify_code)
                else:
                    raise login_err

            self.client = BambuClient(token=token)

            # Cache the token
            import json as _tj, time as _tt
            with open(_token_cache, "w") as _tf:
                _tj.dump({"token": token, "timestamp": _tt.time(), "email": email}, _tf)
            os.chmod(_token_cache, 0o600)
            print("✅ Logged in and token cached (valid 24h)")

        except Exception as e:
            print(f"❌ Cloud login failed: {e}")
            print("   Check email/password, or try again later")
            print("   💡 TIP: If stuck on verification codes, use LAN mode instead (faster + more features)")
            sys.exit(1)

        # Get printer
        device_id = os.environ.get("BAMBU_DEVICE_ID", "")
        if device_id:
            self.device_id = device_id
        else:
            try:
                devices = self.client.get_devices()
                if not devices:
                    print("❌ No printers found on your Bambu account")
                    sys.exit(1)
                self.device_id = devices[0].get("dev_id", devices[0].get("id", ""))
                name = devices[0].get("name", self.device_id)
                print(f"📡 Using printer: {name}")
            except Exception as e:
                print(f"❌ Cannot get printer list: {e}")
                sys.exit(1)

    def get_status(self):
        try:
            return self.client.get_print_status(self.device_id)
        except:
            return self.client.get_device_info(self.device_id)

    def get_ams(self):
        try:
            return self.client.get_ams_filaments(self.device_id)
        except:
            return None

    def pause(self):
        self.client._request("POST", f"/v1/devices/{self.device_id}/commands",
                           json={"print": {"command": "pause"}})

    def resume(self):
        self.client._request("POST", f"/v1/devices/{self.device_id}/commands",
                           json={"print": {"command": "resume"}})

    def stop(self):
        self.client._request("POST", f"/v1/devices/{self.device_id}/commands",
                           json={"print": {"command": "stop"}})

    def set_light(self, on):
        mode = "on" if on else "off"
        self.client._request("POST", f"/v1/devices/{self.device_id}/commands",
                           json={"system": {"led_mode": mode}})

    def set_speed(self, level):
        self.client._request("POST", f"/v1/devices/{self.device_id}/commands",
                           json={"print": {"command": "print_speed", "param": str(level)}})

    def start_print(self, filename, plate_number=1):
        # Try multiple calling conventions for different library versions
        try:
            self.client.start_cloud_print(self.device_id, filename, plate_number=plate_number)
        except TypeError:
            try:
                self.client.start_cloud_print(self.device_id, filename)
            except TypeError:
                self.client.start_cloud_print(device_id=self.device_id, filename=filename)

    def disconnect(self):
        pass


# ─── Local MQTT Backend ──────────────────────────────────────────────

class LocalBackend:
    def __init__(self):
        try:
            import bambulabs_api as bl
        except ImportError:
            print("❌ bambulabs-api not installed.")
            print("   Run: pip3 install --break-system-packages bambulabs-api")
            sys.exit(1)

        ip = os.environ.get("BAMBU_IP", "")
        serial = os.environ.get("BAMBU_SERIAL", "")
        access_code = os.environ.get("BAMBU_ACCESS_CODE", "")

        if not all([ip, serial, access_code]):
            print("❌ Missing local connection vars:")
            if not ip: print("   export BAMBU_IP='192.168.1.xxx'")
            if not serial: print("   export BAMBU_SERIAL='01P00Axxxxxxx'")
            if not access_code: print("   export BAMBU_ACCESS_CODE='xxxxxxxx'")
            sys.exit(1)

        self.ip = ip
        self.access_code = access_code
        # LAN MQTT uses self-signed certs — pass verify=False only to the printer connection
        # DO NOT disable SSL globally (would weaken all network calls)
        try:
            self.printer = bl.Printer(ip, access_code, serial, ssl_verify=False)
        except TypeError:
            # Older bambulabs-api versions don't accept ssl_verify
            self.printer = bl.Printer(ip, access_code, serial)
        self.printer.connect()
        time.sleep(2)

    def get_status(self):
        p = self.printer
        return {
            "nozzle_temp": p.get_nozzle_temperature(),
            "nozzle_target": getattr(p, "get_target_nozzle_temperature", p.get_nozzle_temperature)(),
            "bed_temp": p.get_bed_temperature(),
            "bed_target": p.get_bed_temperature(),  # API limitation: no target temp method
            "state": p.get_current_state(),
            "progress": p.get_percentage(),
            "remaining": p.get_time(),
            "file": p.get_file_name(),
            "speed": p.get_print_speed(),
            "light": p.get_light_state(),
            "layer": getattr(p, 'get_current_layer', lambda: None)(),
            "total_layers": getattr(p, 'get_total_layers', lambda: None)(),
        }

    def get_ams(self):
        try:
            if hasattr(self.printer, 'get_ams'):
                return self.printer.get_ams()
            elif hasattr(self.printer, 'ams_hub'):
                return self.printer.ams_hub
            else:
                return None
        except:
            return None

    def pause(self):
        self.printer.pause_print()

    def resume(self):
        self.printer.resume_print()

    def stop(self):
        self.printer.stop_print()

    def set_light(self, on):
        if on:
            self.printer.turn_light_on()
        else:
            self.printer.turn_light_off()

    def set_speed(self, level):
        if hasattr(self.printer, 'set_print_speed'):
            self.printer.set_print_speed(level)
        elif hasattr(self.printer, 'set_speed_level'):
            self.printer.set_speed_level(level)
        else:
            print("⚠️ Speed control not supported by this bambulabs-api version")

    def start_print(self, filename, plate_number=1):
        self.printer.start_print(filename, plate_number=plate_number)

    def disconnect(self):
        self.printer.disconnect()


# ─── Notifications ───

def notify(title, message, channel="auto"):
    """Send notification via the user's current channel.
    
    channel: auto (detect), discord, imessage, telegram, console
    In agent context, the agent handles notifications via its messaging tools.
    This is a fallback for standalone script usage.
    """
    print(f"🔔 {title}: {message}")
    
    # Try macOS notification
    try:
        import subprocess
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "Bambu Studio AI" subtitle "{title}"'
        ], timeout=5, capture_output=True)
    except:
        pass
    
    # Log to file for agent pickup
    _skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_path = os.path.join(_skill_dir, "output", "notifications.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    import json as _nj, time as _nt
    entry = {"timestamp": _nt.time(), "title": title, "message": message, "channel": channel}
    with open(log_path, "a") as f:
        f.write(_nj.dumps(entry) + "\n")


# ─── Unified Commands ────────────────────────────────────────────────

def get_backend():
    if MODE == "cloud":
        email = os.environ.get("BAMBU_EMAIL") or _config.get("email")
        password = os.environ.get("BAMBU_PASSWORD") or _config.get("password")
        if not email or not password:
            print("❌ Cloud mode requires BAMBU_EMAIL and BAMBU_PASSWORD.")
            print("   Set in config.json or environment variables.")
            print("   Or switch to LAN mode: set mode=local in config.json")
            raise SystemExit(1)
        return CloudBackend()
    else:
        return LocalBackend()

SPEED_NAMES = {1: "Silent", 2: "Standard", 3: "Sport", 4: "Ludicrous"}

def cmd_info(json_output=False):
    """Get printer hardware info for slicing: model, nozzle, AMS filaments."""
    info = {
        "model": _config.get("model") or _config.get("printer_model", "Unknown"),
        "nozzle_diameter": None,
        "nozzle_type": None,
        "filaments": [],
    }

    if MODE == "local":
        try:
            import io, contextlib
            _buf = io.StringIO()
            with contextlib.redirect_stdout(_buf), contextlib.redirect_stderr(_buf):
                backend = get_backend()
            printer = backend.printer
            # Nozzle info
            try:
                nd = printer.nozzle_diameter
                info["nozzle_diameter"] = nd() if callable(nd) else nd
            except: pass
            try:
                nt = printer.nozzle_type
                info["nozzle_type"] = nt() if callable(nt) else nt
            except: pass

            # AMS filaments
            try:
                ams = backend.get_ams()
                if isinstance(ams, list):
                    for slot in ams:
                        if isinstance(slot, dict):
                            info["filaments"].append({
                                "slot": slot.get("tray_id", slot.get("slot", "?")),
                                "color": slot.get("tray_color", slot.get("color", "")),
                                "type": slot.get("tray_type", slot.get("type", "")),
                                "name": slot.get("tray_sub_brands", slot.get("name", "")),
                            })
                elif hasattr(ams, '__iter__'):
                    for item in ams:
                        info["filaments"].append({"raw": str(item)})
            except: pass
        except (Exception, SystemExit):
            # Printer not reachable — show config info only
            info["_offline"] = True
    else:
        # Cloud mode — limited info
        pass

    if json_output:
        import json as _json
        print(_json.dumps(info, ensure_ascii=False))
    else:
        if info.get("_offline"):
            print("⚠️  Printer offline — showing config defaults")
        print(f"🖨️  Model: {info['model']}")
        nd = info.get('nozzle_diameter')
        nt = info.get('nozzle_type')
        if nd:
            print(f"🔧 Nozzle: {nd}mm" + (f" ({nt})" if nt else ""))
        if info['filaments']:
            print(f"🧵 AMS Filaments:")
            for f in info['filaments']:
                if 'raw' in f:
                    print(f"   {f['raw']}")
                else:
                    color = f.get('color', '')
                    ftype = f.get('type', '')
                    fname = f.get('name', '')
                    print(f"   Slot {f.get('slot','?')}: {ftype} {fname} #{color}")
        else:
            print(f"🧵 No AMS filament info available")


def cmd_status(json_output=False):
    backend = get_backend()
    try:
        s = backend.get_status()
        if json_output:
            import json as _json
            print(_json.dumps(s))
            return
        mode_label = "☁️ Cloud" if MODE == "cloud" else "🔌 LAN"
        print(f"{mode_label} | Bambu Lab {_config.get('model', 'Unknown')}")

        if MODE == "local":
            print(f"🔥 Nozzle: {s.get('nozzle_temp', '?')}°C / {s.get('nozzle_target', '?')}°C")
            print(f"🛏️ Bed: {s.get('bed_temp', '?')}°C / {s.get('bed_target', '?')}°C")
            print(f"📄 State: {s.get('state', '?')}")
            print(f"🏎️ Speed: {SPEED_NAMES.get(s.get('speed'), s.get('speed', '?'))}")
            print(f"💡 Light: {'ON' if s.get('light') else 'OFF'}")

            if s.get("state") in ["RUNNING", "PAUSE"]:
                print(f"📁 File: {s.get('file', 'Unknown')}")
                print(f"📊 Progress: {s.get('progress', '?')}%")
                if s.get("layer") and s.get("total_layers"):
                    print(f"📐 Layer: {s['layer']}/{s['total_layers']}")
                r = s.get("remaining")
                if r:
                    print(f"⏳ Remaining: {r // 60}h {r % 60}m")
        else:
            # Cloud — parse whatever structure comes back
            if isinstance(s, dict):
                for key in ["gcode_state", "mc_percent", "mc_remaining_time",
                            "nozzle_temper", "bed_temper", "subtask_name"]:
                    val = s.get(key) or (s.get("print", {}) or {}).get(key)
                    if val is not None:
                        labels = {
                            "gcode_state": "📄 State",
                            "mc_percent": "📊 Progress",
                            "mc_remaining_time": "⏳ Remaining (min)",
                            "nozzle_temper": "🔥 Nozzle (°C)",
                            "bed_temper": "🛏️ Bed (°C)",
                            "subtask_name": "📁 File",
                        }
                        print(f"{labels.get(key, key)}: {val}")
            else:
                print(f"📊 Status: {s}")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        backend.disconnect()

def cmd_progress():
    backend = get_backend()
    try:
        s = backend.get_status()
        if MODE == "local":
            state = s.get("state", "?")
            if state not in ["RUNNING", "PAUSE"]:
                print(f"📄 No active print (state: {state})")
                return
            print(f"📁 File: {s.get('file', 'Unknown')}")
            print(f"📊 Progress: {s.get('progress', '?')}%")
            if s.get("layer") and s.get("total_layers"):
                print(f"📐 Layer: {s['layer']}/{s['total_layers']}")
            r = s.get("remaining")
            if r:
                print(f"⏳ Remaining: {r // 60}h {r % 60}m")
        else:
            if isinstance(s, dict):
                pct = s.get("mc_percent") or (s.get("print", {}) or {}).get("mc_percent", "?")
                remaining = s.get("mc_remaining_time") or (s.get("print", {}) or {}).get("mc_remaining_time")
                state = s.get("gcode_state") or (s.get("print", {}) or {}).get("gcode_state", "?")
                print(f"📄 State: {state}")
                print(f"📊 Progress: {pct}%")
                if remaining:
                    print(f"⏳ Remaining: {remaining} min")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        backend.disconnect()

def cmd_pause():
    b = get_backend()
    try: b.pause(); print("⏸️ Print paused")
    finally: b.disconnect()

def cmd_resume():
    b = get_backend()
    try: b.resume(); print("▶️ Print resumed")
    finally: b.disconnect()

def cmd_cancel():
    b = get_backend()
    try: b.stop(); print("🛑 Print cancelled")
    finally: b.disconnect()

def cmd_light(state):
    b = get_backend()
    try: b.set_light(state == "on"); print(f"💡 Light {'ON' if state == 'on' else 'OFF'}")
    finally: b.disconnect()

def cmd_speed(mode):
    speed_map = {"silent": 1, "standard": 2, "sport": 3, "ludicrous": 4}
    level = speed_map.get(mode.lower())
    if not level:
        print(f"❌ Unknown mode: {mode}. Options: silent, standard, sport, ludicrous")
        return
    b = get_backend()
    try: b.set_speed(level); print(f"🏎️ Speed: {mode.capitalize()}")
    finally: b.disconnect()

def cmd_print(filename, confirmed=False):
    if not confirmed:
        print("⛔ Safety: Preview in Bambu Studio first, then re-run with --confirmed")
        print(f"   python3 scripts/bambu.py print {filename} --confirmed")
        sys.exit(1)
    b = get_backend()
    try: b.start_print(filename, plate_number=1); print(f"✅ Started printing: {filename}")
    except Exception as e: print(f"❌ Error: {e}")
    finally: b.disconnect()

def cmd_ams():
    b = get_backend()
    try:
        ams = b.get_ams()
        if not ams:
            print("📦 No AMS data available")
            return
        print("📦 AMS Status:")
        if isinstance(ams, list):
            for i, slot in enumerate(ams):
                if slot:
                    t = slot.get("type", slot.get("tray_type", "?"))
                    c = slot.get("color", slot.get("tray_color", "?"))
                    r = slot.get("remain", slot.get("remain_pct", "?"))
                    print(f"  Slot {i+1}: {t} | Color: #{c} | Remaining: {r}%")
                else:
                    print(f"  Slot {i+1}: Empty")
        else:
            print(f"  Raw: {ams}")
    except Exception as e:
        print(f"⚠️ AMS: {e}")
    finally:
        b.disconnect()

def cmd_snapshot():
    if MODE == "cloud":
        print("❌ Camera snapshots not available in Cloud mode.")
        print("   Switch to LAN mode for camera access.")
        return

    ip = os.environ.get("BAMBU_IP", _config.get("printer_ip", ""))
    ac = os.environ.get("BAMBU_ACCESS_CODE", _config.get("access_code", ""))
    if not ip or not ac:
        # Try loading from secrets
        _sp = os.path.join(_skill_dir, ".secrets.json")
        if os.path.exists(_sp):
            import json as _sj
            with open(_sp) as _sf:
                _sd = _sj.load(_sf)
                ac = ac or _sd.get("access_code", "")
        if not ip:
            print("❌ BAMBU_IP not set. Check config.json or set env var.")
            return
        if not ac:
            print("❌ Access code not set. Check .secrets.json or set BAMBU_ACCESS_CODE.")
            return

    out = os.path.join(_skill_dir, "output", "snapshots", "snapshot.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    # Use RTSP stream (port 322) — NOT port 6000 socket
    # Port 6000 is incompatible with H2D and newer firmware (SSL handshake failure)
    # RTSP via ffmpeg is the reliable method for all models
    print(f"📸 Capturing from RTSP stream ({ip}:322)...")
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-y", "-update", "1", "-rtsp_transport", "tcp",
             "-i", f"rtsps://bblp:{ac}@{ip}:322/streaming/live/1",
             "-frames:v", "1", out],
            capture_output=True, timeout=15
        )
        if result.returncode == 0 and os.path.exists(out):
            size = os.path.getsize(out)
            print(f"📸 Snapshot saved: {out} ({size // 1024} KB)")
        else:
            stderr = result.stderr.decode()[:300]
            print(f"⚠️ ffmpeg error: {stderr}")
            if "Connection refused" in stderr or "timeout" in stderr.lower():
                print("   💡 Camera may be in use by Bambu Studio or phone app.")
                print("   Only one client can access the camera at a time.")
                print("   Close other viewers and try again.")
            elif "401" in stderr or "Unauthorized" in stderr:
                print("   💡 Wrong access code. Check Settings → Device on printer.")
    except FileNotFoundError:
        print("❌ ffmpeg not installed. Run: brew install ffmpeg")
    except subprocess.TimeoutExpired:
        print("⚠️ Camera timeout. Possible causes:")
        print("   1. Camera in use by another app (phone/Bambu Studio)")
        print("   2. Printer in sleep mode (tap touchscreen)")
        print("   3. Wrong IP address")
    except Exception as e:
        print(f"❌ Error: {e}")

def cmd_gcode(code):
    """Send raw G-code to printer (local mode only)."""
    if MODE != "local":
        print("⚠️ G-code requires local mode: export BAMBU_MODE=local")
        return
    b = get_backend()
    try:
        # Send via MQTT
        b.printer.send_gcode(code)
        print(f"📟 G-code sent: {code}")
    except AttributeError:
        # Fallback: direct MQTT publish
        import json as _json
        topic = f"device/{os.environ.get('BAMBU_SERIAL', '')}/request"
        payload = {"print": {"command": "gcode_line", "param": code}}
        try:
            b.printer._client.publish(topic, _json.dumps(payload))
            print(f"📟 G-code sent (MQTT): {code}")
        except Exception as e:
            print(f"❌ G-code error: {e}")
    finally:
        b.disconnect()

def main():
    parser = argparse.ArgumentParser(
        description="Bambu Lab Printer Control (All Models) (Cloud + Local)",
        epilog=f"Current mode: {MODE.upper()} | Set BAMBU_MODE=cloud or BAMBU_MODE=local"
    )
    sub = parser.add_subparsers(dest="command")
    sp_info = sub.add_parser("info"); sp_info.add_argument("--json", action="store_true", help="JSON output")
    sp_status = sub.add_parser("status"); sp_status.add_argument("--json", action="store_true", help="JSON output")
    sub.add_parser("progress")
    sub.add_parser("pause")
    sub.add_parser("resume")
    sub.add_parser("cancel")
    sub.add_parser("ams")
    sub.add_parser("snapshot")
    p = sub.add_parser("print"); p.add_argument("--confirmed", action="store_true", help="Confirm previewed in Bambu Studio"); p.add_argument("filename")
    p = sub.add_parser("gcode", help="Send raw G-code (local only)"); p.add_argument("code")
    p = sub.add_parser("notify", help="Send notification"); p.add_argument("--title", default="Bambu Studio AI"); p.add_argument("--message", required=True); p.add_argument("--image")
    p = sub.add_parser("light"); p.add_argument("state", choices=["on", "off"])
    p = sub.add_parser("speed"); p.add_argument("mode", choices=["silent", "standard", "sport", "ludicrous"])

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {"progress": cmd_progress, "pause": cmd_pause,
            "resume": cmd_resume, "cancel": cmd_cancel, "ams": cmd_ams, "snapshot": cmd_snapshot}

    if args.command == "status":
        cmd_status(json_output=getattr(args, "json", False))
    elif args.command == "info":
        cmd_info(json_output=getattr(args, "json", False))
    elif args.command == "notify":
        notify(args.title, args.message)
    elif args.command in cmds:
        cmds[args.command]()
    elif args.command == "print":
        cmd_print(args.filename, confirmed=args.confirmed)
    elif args.command == "gcode":
        cmd_gcode(args.code)
    elif args.command == "light":
        cmd_light(args.state)
    elif args.command == "speed":
        cmd_speed(args.mode)

if __name__ == "__main__":
    main()
