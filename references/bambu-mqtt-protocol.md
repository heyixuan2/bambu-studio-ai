# Bambu Lab MQTT Protocol Reference

## Connection
- Host: printer IP (LAN) or Bambu Cloud broker
- Port: 8883 (TLS)
- Username: `bblp`
- Password: LAN Access Code

## Topics

### Status Reports (Printer → Client)
```
device/{serial}/report
```
JSON payload with print state, temperatures, progress, AMS info.

### Commands (Client → Printer)
```
device/{serial}/request
```

## Key Report Fields
| Field | Type | Description |
|-------|------|-------------|
| `print.gcode_state` | string | IDLE / RUNNING / PAUSE / FINISH / FAILED |
| `print.mc_percent` | int | Progress 0-100 |
| `print.mc_remaining_time` | int | Minutes remaining |
| `print.nozzle_temper` | float | Current nozzle temp (°C) |
| `print.nozzle_target_temper` | float | Target nozzle temp |
| `print.bed_temper` | float | Current bed temp |
| `print.bed_target_temper` | float | Target bed temp |
| `print.subtask_name` | string | Current file name |
| `print.layer_num` | int | Current layer |
| `print.total_layer_num` | int | Total layers |
| `print.fan_gear` | int | Fan speed level |
| `print.spd_lvl` | int | Speed level (1-4) |
| `print.lights_report` | array | LED state |
| `print.ams` | object | AMS slot info |

## Command Payloads

### Print Control
```json
{"print": {"command": "pause"}}
{"print": {"command": "resume"}}
{"print": {"command": "stop"}}
```

### Speed
```json
{"print": {"command": "print_speed", "param": "2"}}
```
Values: 1=Silent, 2=Standard, 3=Sport, 4=Ludicrous

### G-code
```json
{"print": {"command": "gcode_line", "param": "G28\n"}}
```

### Light
```json
{"system": {"led_mode": "on"}}
{"system": {"led_mode": "off"}}
```

### Temperature
```json
{"print": {"command": "gcode_line", "param": "M104 S200\n"}}
{"print": {"command": "gcode_line", "param": "M140 S60\n"}}
```

## Camera
- RTSP stream: `rtsps://bblp:{access_code}@{ip}:322/streaming/live/1`
- Requires ffmpeg for snapshot capture

## Sources
- https://github.com/coelacant1/Bambu-Lab-Cloud-API
- https://github.com/greghesp/pybambu
