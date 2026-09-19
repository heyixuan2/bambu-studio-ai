"""Bambu Lab's official filament colours, from the table Bambu Studio ships.

The data lives in ``assets/filaments.json`` (see its ``about`` field for how it is made).
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

from bambu_studio_ai import _json

#: Finishes that read as a plain solid colour, so they may stand in for an opaque region.
#: Silk, translucent, glow and the rest change how a colour looks and are only offered
#: when asked for.
PLAIN_FINISHES = frozenset({"opaque", "matte"})

_HEX = re.compile(r"^#[0-9A-F]{6}$")


@dataclass(frozen=True)
class FilamentColor:
    """One colour of one Bambu Lab filament product line."""

    line: str
    """Product line, e.g. ``"PLA Basic"``."""
    name: str
    hex: str
    """``#RRGGBB``; the first colour for gradient and multicolour spools."""
    hexes: tuple[str, ...]
    """Every colour of the spool (one entry for solid spools)."""
    finish: str
    """``opaque``, ``matte``, ``silk``, ``translucent``, ... (the file's ``finishes``)."""
    pattern: str
    """``solid``, ``gradient`` or ``multicolor``."""
    code: str
    """Bambu's colour code: the five digits in the product SKU."""
    material: str
    """Bambu Studio filament type of the line, e.g. ``"PLA"``."""
    filament_id: str
    support: bool
    """Whether the line is a support material."""

    @property
    def plain(self) -> bool:
        """A single solid colour with a plain finish: safe to suggest for an opaque region."""
        return self.pattern == "solid" and self.finish in PLAIN_FINISHES


@functools.cache
def filament_colors() -> tuple[FilamentColor, ...]:
    """Every colour in the table, in Bambu Studio's order."""
    data = _json.load_asset("filaments.json")
    lines = _json.obj(_json.field(data, "lines", "filaments.json"), "lines")
    colors: list[FilamentColor] = []
    for i, raw in enumerate(_json.items(_json.field(data, "colors", "filaments.json"), "colors")):
        where = f"colors[{i}]"
        entry = _json.obj(raw, where)
        line_name = _json.text(entry, "line", where)
        line = _json.obj(_json.field(lines, line_name, "lines"), line_name)
        hex_value = _json.text(entry, "hex", where)
        hexes = _json.texts(entry, "hexes", where) or (hex_value,)
        if not all(_HEX.match(h) for h in hexes) or hexes[0] != hex_value:
            raise _json.DataFileError(
                f"{where}: colours must be #RRGGBB and hex the first of hexes"
            )
        colors.append(
            FilamentColor(
                line=line_name,
                name=_json.text(entry, "name", where),
                hex=hex_value,
                hexes=hexes,
                finish=_json.text(entry, "finish", where),
                pattern=_json.text(entry, "pattern", where),
                code=_json.text(entry, "code", where),
                material=_json.text(line, "material", line_name),
                filament_id=_json.text(line, "filament_id", line_name),
                support=_json.flag(line, "support", line_name),
            )
        )
    return tuple(colors)
