"""Load Bambu Studio's system profiles and flatten their inheritance chains.

A vendor bundle is a directory holding ``BBL.json`` (the index: every machine, process
and filament preset by name, with its file) and ``BBL/`` (the preset files). A preset
names its parent in ``inherits`` and may pull G-code templates in with ``include``.

The command-line slicer does not resolve either: given a bare leaf preset it silently
falls back to built-in defaults (a 200 x 200 mm bed, zero filament density). Every
preset handed to it must therefore be flattened into one full config first.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

#: A preset as JSON: values are strings or lists of strings, passed through verbatim.
Profile = Mapping[str, object]

#: Preset kinds, plus ``machine_model``: one file per printer family with facts that
#: aren't in any preset, such as the build plate it ships with (``default_bed_type``).
KINDS = ("machine_model", "machine", "process", "filament")
_INDEX_LISTS = {
    "machine_model": "machine_model_list",
    "machine": "machine_list",
    "process": "process_list",
    "filament": "filament_list",
}

#: Identity of a preset. Bambu Studio reads these from the preset's own file only, and
#: the slicer checks ``compatible_printers`` against ``name``, so a parent's or a
#: template's values must never leak into a leaf.
LEAF_ONLY_KEYS = frozenset({"name", "setting_id", "instantiation", "from", "type"})

#: Links that flattening resolves; a flattened preset has no parent or includes.
LINK_KEYS = frozenset({"inherits", "include"})

# Bambu Studio takes a filament's ``filament_id`` from the preset or its parent, never
# from an included template (PresetBundle.cpp, load_vendor_configs_from_json).
_NOT_FROM_INCLUDES = LEAF_ONLY_KEYS | LINK_KEYS | {"filament_id"}


class ProfileError(RuntimeError):
    """The profile bundle is missing, unreadable or internally inconsistent."""


def text(profile: Profile, key: str) -> str:
    """Return a string setting, the first entry of a list setting, or ``""``."""
    value = profile.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        first = cast("list[object]", value)[0]
        return first if isinstance(first, str) else ""
    return ""


def strings(profile: Profile, key: str) -> list[str]:
    """Return a list-of-strings setting (a lone string becomes a one-item list)."""
    value = profile.get(key)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in cast("list[object]", value) if isinstance(item, str)]
    return []


def number(profile: Profile, key: str) -> float | None:
    """Return a numeric setting stored as text (``"0.2"``), or ``None``."""
    try:
        return float(text(profile, key))
    except ValueError:
        return None


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        document: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProfileError(f"cannot read profile file {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ProfileError(f"{path} is not a JSON object")
    return cast("dict[str, object]", document)


class ProfileLibrary:
    """The system presets of one vendor bundle, looked up by preset name."""

    def __init__(self, root: Path, vendor: str = "BBL") -> None:
        """Index the bundle in ``root`` (the directory that holds ``<vendor>.json``).

        Raises:
            ProfileError: the index is missing or unreadable.
        """
        self.root = root
        self.vendor_dir = root / vendor
        index = _read_json_object(root / f"{vendor}.json")
        version = index.get("version")
        self.version = version if isinstance(version, str) else ""
        self._paths: dict[str, dict[str, Path]] = {kind: {} for kind in KINDS}
        for kind, list_key in _INDEX_LISTS.items():
            entries = index.get(list_key)
            if not isinstance(entries, list):
                continue
            for entry in cast("list[object]", entries):
                if not isinstance(entry, dict):
                    continue
                item = cast("dict[str, object]", entry)
                name, sub_path = item.get("name"), item.get("sub_path")
                if isinstance(name, str) and isinstance(sub_path, str):
                    self._paths[kind][name] = self.vendor_dir / sub_path
        self._raw: dict[tuple[str, str], dict[str, object]] = {}
        self._flat: dict[tuple[str, str], dict[str, object]] = {}

    def names(self, kind: str) -> list[str]:
        """Names of every preset of this kind, including abstract parents and templates."""
        return sorted(self._paths[kind])

    def has(self, kind: str, name: str) -> bool:
        """Whether the bundle has a preset of this kind with this name."""
        return name in self._paths[kind]

    def raw(self, kind: str, name: str) -> Profile:
        """The preset exactly as stored in its file.

        Raises:
            ProfileError: no such preset, or its file is outside the bundle or unreadable.
        """
        key = (kind, name)
        if key not in self._raw:
            path = self._paths[kind].get(name)
            if path is None:
                raise ProfileError(f"no {kind} profile named {name!r} in {self.root}")
            # The index is data from disk; don't follow it out of the bundle.
            if not path.resolve().is_relative_to(self.vendor_dir.resolve()):
                raise ProfileError(f"{kind} profile {name!r} points outside {self.vendor_dir}")
            self._raw[key] = _read_json_object(path)
        return self._raw[key]

    def flatten(self, kind: str, name: str) -> dict[str, object]:
        """The preset as one full config: parent chain, then includes, then its own keys.

        This is the order Bambu Studio itself uses when it loads system presets. One
        difference: it applies only the template keys that differ from its built-in
        defaults, which it doesn't publish; the shipped templates set G-code and
        per-extruder values that differ anyway. Values, G-code included, are copied
        verbatim.

        Raises:
            ProfileError: a parent or include is missing, or the chain has a cycle.
        """
        return dict(self._flatten(kind, name, ()))

    def instances(self, kind: str) -> list[tuple[str, Profile]]:
        """Flattened presets that users can select (``instantiation`` is ``"true"``)."""
        return [
            (name, self._flatten(kind, name, ()))
            for name in self.names(kind)
            if text(self.raw(kind, name), "instantiation") == "true"
        ]

    def _flatten(self, kind: str, name: str, chain: tuple[str, ...]) -> dict[str, object]:
        key = (kind, name)
        if key in self._flat:
            return self._flat[key]
        if name in chain:
            raise ProfileError(f"{kind} profile inheritance loops: {' -> '.join((*chain, name))}")
        own = self.raw(kind, name)
        chain = (*chain, name)
        merged: dict[str, object] = {}
        parent = text(own, "inherits")
        if parent:
            merged.update(
                (k, v)
                for k, v in self._flatten(kind, parent, chain).items()
                if k not in LEAF_ONLY_KEYS
            )
        for include in strings(own, "include"):
            merged.update(
                (k, v)
                for k, v in self._flatten(kind, include, chain).items()
                if k not in _NOT_FROM_INCLUDES
            )
        merged.update((k, v) for k, v in own.items() if k not in LINK_KEYS)
        self._flat[key] = merged
        return merged
