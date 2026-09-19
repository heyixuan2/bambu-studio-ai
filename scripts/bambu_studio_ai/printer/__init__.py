"""Read-only access to a Bambu Lab printer over local MQTT.

Works while the printer stays in normal cloud mode: it only needs the printer's IP,
serial number and LAN access code, and it never sends commands, so the Bambu Handy
app and Bambu Studio keep working. Starting, pausing or changing a print is left to
Bambu Studio and the Handy app.
"""

from bambu_studio_ai.printer.client import (
    PrinterAuthError,
    PrinterConnectionError,
    PrinterSettings,
    read_report,
)
from bambu_studio_ai.printer.report import PrinterStatus, Tray, parse_status

__all__ = [
    "PrinterAuthError",
    "PrinterConnectionError",
    "PrinterSettings",
    "PrinterStatus",
    "Tray",
    "parse_status",
    "read_report",
]
