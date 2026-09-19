# Bambu Lab Model Specifications

| Model | Volume (mm³) | Speed | Nozzle Max | Bed Max | Extruders | Enclosure | AMS |
|-------|-------------|-------|------------|---------|-----------|-----------|-----|
| A1 Mini | 180×180×180 | 500mm/s | 300°C | 80°C | 1 | Open | AMS Lite |
| A1 | 256×256×256 | 500mm/s | 300°C | 100°C | 1 | Open | AMS Lite |
| P1S | 256×256×256 | 500mm/s | 300°C | 100°C | 1 | Enclosed | AMS |
| P2S | 256×256×256 | 600mm/s | 300°C | 110°C | 1 | Enclosed | AMS 2 Pro |
| X1C | 256×256×256 | 500mm/s | 300°C | 110°C | 1 | Enclosed | AMS |
| X1E | 256×256×256 | 500mm/s | 300°C | 110°C | 1 | Full Enclosed | AMS |
| H2C | 256×256×256 | 600mm/s | 350°C | 120°C | 1 | 65°C Heated | AMS 2 Pro |
| H2S | 340×320×340 | 1000mm/s | 300°C | 110°C | 1 | Enclosed | AMS 2 Pro |
| H2D | 350×320×325 | 600mm/s | 350°C | 120°C | 2 | Enclosed | AMS 2 Pro |
| X2D | 256×256×260 | 1000mm/s | 300°C | 120°C | 2 | 65°C Heated | AMS 2 Pro |

Source: bambulab.com/en-us/compare (March 2026)

The scripts apply a ~10% safety margin to these volumes when scaling and checking fit
(`BUILD_VOLUMES` in `scripts/common.py`).

## Materials

| Material | Nozzle | Bed | Enclosure | Min wall | Best for |
|----------|--------|-----|-----------|----------|----------|
| PLA / PLA+ | 190–230 °C | 60 °C | Open | 1.2 mm | General purpose, decorative |
| PETG | 220–250 °C | 80 °C | Open | 1.2 mm | Strength, water resistance |
| TPU | 210–240 °C | 50 °C | Open | 1.6 mm | Flexible parts, phone cases |
| ABS / ASA | 230–260 °C | 100 °C | Required | 1.2 mm | Heat resistance, outdoor (ASA) |
| PA (Nylon) | 250–280 °C | 80 °C | Required | 1.5 mm | Mechanical parts, wear |
| PC | 260–300 °C | 100 °C | Required | 1.5 mm | Toughness, heat |
| PEEK | 330–350 °C | 120 °C | H2C / H2D only | 2.0 mm | Engineering, high temperature |

Enclosed printers: P1S, P2S, X1C, X1E, X2D, H2C, H2S, H2D. The A1 and A1 Mini are open-frame, so
avoid ABS/ASA/PA/PC on them. `analyze.py --material X` checks this for the configured printer.
