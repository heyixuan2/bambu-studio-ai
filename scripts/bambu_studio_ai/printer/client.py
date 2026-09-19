"""Read one full status report from a printer over its local MQTT broker.

Every Bambu Lab printer runs an MQTT broker on port 8883 that accepts the user
``bblp`` with the LAN access code shown on the printer's screen. Subscribing to the
report topic and asking for a full push ("pushall") is read-only and works in the
printer's normal cloud mode; LAN Only Mode and Developer Mode are not needed.
"""

from __future__ import annotations

import json
import ssl
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from paho.mqtt.client import Client, ConnectFlags, MQTTMessage
    from paho.mqtt.properties import Properties
    from paho.mqtt.reasoncodes import ReasonCode

MQTT_PORT = 8883
MQTT_USER = "bblp"
DEFAULT_TIMEOUT_S = 20.0

# A full report (the answer to "pushall") carries these; incremental pushes from
# P1/A1 printers may carry only the fields that changed.
_FULL_REPORT_KEYS = ("gcode_state", "mc_percent")


class PrinterConnectionError(RuntimeError):
    """The printer could not be reached or sent no full report in time."""


class PrinterAuthError(PrinterConnectionError):
    """The printer rejected the access code or serial number."""


@dataclass(frozen=True)
class PrinterSettings:
    """What is needed to reach a printer on the local network."""

    ip: str
    serial: str
    access_code: str

    def missing(self) -> list[str]:
        """Names of the config keys that are still empty."""
        fields = {"printer_ip": self.ip, "serial": self.serial, "access_code": self.access_code}
        return [name for name, value in fields.items() if not value]


class ReportCollector:
    """MQTT callbacks that gather one full ``print`` report.

    Kept separate from the network code so it can be tested with plain dicts.
    """

    def __init__(self, serial: str) -> None:
        """Collect reports published by the printer with this serial number."""
        self.report_topic = f"device/{serial}/report"
        self.request_topic = f"device/{serial}/request"
        self.report: dict[str, Any] = {}
        self.error: PrinterConnectionError | None = None
        self.done = threading.Event()

    def on_connect(
        self,
        client: Client,
        _userdata: object,
        _flags: ConnectFlags,
        reason_code: ReasonCode,
        _properties: Properties | None,
    ) -> None:
        """Subscribe and request a full report, or record why the broker refused us."""
        if reason_code.is_failure:
            self.error = PrinterAuthError(f"printer refused the connection: {reason_code}")
            self.done.set()
            return
        client.subscribe(self.report_topic)
        request = {"pushing": {"sequence_id": "0", "command": "pushall"}}
        client.publish(self.request_topic, json.dumps(request))

    def on_message(self, _client: Client, _userdata: object, message: MQTTMessage) -> None:
        """Merge the ``print`` section of each report until a full one has arrived."""
        self.feed(message.payload)

    def feed(self, payload: bytes) -> None:
        """Process one raw MQTT payload."""
        try:
            document: object = json.loads(payload)
        except ValueError:
            return
        if not isinstance(document, dict):
            return
        section: object = cast("dict[str, object]", document).get("print")
        if isinstance(section, dict):
            self.report.update(cast("dict[str, Any]", section))
            if all(key in self.report for key in _FULL_REPORT_KEYS):
                self.done.set()


def read_report(settings: PrinterSettings, timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Connect, wait for one full report, disconnect, and return its ``print`` section.

    Raises:
        PrinterAuthError: the access code or serial number was rejected.
        PrinterConnectionError: no full report arrived within ``timeout`` seconds.
    """
    # Imported here so the rest of the skill works without paho-mqtt installed.
    from paho.mqtt.client import Client, MQTTv311  # noqa: PLC0415
    from paho.mqtt.enums import CallbackAPIVersion  # noqa: PLC0415

    collector = ReportCollector(settings.serial)
    client = Client(CallbackAPIVersion.VERSION2, protocol=MQTTv311)
    client.username_pw_set(MQTT_USER, settings.access_code)
    # The printer presents a certificate signed by Bambu's own CA for its serial
    # number, not its IP, so hostname checks can't pass on a LAN address.
    tls = ssl.create_default_context()
    tls.check_hostname = False
    tls.verify_mode = ssl.CERT_NONE
    client.tls_set_context(tls)  # pyright: ignore[reportUnknownMemberType]  (paho leaves it unannotated)
    client.on_connect = collector.on_connect
    client.on_message = collector.on_message

    client.connect_async(settings.ip, MQTT_PORT, keepalive=60)
    client.loop_start()
    try:
        arrived = collector.done.wait(timeout)
    finally:
        client.disconnect()
        client.loop_stop()

    if collector.error:
        raise collector.error
    if not arrived:
        raise PrinterConnectionError(
            f"no report from {settings.ip} within {timeout:.0f} s "
            "(is the printer on and on this network, and are the IP and serial number right?)"
        )
    return collector.report
