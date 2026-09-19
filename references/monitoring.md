# Print Monitoring

Monitoring needs **LAN mode** (MQTT on port 8883, camera over RTSP on port 322 via ffmpeg).
Always ask before starting it, and ask separately before enabling `--auto-pause`.

## What `monitor.py` does

- Polls printer status every `--interval` seconds (default 120; 300 is plenty for most prints).
- Takes a camera snapshot each cycle: `<output dir>/snapshots/snap_<time>.jpg`.
- Prints one line per event, line-buffered, so a background reader sees it immediately:
  ```
  📢 NOTIFY: Print Progress — 📊 Progress: 42% | Remaining: 1h 10m | 🔥 Nozzle: 220°C | 🛏️ Bed: 60°C
  📢 NOTIFY: Print Alert 🚨 — ⚠️ Progress stalled: 42% ... [snapshot: /path/snap_….jpg]
  📢 NOTIFY: Print Complete ✅ — Print finished!
  ```
- Also shows a desktop notification (macOS, and Linux with `notify-send`), and appends to
  `snapshots/monitor-log.json`. State lives in `snapshots/monitor-state.json`, so `--once` runs
  carry on where the last one stopped.
- Exits when the print finishes, or after 5 consecutive failed status checks.

| Event | When | Severity |
|---|---|---|
| Print started | Printing detected (with `--wait-start`) | info |
| Progress report | Every 30 min | info |
| Progress stalled | No progress change for 10+ min | warning |
| Unexpected pause | Printer paused, not by the monitor | warning |
| Temperature anomaly | Nozzle above the printer's rated max (300 °C; 350 °C on H2C/H2D), bed above 120 °C | critical |
| Print complete | Printer went idle after printing | info |

With `--auto-pause`, critical alerts pause the print automatically.

## Choose a strategy that fits your environment

**A. Background process (best).** If you can start a long-running command and read its output
later:

```
python3 scripts/monitor.py --wait-start 30 --interval 300 [--auto-pause]
```

`--wait-start 30` handles the usual case where the model was just opened in Bambu Studio and the
user hasn't pressed Print yet. The monitor waits up to 30 minutes for a print to start, then
monitors it. Relay each `📢 NOTIFY` line to the user with the latest snapshot. For alerts,
include the snapshot and what you recommend (pause, keep watching, cancel).

**B. Scheduled checks.** If your agent can run recurring tasks but not keep a process alive,
schedule `python3 scripts/monitor.py --once` every 5–10 minutes. It keeps state between runs
(milestones, stall timer), so it reports the same way.

**C. On demand.** If neither is available, tell the user you can't watch continuously, then:
- check when asked: `python3 scripts/bambu.py progress` and `python3 scripts/bambu.py snapshot`
- or suggest they run `python3 scripts/monitor.py --interval 300` in their own terminal. It
  shows desktop notifications, and `monitor.py --status` summarizes the log later.

## Status message format

When relaying progress to the user:

```
🖨️ Print update: {file}
📊 {percent}% · layer {current}/{total} · {remaining} left
🔥 Nozzle {temp}°C · 🛏️ Bed {temp}°C
📸 [latest snapshot]
```

If you can look at images, glance at the snapshot too. Visible spaghetti, a part knocked off the
bed or a layer shift are worth an immediate alert even if the numbers look fine. Recommend a
pause and let the user decide, unless they enabled auto-pause.

## Camera notes

- Only one client can use the camera stream at a time. Close camera views in Bambu Studio or
  Handy if snapshots time out.
- A sleeping printer doesn't stream. Waking it (tap the screen) helps.
- Snapshots aren't available in cloud mode.
