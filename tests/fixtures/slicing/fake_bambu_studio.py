"""Stand-in for the Bambu Studio command line, for tests that must not need the app.

Behaves like BambuStudio 02.07.01.62 for the options slice.py uses: writes result.json
and the exported 3MF (with plate G-code) into --outputdir. FAKE_BS_MODE picks an
outcome; FAKE_BS_RECORD names a file that receives the argv, cwd and loaded settings.
"""

import json
import os
import sys
import time
import zipfile
from pathlib import Path

HEADER = """; HEADER_BLOCK_START
; BambuStudio 02.07.01.62
; model printing time: 5m 0s; total estimated time: 10m 0s
; total filament weight [g] : 2.50
; HEADER_BLOCK_END

; CONFIG_BLOCK_START
; filament_ids = GFA00
; CONFIG_BLOCK_END
"""


def option(name):
    return sys.argv[sys.argv.index(name) + 1]


def main():
    mode = os.environ.get("FAKE_BS_MODE", "ok")
    outdir = Path(option("--outputdir"))
    settings = option("--load-settings").split(";")
    record = os.environ.get("FAKE_BS_RECORD")
    if record:
        Path(record).write_text(json.dumps({
            "argv": sys.argv[1:],
            "cwd": os.getcwd(),
            "settings": [json.loads(Path(p).read_text(encoding="utf-8")) for p in settings],
            "filaments": [json.loads(Path(p).read_text(encoding="utf-8"))
                          for p in option("--load-filaments").split(";")],
        }), encoding="utf-8")
    if mode == "hang":
        time.sleep(30)
    if mode == "fail":
        result = {"return_code": -61, "error_string": "Filaments are not compatible with the plate type."}
        (outdir / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return 195  # -61 as an unsigned exit status
    if mode != "no_result":
        plate = {"id": 1, "total_predication": 600.5, "main_predication": 300.0, "warning_message": "",
                 "filaments": [{"id": 1, "filament_id": "GFA00", "total_used_g": 2.5, "main_used_g": 2.5}]}
        result = {"return_code": 0, "error_string": "Success.", "sliced_plates": [plate]}
        (outdir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    if mode != "no_3mf":
        with zipfile.ZipFile(outdir / option("--export-3mf"), "w") as archive:
            archive.writestr("Metadata/plate_1.gcode", HEADER + "G28\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
