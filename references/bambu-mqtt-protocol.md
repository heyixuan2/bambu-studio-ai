# Bambu Lab local MQTT: what this skill reads

For debugging `bambu.py status` and `monitor.py`. The skill only **reads**; it never publishes
commands other than asking for a full status report.

## Connection

| | |
|---|---|
| Host | the printer's IP address on the local network |
| Port | 8883, TLS (the printer's certificate is signed by Bambu's own CA for its serial number, so hostname checks are off) |
| Username | `bblp` |
| Password | the LAN access code from the printer screen (Settings → Network) |
| Subscribe | `device/{serial}/report` |
| On connect | publish `{"pushing": {"sequence_id": "0", "command": "pushall"}}` to `device/{serial}/request` to get a full report (don't repeat this more than every few minutes; P1/A1 printers answer slowly) |

This works while the printer is in its normal cloud mode, as in Home Assistant's Bambu Lab
integration. Since Bambu's January 2025 authorization-control firmware, commands that change what
the printer does (start, pause, stop, G-code, temperatures, light, speed) are only accepted from
third-party software when the printer is in LAN Only Mode with Developer Mode on. Reading is not
affected.

A wrong access code shows up as a refused connection ("Not authorized"). A wrong serial number
connects but no reports arrive, which looks like a timeout.

## Report fields used (`print.*`)

| Field | Type | Meaning |
|---|---|---|
| `gcode_state` | string | `IDLE`, `PREPARE`, `SLICING`, `RUNNING`, `PAUSE`, `FINISH`, `FAILED` |
| `mc_percent` | int | Progress, 0–100 |
| `mc_remaining_time` | int | Minutes left |
| `layer_num`, `total_layer_num` | int | Current and total layers |
| `subtask_name`, `gcode_file` | string | Job name, file path on the printer |
| `nozzle_temper`, `nozzle_target_temper` | float | °C |
| `bed_temper`, `bed_target_temper` | float | °C |
| `chamber_temper` | float | °C (models with a chamber sensor) |
| `spd_lvl` | int | 1 silent, 2 standard, 3 sport, 4 ludicrous |
| `lights_report` | list | `[{"node": "chamber_light", "mode": "on"\|"off"\|"flashing"}]` |
| `print_error` | int | 0, or an error code; shown as 8 hex digits (e.g. `0300400C`) |
| `hms` | list | `[{"attr": int, "code": int}]`; shown as `AAAA_AAAA_CCCC_CCCC` hex |
| `ams.tray_now` | string | Slot being fed: AMS unit × 4 + slot, `254` external spool, `255` none |
| `ams.ams[].tray[]` | list | Per slot: `tray_type`, `tray_sub_brands`, `tray_color` (`RRGGBBAA`), `remain` (%, −1 unknown), `tray_info_idx` |
| `vt_tray` | object | The external spool, same fields as a tray |

P1 and A1 printers send only the fields that changed between full reports, so the client merges
reports and waits until `gcode_state` and `mc_percent` have both arrived. Fields a model doesn't
have are simply absent.

## Sources

- OpenBambuAPI (protocol documentation): https://github.com/Doridian/OpenBambuAPI/blob/main/mqtt.md
- Bambu Lab, third-party integration and Developer Mode: https://wiki.bambulab.com/en/software/third-party-integration
- Bambu Lab blog, 2025-01-20: https://blog.bambulab.com/updates-and-third-party-integration-with-bambu-connect/
