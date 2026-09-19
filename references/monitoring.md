# Print Monitoring

`monitor.py` watches a print and tells the user what matters. It is **read-only**: it reads the
printer's status over the local network (printer IP, serial and access code, see
[setup.md](setup.md#2-printer-status-optional)) and never pauses or changes the print. The
printer stays in its normal mode, so the user can pause or cancel from the printer screen or the
Bambu Handy app at any time.

Always ask before starting the monitor.

## What `monitor.py` does

- Checks the printer every `--interval` seconds (default 120; 300 is plenty for most prints).
- Prints one line per event, flushed immediately, so a background reader sees it at once:
  ```
  📢 NOTIFY: Watching print — cat_figurine · 12% · layer 20/136 · 1 h 40 min left
  📢 NOTIFY: Print progress — cat_figurine · 42% · layer 57/136 · 1 h 11 min left
  📢 NOTIFY: Print paused — Paused on the printer (filament runout, a detected problem, or by hand). …
  📢 NOTIFY: Print finished — cat_figurine is done.
  ```
  With `--json`, each event is one JSON object per line instead:
  `{"kind": "finished", "severity": "info", "title": "Print finished", "message": "…"}`.
- Shows a desktop notification for everything except routine progress (macOS, and Linux with
  `notify-send`), and appends every event to `<output dir>/monitor/events.jsonl`.
- Keeps its state in `~/.bambu-studio-ai/monitor-state.json`, so scheduled `--once` runs carry on
  where the last one stopped.
- Stops when the print ends. If the printer can't be reached it retries, and gives up after 10
  failed checks in a row.

| Event (`kind`) | When | Severity |
|---|---|---|
| `started` | A print is running (or starts, with `--wait-start`) | info |
| `progress` | Every 30 min while printing | info |
| `paused` | The printer paused (runout, detected problem, or by hand) | warning |
| `alert` — printer error | The printer reports an error code | critical |
| `alert` — HMS warning | A new HMS code appears (each code once) | warning |
| `alert` — may be stuck | No new layer and no change in time left for 20 min while printing | warning |
| `alert` — too hot | Nozzle or bed more than 10 °C above the printer's rating | critical |
| `finished` / `failed` / `stopped` | The job ended: done, failed, or cancelled | info / critical / warning |

Calibration before the first layer can take a while; that is not reported as stuck.

## Choose a strategy that fits your environment

**A. Background process (best).** If you can start a long-running command and read its output
later:

```
python3 scripts/monitor.py --wait-start 30 --interval 300
```

`--wait-start 30` handles the usual case where the model was just opened in Bambu Studio and the
user hasn't pressed Print yet: the monitor waits up to 30 minutes for a print to start, then
watches it. Relay each `📢 NOTIFY` line to the user. For a warning or critical event, say what
you'd suggest (check the printer, pause from Bambu Handy, keep watching) and let the user decide.

**B. Scheduled checks.** If your agent can run recurring tasks but not keep a process alive,
schedule `python3 scripts/monitor.py --once` every 5–10 minutes. It keeps state between runs
(what was already announced, the stall timer), so it reports the same way.

**C. On demand.** If neither is available, tell the user you can't watch continuously, then:
- check when asked: `python3 scripts/bambu.py status`
- or suggest they run `python3 scripts/monitor.py --interval 300` in their own terminal. It
  shows desktop notifications, and `monitor.py --status` lists recent events later.

## Status message format

When relaying progress to the user:

```
🖨️ Print update: {file}
{percent}% · layer {current}/{total} · {remaining} left
Nozzle {temp}/{target} °C · Bed {temp}/{target} °C
```

## Printer error and HMS codes

`bambu.py status` shows the printer's error code (8 hex digits, e.g. `0300400C`) and HMS codes
(e.g. `0300_0100_0002_0007`). The printer screen and the Bambu Handy app show the full message
for each code; Bambu's wiki (wiki.bambulab.com) has an HMS page per code. Quote the code to the
user rather than guessing its meaning.

## What monitoring can't do

- **Camera snapshots.** The camera stream needs the printer's LAN-only settings, which this skill
  doesn't ask users to enable. Suggest the Bambu Handy app for a live view.
- **Pausing automatically.** Pausing from third-party software needs LAN Only + Developer Mode.
  The monitor alerts; the user pauses from the printer or Bambu Handy.
