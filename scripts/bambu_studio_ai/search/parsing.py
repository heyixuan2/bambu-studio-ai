"""Small, forgiving readers for JSON from sites whose schema we don't control.

A missing or oddly-typed field becomes an empty value instead of an exception, so one
malformed hit costs one result, not the whole search.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import cast
from urllib.parse import quote

_WHITESPACE = re.compile(r"\s+")


def mapping(value: object) -> Mapping[str, object]:
    """``value`` if it is a JSON object, else an empty one."""
    return cast("Mapping[str, object]", value) if isinstance(value, dict) else {}


def mappings(value: object) -> list[Mapping[str, object]]:
    """The JSON objects in ``value`` if it is a list, skipping anything else."""
    if not isinstance(value, list):
        return []
    items = cast("list[object]", value)
    return [cast("Mapping[str, object]", item) for item in items if isinstance(item, dict)]


def count(value: object) -> int | None:
    """A non-negative integer count, or ``None`` when absent or not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = int(value)
    except (ValueError, OverflowError):
        return None
    return number if number >= 0 else None


def text(value: object) -> str:
    """Single-line text: whitespace collapsed, control characters removed.

    Titles and names are written by site users and end up in a terminal, so escape
    sequences must not survive. Anything that isn't a string becomes empty.
    """
    if not isinstance(value, str):
        return ""
    collapsed = _WHITESPACE.sub(" ", value).strip()
    return "".join(char for char in collapsed if unicodedata.category(char) != "Cc")


def model_id(value: object) -> str:
    """A site's numeric model id as text, or empty if it isn't one."""
    raw = str(value) if isinstance(value, (int, str)) and not isinstance(value, bool) else ""
    return raw if raw.isascii() and raw.isdigit() else ""


def page_url(base: str, identifier: str, slug: object) -> str:
    """``<base><id>-<slug>``, the public page URL form both sites use."""
    cleaned = quote(text(slug), safe="-_.~")
    return f"{base}{identifier}-{cleaned}" if cleaned else f"{base}{identifier}"


def utc_timestamp(value: object) -> str:
    """An ISO 8601 time as ``YYYY-MM-DDTHH:MM:SSZ`` in UTC, or empty if unparseable.

    Normalising lets results from both sites be sorted by publication time as strings.
    """
    raw = text(value)
    if not raw:
        return ""
    # Python 3.10's fromisoformat() rejects a trailing "Z".
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
