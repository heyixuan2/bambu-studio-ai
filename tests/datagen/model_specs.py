"""Regenerate the printer and material tables in ``references/model-specs.md``.

    python3 tests/datagen/model_specs.py            # exit 1 if the tables are out of date
    python3 tests/datagen/model_specs.py --write    # rewrite them from assets/*.json

Only the text between the ``<!-- generated:... -->`` markers is replaced; the prose
around the tables is edited by hand.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):  # run as a script: make the library importable
    sys.path.insert(0, str(ROOT / "scripts"))

from bambu_studio_ai import hardware

MODEL_SPECS = ROOT / "references" / "model-specs.md"
_BLOCK = re.compile(r"(<!-- generated:(\w+) .*?-->\n)(.*?)(<!-- /generated:\2 -->)", re.DOTALL)


def _mm(volume):
    return " × ".join(f"{v:g}" for v in volume)


def _printer_row(p):
    volume = _mm(p.build_volume_mm)
    if p.spec_volume_mm:
        volume += f" (spec {_mm(p.spec_volume_mm)})"
    if p.extruders:
        nozzles = " · ".join(f"{e.name} {_mm(e.volume_mm)}" for e in p.extruders)
        nozzles += f" · both {_mm(p.dual_nozzle_volume_mm)}"
    else:
        nozzles = "one nozzle"
    ams = f"{', '.join(p.ams.types)} (≤ {p.ams.max_slots} slots)"
    nozzle = p.nozzle.replace("_steel", "")
    return (f"| {p.key} | {volume} | {nozzles} | {p.max_nozzle_c} °C | {p.max_bed_c} °C | {p.chamber} "
            f"| {nozzle} | {ams} | {p.status} |")


def printer_table():
    lines = [
        "| Model | Plate W × D × H (mm) | Per nozzle (mm) | Nozzle max | Bed max | Chamber "
        "| Nozzle fitted | AMS | Status |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    lines += [_printer_row(p) for p in hardware.printers().values()]
    return "\n".join(lines) + "\n"


def _printers(material):
    everyone = list(hardware.printers())
    missing = [hardware.printer(k).key for k in everyone if k not in material.printers]
    if not missing:
        return "all"
    if len(missing) <= len(everyone) // 2:
        return "all but " + ", ".join(missing)
    return ", ".join(material.printers)


def _needs(material):
    needs = []
    if material.needs_heated_chamber:
        needs.append("heated chamber")
    elif material.needs_enclosure:
        needs.append("enclosure")
    if material.abrasive:
        needs.append("hardened nozzle")
    if material.soluble:
        needs.append("water-soluble")
    elif material.support:
        needs.append("support only")
    return ", ".join(needs) or "—"


def material_table():
    lines = [
        "| Material | Nozzle | Bed | Chamber | Needs | AMS | Bambu Studio profile for |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in hardware.materials().values():
        chamber = f"{m.chamber_c} °C" if m.chamber_c else "—"
        ams = "yes" if m.ams_compatible else "**no**"
        lines.append(f"| {m.key} | {m.nozzle_c[0]}–{m.nozzle_c[1]} °C | {m.bed_c} °C | {chamber} "
                     f"| {_needs(m)} | {ams} | {_printers(m)} |")
    lines.append("")
    for name, reason in hardware.unsupported_materials().items():
        lines.append(f"- **{name}: not printable.** {reason}")
    return "\n".join(lines) + "\n"


TABLES = {"printers": printer_table, "materials": material_table}


def render(text):
    """``text`` with every generated block replaced by the current table."""
    return _BLOCK.sub(lambda m: m.group(1) + TABLES[m.group(2)]() + m.group(4), text)


def main(argv):
    current = MODEL_SPECS.read_text(encoding="utf-8")
    fresh = render(current)
    if fresh == current:
        print("references/model-specs.md is up to date")
        return 0
    if "--write" in argv:
        MODEL_SPECS.write_text(fresh, encoding="utf-8")
        print("wrote references/model-specs.md")
        return 0
    print("references/model-specs.md is out of date: run python3 tests/datagen/model_specs.py --write")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
