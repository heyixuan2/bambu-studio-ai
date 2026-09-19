"""Typed accessors for JSON data files shipped with the skill.

``json.load`` returns untyped values; these helpers check each field once, at the
boundary, and raise :class:`DataFileError` naming the file and field when the data
is not what the code expects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

#: Folder of data files that ship with the skill (``<skill>/assets``). Found relative to
#: this package, never the working directory, so scripts work when called from anywhere.
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"


class DataFileError(ValueError):
    """A data file in ``assets/`` is missing or malformed."""


JsonObject = dict[str, object]


def load_asset(name: str) -> JsonObject:
    """Read ``assets/<name>`` as a JSON object."""
    path = ASSETS_DIR / name
    try:
        with path.open(encoding="utf-8") as f:
            data: object = json.load(f)
    except (OSError, ValueError) as e:
        raise DataFileError(f"Cannot read {path}: {e}") from e
    return obj(data, name)


def obj(value: object, where: str) -> JsonObject:
    """``value`` as a JSON object."""
    if not isinstance(value, dict):
        raise DataFileError(f"{where}: expected an object")
    return cast("JsonObject", value)


def items(value: object, where: str) -> list[object]:
    """``value`` as a JSON array."""
    if not isinstance(value, list):
        raise DataFileError(f"{where}: expected an array")
    return cast("list[object]", value)


def field(data: JsonObject, key: str, where: str) -> object:
    """``data[key]``, which must be present."""
    if key not in data:
        raise DataFileError(f"{where}: missing {key!r}")
    return data[key]


def text(data: JsonObject, key: str, where: str) -> str:
    """A string field."""
    value = field(data, key, where)
    if not isinstance(value, str):
        raise DataFileError(f"{where}.{key}: expected a string")
    return value


def flag(data: JsonObject, key: str, where: str) -> bool:
    """A boolean field."""
    value = field(data, key, where)
    if not isinstance(value, bool):
        raise DataFileError(f"{where}.{key}: expected true or false")
    return value


def number(value: object, where: str) -> float:
    """``value`` as a number (booleans rejected)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataFileError(f"{where}: expected a number")
    return float(value)


def integer(data: JsonObject, key: str, where: str) -> int:
    """An integer field."""
    value = field(data, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataFileError(f"{where}.{key}: expected an integer")
    return value


def optional_integer(data: JsonObject, key: str, where: str) -> int | None:
    """An integer field that may be absent or null."""
    if data.get(key) is None:
        return None
    return integer(data, key, where)


def texts(data: JsonObject, key: str, where: str) -> tuple[str, ...]:
    """An array-of-strings field (absent means empty)."""
    values = items(data.get(key, []), f"{where}.{key}")
    if not all(isinstance(v, str) for v in values):
        raise DataFileError(f"{where}.{key}: expected strings")
    return tuple(cast("list[str]", values))


def numbers(data: JsonObject, key: str, where: str, count: int) -> tuple[float, ...]:
    """An array of exactly ``count`` numbers."""
    values = items(field(data, key, where), f"{where}.{key}")
    if len(values) != count:
        raise DataFileError(f"{where}.{key}: expected {count} numbers")
    return tuple(number(v, f"{where}.{key}") for v in values)
