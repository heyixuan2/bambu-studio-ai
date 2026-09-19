"""Slice a model with the Bambu Studio command line and collect its estimate.

The presets are flattened copies of Bambu Studio's own, written unchanged: the start,
end and filament-change G-code in them (bed levelling, vibration compensation, AMS
loading) is what the printer needs and is never edited here.

One project setting is added: the build plate (``curr_bed_type``). Bambu Studio keeps it
in the project, not in a preset, and sets it from the printer's default plate when a
project is created. Left out, the command line assumes a Cool Plate: the wrong bed
temperature, and the start G-code skips the first-layer offset for textured plates.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from bambu_studio_ai.slicing.estimate import (
    Estimate,
    EstimateError,
    estimate_from_3mf,
    parse_result_json,
)
from bambu_studio_ai.slicing.profiles import Profile

DEFAULT_TIMEOUT_S = 300.0

#: Model formats the 02.07 command line loads (its own message lists STL, OBJ, AMF,
#: glTF/GLB and FBX; 3MF and PLY were tried and load too).
MODEL_SUFFIXES = (".stl", ".3mf", ".obj", ".amf", ".ply", ".gltf", ".glb", ".fbx")

#: Formats only the Bambu Studio app opens; the command line answers "Unknown file format".
GUI_ONLY_SUFFIXES = (".step", ".stp")

# Relative on purpose: with --outputdir, the command line prefixes the export name with
# that directory even when the name is absolute, and the export then fails.
_EXPORT_NAME = "sliced.3mf"
_VERSION = re.compile(r"^; BambuStudio (\S+)", re.MULTILINE)
_PLATE_GCODE = re.compile(r"Metadata/plate_\d+\.gcode")
_HEADER_BYTES = 512
_OUTPUT_TAIL_LINES = 8


class SliceError(RuntimeError):
    """Bambu Studio ran but did not produce a sliced 3MF."""


@dataclass(frozen=True)
class SliceJob:
    """One model to slice with three flattened presets."""

    model: Path
    output: Path
    machine: Profile
    process: Profile
    filament: Profile
    bed_type: str = ""
    """Build plate, e.g. ``"Textured PEI Plate"``; empty leaves the slicer's default."""
    timeout_s: float = DEFAULT_TIMEOUT_S


@dataclass(frozen=True)
class SliceResult:
    """The sliced project and what it will take to print."""

    output_file: Path
    estimate: Estimate
    bambu_studio_version: str
    """From the G-code header (``"02.07.01.62"``); empty if it has none."""
    seconds: float
    """Wall-clock time the slice took."""


def build_command(cli: Sequence[str], work_dir: Path, model: Path) -> list[str]:
    """The Bambu Studio command line for slicing ``model`` with the presets in ``work_dir``."""
    return [
        *cli,
        "--load-settings",
        f"{work_dir / 'machine.json'};{work_dir / 'process.json'}",
        "--load-filaments",
        str(work_dir / "filament.json"),
        "--slice",
        "0",
        "--outputdir",
        str(work_dir),
        "--export-3mf",
        _EXPORT_NAME,
        str(model),
    ]


def run_slice(cli: Sequence[str], job: SliceJob) -> SliceResult:
    """Slice ``job.model`` into ``job.output`` (a Bambu Studio project with G-code).

    The command line writes ``result.json`` and the plate G-code into its working
    directory, so it runs in a scratch folder next to the output, which is removed
    afterwards.

    Raises:
        SliceError: Bambu Studio failed, timed out, or wrote no sliced 3MF.
        OSError: the output folder is not writable.
    """
    job.output.parent.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=".bambu-slice-", dir=job.output.parent))
    try:
        process = dict(job.process)
        if job.bed_type:
            process["curr_bed_type"] = job.bed_type
        for stem, profile in (
            ("machine", job.machine),
            ("process", process),
            ("filament", job.filament),
        ):
            (work_dir / f"{stem}.json").write_text(
                json.dumps(dict(profile), indent=2, ensure_ascii=False), encoding="utf-8"
            )
        command = build_command(cli, work_dir, job.model.resolve())
        started = time.monotonic()
        try:
            completed = subprocess.run(  # noqa: S603 (argv list, no shell; cli is Bambu Studio)
                command,
                cwd=work_dir,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=job.timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SliceError(
                f"Bambu Studio did not finish within {job.timeout_s:g} s. "
                "Simplify the model or allow more time."
            ) from exc
        except OSError as exc:
            raise SliceError(f"could not run {cli[0]}: {exc}") from exc
        seconds = time.monotonic() - started
        estimate, version = _check_and_estimate(work_dir, completed)
        shutil.move(str(work_dir / _EXPORT_NAME), job.output)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return SliceResult(
        output_file=job.output, estimate=estimate, bambu_studio_version=version, seconds=seconds
    )


def _check_and_estimate(
    work_dir: Path, completed: subprocess.CompletedProcess[str]
) -> tuple[Estimate, str]:
    """The estimate and the slicer version, once the slice is known to have worked."""
    result = _read_result(work_dir / "result.json")
    code = result.get("return_code") if result is not None else None
    if completed.returncode != 0 or (isinstance(code, int) and code != 0):
        raise SliceError(_failure_message(result, completed))
    sliced = work_dir / _EXPORT_NAME
    version = _gcode_version(sliced) if sliced.is_file() else None
    if version is None:
        raise SliceError(
            "Bambu Studio exited without writing a sliced 3MF.\n" + _output_tail(completed)
        )
    if result is not None:
        # An unreadable result.json falls through to the G-code header, which carries
        # the same numbers.
        with contextlib.suppress(EstimateError):
            return parse_result_json(result), version
    try:
        return estimate_from_3mf(sliced), version
    except EstimateError as exc:
        raise SliceError(f"the sliced 3MF has no estimate: {exc}") from exc


def _read_result(path: Path) -> dict[str, object] | None:
    try:
        document: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cast("dict[str, object]", document) if isinstance(document, dict) else None


def _gcode_version(path: Path) -> str | None:
    """The slicer version in the first plate's G-code header; ``None`` if there is no G-code."""
    try:
        with zipfile.ZipFile(path) as archive:
            plates = sorted(n for n in archive.namelist() if _PLATE_GCODE.fullmatch(n))
            if not plates:
                return None
            with archive.open(plates[0]) as gcode:
                head = gcode.read(_HEADER_BYTES).decode("utf-8", errors="replace")
    except (OSError, zipfile.BadZipFile):
        return None
    version = _VERSION.search(head)
    return version.group(1) if version else ""


def _failure_message(
    result: dict[str, object] | None, completed: subprocess.CompletedProcess[str]
) -> str:
    if result is not None and isinstance(result.get("error_string"), str):
        return f"Bambu Studio: {result['error_string']} (code {result.get('return_code')})"
    return (
        f"Bambu Studio exited with code {completed.returncode} and no result.json. "
        "Versions 02.05.00-02.05.01 crash in command-line mode; update if yours is one.\n"
        + _output_tail(completed)
    )


def _output_tail(completed: subprocess.CompletedProcess[str]) -> str:
    text = (completed.stderr or "").strip() or (completed.stdout or "").strip()
    return "\n".join(text.splitlines()[-_OUTPUT_TAIL_LINES:])
