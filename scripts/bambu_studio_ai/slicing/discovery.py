r"""Find the Bambu Studio command line and the printer profiles it ships with.

Tested only on macOS (Bambu Studio 02.07.01.62 in /Applications). The Windows and Linux
locations follow the installers' layouts and user reports and have not been run:

* Windows: the installer puts ``bambu-studio.exe`` and ``resources\profiles`` in
  ``%ProgramFiles%\Bambu Studio`` (bambulab/BambuStudio#12068). Issue #9802 (open,
  v02.05.00.66) reports the Windows CLI printing nothing, so it may not work there.
* Linux: a ``bambu-studio`` on PATH (distribution packages), an AppImage in
  ``~/Applications`` or ``~/.local/bin``, or the Flatpak ``com.bambulab.BambuStudio``.
  An AppImage keeps its profiles inside the image, so they are read from the copy
  Bambu Studio makes in ``~/.config/BambuStudio/system`` on its first start.

``BAMBU_STUDIO_CLI`` (an executable) and ``BAMBU_STUDIO_PROFILES`` (a directory holding
``BBL.json``) override the search.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

CLI_ENV = "BAMBU_STUDIO_CLI"
PROFILES_ENV = "BAMBU_STUDIO_PROFILES"
VENDOR = "BBL"
FLATPAK_ID = "com.bambulab.BambuStudio"
_MAC_APP = "BambuStudio.app"


@dataclass(frozen=True)
class Host:
    """The facts discovery depends on, so tests can describe any machine."""

    system: str
    """``platform.system()``: ``"Darwin"``, ``"Windows"`` or ``"Linux"``."""
    home: Path
    env: Mapping[str, str] = field(default_factory=dict[str, str])

    @classmethod
    def current(cls) -> Host:
        """The machine this code runs on."""
        return cls(system=platform.system(), home=Path.home(), env=dict(os.environ))


def cli_candidates(host: Host) -> list[tuple[str, ...]]:
    """Commands that may run the Bambu Studio command line, most likely first."""
    if host.system == "Darwin":
        return [
            (str(base / _MAC_APP / "Contents" / "MacOS" / "BambuStudio"),)
            for base in (Path("/Applications"), host.home / "Applications")
        ]
    if host.system == "Windows":
        program_files = Path(host.env.get("PROGRAMFILES", r"C:\Program Files"))
        exe = program_files / "Bambu Studio" / "bambu-studio.exe"
        found = shutil.which("bambu-studio")
        return [(str(exe),)] + ([(found,)] if found else [])
    commands: list[tuple[str, ...]] = [
        (found,) for name in ("bambu-studio", "BambuStudio") if (found := shutil.which(name))
    ]
    for folder in (host.home / "Applications", host.home / ".local" / "bin"):
        commands += [(str(image),) for image in sorted(folder.glob("Bambu*Studio*.AppImage"))]
    if shutil.which("flatpak") and any(root.is_dir() for root in _flatpak_roots(host)):
        commands.append(("flatpak", "run", FLATPAK_ID))
    return commands


def profile_candidates(host: Host, cli: Sequence[str] | None = None) -> list[Path]:
    """Directories that may hold ``BBL.json``, most likely first.

    The first candidate is the bundle next to ``cli``, found the way Bambu Studio finds
    its own resources.
    """
    candidates: list[Path] = []
    if cli and len(cli) == 1:
        executable = Path(cli[0]).resolve()
        if host.system == "Darwin":
            candidates.append(executable.parent.parent / "Resources" / "profiles")
        elif host.system == "Windows":
            candidates.append(executable.parent / "resources" / "profiles")
        else:
            candidates.append(executable.parent.parent / "resources" / "profiles")
    if host.system == "Darwin":
        candidates += [
            base / _MAC_APP / "Contents" / "Resources" / "profiles"
            for base in (Path("/Applications"), host.home / "Applications")
        ]
        candidates.append(host.home / "Library" / "Application Support" / "BambuStudio" / "system")
    elif host.system == "Windows":
        program_files = Path(host.env.get("PROGRAMFILES", r"C:\Program Files"))
        candidates.append(program_files / "Bambu Studio" / "resources" / "profiles")
        if appdata := host.env.get("APPDATA"):
            candidates.append(Path(appdata) / "BambuStudio" / "system")
    else:
        config_home = Path(host.env.get("XDG_CONFIG_HOME") or host.home / ".config")
        candidates.append(config_home / "BambuStudio" / "system")
        candidates.append(
            host.home / ".var" / "app" / FLATPAK_ID / "config" / "BambuStudio" / "system"
        )
        candidates += [
            root / "current" / "active" / "files" / "resources" / "profiles"
            for root in _flatpak_roots(host)
        ]
    return candidates


def find_cli(host: Host | None = None) -> tuple[str, ...] | None:
    """The command that runs the Bambu Studio command line, or ``None``."""
    host = host or Host.current()
    if override := host.env.get(CLI_ENV):
        return (override,) if Path(override).is_file() else None
    for command in cli_candidates(host):
        if command[0] == "flatpak" or Path(command[0]).is_file():
            return command
    return None


def find_profiles_dir(host: Host | None = None, cli: Sequence[str] | None = None) -> Path | None:
    """The profile bundle to slice with, or ``None``.

    When several exist (the app's own copy and the copy Bambu Studio keeps in the user's
    data folder, which it updates online), the newest ``BBL.json`` version wins; ties go
    to the one next to the command line.
    """
    host = host or Host.current()
    if override := host.env.get(PROFILES_ENV):
        root = Path(override)
        return root if is_profile_bundle(root) else None
    best: tuple[tuple[int, ...], Path] | None = None
    for root in profile_candidates(host, cli):
        if not is_profile_bundle(root):
            continue
        version = bundle_version(root)
        if best is None or version > best[0]:
            best = (version, root)
    return best[1] if best else None


def is_profile_bundle(root: Path) -> bool:
    """Whether ``root`` holds a Bambu Lab profile index and its preset folder."""
    return (root / f"{VENDOR}.json").is_file() and (root / VENDOR).is_dir()


def bundle_version(root: Path) -> tuple[int, ...]:
    """The bundle's version from ``BBL.json`` (``"02.07.00.08"`` -> ``(2, 7, 0, 8)``)."""
    try:
        document: object = json.loads((root / f"{VENDOR}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    version = (
        cast("dict[str, object]", document).get("version") if isinstance(document, dict) else None
    )
    if not isinstance(version, str):
        return ()
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def _flatpak_roots(host: Host) -> list[Path]:
    return [
        Path("/var/lib/flatpak/app") / FLATPAK_ID,
        host.home / ".local" / "share" / "flatpak" / "app" / FLATPAK_ID,
    ]
