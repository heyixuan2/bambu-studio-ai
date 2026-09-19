"""Choose machine, process and filament presets from Bambu Studio's own profile graph.

Nothing here guesses from file names. The machine is the preset whose ``printer_model``
is the printer's family and whose ``printer_variant`` is the nozzle; processes and
filaments are the presets whose ``compatible_printers`` lists that machine. That is the
rule Bambu Studio applies in its own preset lists, so a choice made here is one the
user could have made by hand.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from bambu_studio_ai.slicing.profiles import Profile, ProfileLibrary, number, strings, text

#: The skill's printer model keys (as in ``config.json``) and the machine families
#: (``printer_model``) Bambu Studio uses for them.
PRINTER_FAMILIES: Final[dict[str, str]] = {
    "A1 Mini": "Bambu Lab A1 mini",
    "A1": "Bambu Lab A1",
    "A2L": "Bambu Lab A2L",
    "P1P": "Bambu Lab P1P",
    "P1S": "Bambu Lab P1S",
    "P2S": "Bambu Lab P2S",
    "X1C": "Bambu Lab X1 Carbon",
    "X1E": "Bambu Lab X1E",
    "X2D": "Bambu Lab X2D",
    "H2C": "Bambu Lab H2C",
    "H2S": "Bambu Lab H2S",
    "H2D": "Bambu Lab H2D",
    "H2D Pro": "Bambu Lab H2D Pro",
}

QUALITIES: Final = ("draft", "standard", "fine")

# Bambu names process presets by layer height relative to the nozzle: "Draft" is
# 0.6 x the nozzle (0.24 mm on a 0.4 nozzle, 0.36 on 0.6, 0.12 on 0.2) and "Fine" is
# 0.3 x (0.12, 0.18, 0.06). Some machines have no preset with those words (the H2D's
# 0.24 mm preset is called "Standard"), so the word wins and the ratio is the fallback.
_QUALITY_WORD: Final = {"draft": "Draft", "fine": "Fine"}
_QUALITY_RATIO: Final = {"draft": 0.6, "standard": 0.5, "fine": 0.3}
# Between presets of the same layer height, prefer the everyday ones; "High Quality"
# and "Strength" variants trade a lot of print time for surface or wall strength.
_LABEL_PREFERENCE: Final = (
    "Standard",
    "Optimal",
    "Fine",
    "Draft",
    "Balanced Quality",
    "Extra Fine",
    "Extra Draft",
    "High Quality",
    "Balanced Strength",
    "Strength",
)
_TOLERANCE_MM = 1e-3
_GENERIC_VENDOR = "Generic"
_BAMBU_VENDOR = "Bambu Lab"

Candidate = tuple[str, Profile]


class ResolveError(ValueError):
    """No preset matches the request; the message says what is available instead."""


@dataclass(frozen=True)
class PrintRequest:
    """What the user asked for."""

    printer: str
    """A key of :data:`PRINTER_FAMILIES`, e.g. ``"P1S"``."""
    nozzle_mm: float = 0.4
    material: str | None = None
    """A filament type (``"PETG"``) or preset name; ``None`` for the printer's default."""
    quality: str = "standard"
    layer_height_mm: float | None = None
    """Overrides ``quality`` when set."""


@dataclass(frozen=True)
class ProfileChoice:
    """The three presets to slice with."""

    printer: str
    nozzle: str
    machine: str
    process: str
    filament: str
    layer_height_mm: float
    material: str
    """The chosen filament's type, e.g. ``"PLA"``."""
    bed_type: str
    """The build plate the printer ships with, e.g. ``"Textured PEI Plate"``; empty if the
    profiles don't say."""


def printer_key(name: str) -> str | None:
    """Map a user-typed printer name (``"a1 mini"``, ``"X1 Carbon"``) to its model key."""
    wanted = _squash(name)
    for key, family in PRINTER_FAMILIES.items():
        if wanted in {_squash(key), _squash(family), _squash(family.removeprefix("Bambu Lab "))}:
            return key
    return None


def resolve_profiles(library: ProfileLibrary, request: PrintRequest) -> ProfileChoice:
    """Pick the machine, process and filament presets for ``request``.

    Raises:
        ResolveError: the printer, nozzle, layer height or material has no matching preset.
    """
    family = PRINTER_FAMILIES.get(request.printer)
    if family is None:
        raise ResolveError(
            f"Unknown printer {request.printer!r}. Known: {', '.join(PRINTER_FAMILIES)}"
        )
    machine_name, machine = find_machine(library, family, request.nozzle_mm)
    process_name, process = find_process(
        library, (machine_name, machine), request.quality, request.layer_height_mm
    )
    filament_name, filament = find_filament(library, (machine_name, machine), request.material)
    return ProfileChoice(
        printer=request.printer,
        nozzle=text(machine, "printer_variant"),
        machine=machine_name,
        process=process_name,
        filament=filament_name,
        layer_height_mm=number(process, "layer_height") or 0.0,
        material=text(filament, "filament_type"),
        bed_type=default_bed_type(library, family),
    )


def default_bed_type(library: ProfileLibrary, family: str) -> str:
    """The plate a new Bambu Studio project uses for this family (``default_bed_type``)."""
    if not library.has("machine_model", family):
        return ""
    return text(library.raw("machine_model", family), "default_bed_type")


def machines_by_nozzle(library: ProfileLibrary, family: str) -> dict[str, Candidate]:
    """The family's machine presets keyed by nozzle (``"0.4"``), smallest nozzle first."""
    found = {
        text(profile, "printer_variant"): (name, profile)
        for name, profile in library.instances("machine")
        if text(profile, "printer_model") == family
    }
    return dict(sorted(found.items(), key=lambda item: _as_float(item[0])))


def find_machine(library: ProfileLibrary, family: str, nozzle_mm: float) -> Candidate:
    """The machine preset for this family and nozzle, e.g. "Bambu Lab P1S 0.4 nozzle".

    Raises:
        ResolveError: the family is unknown to this Bambu Studio, or lacks that nozzle.
    """
    variants = machines_by_nozzle(library, family)
    if not variants:
        raise ResolveError(
            f"This Bambu Studio's profiles (version {library.version or 'unknown'}) have no "
            f"{family}. Update Bambu Studio."
        )
    for variant, candidate in variants.items():
        if _same(_as_float(variant), nozzle_mm):
            return candidate
    raise ResolveError(
        f"{family} has no {nozzle_mm:g} mm nozzle profile. Nozzles: {', '.join(variants)} mm"
    )


def compatible(library: ProfileLibrary, kind: str, machine_name: str) -> list[Candidate]:
    """Selectable presets of ``kind`` that list ``machine_name`` as compatible.

    An empty ``compatible_printers`` means "any printer", as in Bambu Studio.
    """
    return [
        (name, profile)
        for name, profile in library.instances(kind)
        if machine_name in strings(profile, "compatible_printers")
        or not strings(profile, "compatible_printers")
    ]


def find_process(
    library: ProfileLibrary,
    machine: Candidate,
    quality: str = "standard",
    layer_height_mm: float | None = None,
) -> Candidate:
    """The process preset for a quality level or an exact layer height.

    ``standard`` is the machine's own default preset, as in Bambu Studio.

    Raises:
        ResolveError: no compatible process, or none with the requested layer height.
    """
    machine_name, machine_profile = machine
    candidates = compatible(library, "process", machine_name)
    if not candidates:
        raise ResolveError(f"No process profiles are compatible with {machine_name}.")
    default = text(machine_profile, "default_print_profile")
    if layer_height_mm is not None:
        matches = [c for c in candidates if _same(number(c[1], "layer_height"), layer_height_mm)]
        if not matches:
            raise ResolveError(
                f"No {layer_height_mm:g} mm process profile for {machine_name}. "
                f"Layer heights: {', '.join(layer_heights(candidates))} mm"
            )
        return _best_process(matches, default, "Standard")
    if quality not in QUALITIES:
        raise ResolveError(f"Unknown quality {quality!r}. Use one of: {', '.join(QUALITIES)}")
    if quality == "standard":
        for candidate in candidates:
            if candidate[0] == default:
                return candidate
    word = _QUALITY_WORD.get(quality, "Standard")
    pool = [c for c in candidates if _quality_label(c[0]) == word] or candidates
    target = _QUALITY_RATIO[quality] * (_as_float(text(machine_profile, "printer_variant")) or 0.4)

    def distance(candidate: Candidate) -> float:
        return abs((number(candidate[1], "layer_height") or 0.0) - target)

    nearest = min(distance(c) for c in pool)
    return _best_process([c for c in pool if _same(distance(c), nearest)], default, word)


def find_filament(library: ProfileLibrary, machine: Candidate, material: str | None) -> Candidate:
    """The filament preset for a material type or preset name.

    With no material this is the machine's default filament (Bambu PLA Basic on every
    current machine). A type such as ``"PETG"`` picks the machine's default if it is of
    that type, else Bambu Studio's "Generic" preset for it, which is what the slicer
    offers for spools of unknown brand. A preset name ("Bambu PETG HF") may be given
    with or without its ``@BBL …`` suffix.

    Raises:
        ResolveError: nothing compatible matches; the message lists the usable types.
    """
    machine_name, machine_profile = machine
    candidates = compatible(library, "filament", machine_name)
    defaults = strings(machine_profile, "default_filament_profile")
    default = next((c for c in candidates if c[0] in defaults), None)
    if material is None:
        if default is not None:
            return default
        material = "PLA"
    wanted = material.strip().casefold()
    for candidate in candidates:
        if candidate[0].casefold() == wanted:
            return candidate
    same_base = [c for c in candidates if _base_name(c[0]).casefold() == wanted]
    if same_base:
        return min(same_base, key=lambda c: (c[0] not in defaults, c[0]))
    same_type = [c for c in candidates if text(c[1], "filament_type").casefold() == wanted]
    if default is not None and default in same_type:
        return default
    if same_type:
        return min(same_type, key=_filament_rank)
    raise ResolveError(
        f"No {material} filament profile for {machine_name}. "
        f"Materials: {', '.join(material_types(candidates))}. "
        "Or pass a Bambu Studio filament name, e.g. 'Bambu PETG HF'."
    )


def layer_heights(candidates: Sequence[Candidate]) -> list[str]:
    """Distinct layer heights of process presets, thinnest first, as text (``"0.2"``)."""
    heights = {number(profile, "layer_height") for _, profile in candidates}
    return [f"{height:g}" for height in sorted(h for h in heights if h is not None)]


def material_types(candidates: Sequence[Candidate]) -> list[str]:
    """Distinct filament types of filament presets, sorted."""
    return sorted({text(profile, "filament_type") for _, profile in candidates} - {""})


def _best_process(candidates: Sequence[Candidate], default: str, word: str) -> Candidate:
    def rank(candidate: Candidate) -> tuple[bool, bool, int, str]:
        label = _quality_label(candidate[0])
        preference = (
            _LABEL_PREFERENCE.index(label) if label in _LABEL_PREFERENCE else len(_LABEL_PREFERENCE)
        )
        return (candidate[0] != default, label != word, preference, candidate[0])

    return min(candidates, key=rank)


def _filament_rank(candidate: Candidate) -> tuple[bool, bool, int, str]:
    name, profile = candidate
    vendor = text(profile, "filament_vendor")
    return (vendor != _GENERIC_VENDOR, vendor != _BAMBU_VENDOR, len(_base_name(name)), name)


def _quality_label(process_name: str) -> str:
    """The quality word of a process name: ``0.28mm Extra Draft @BBL X1C`` -> ``Extra Draft``."""
    label = _base_name(process_name)
    return label.split("mm ", 1)[1] if "mm " in label else label


def _base_name(preset_name: str) -> str:
    """A preset name without its machine suffix: ``Generic PLA @BBL A1`` -> ``Generic PLA``."""
    return preset_name.split(" @", 1)[0]


def _squash(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def _as_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _same(a: float | None, b: float) -> bool:
    return a is not None and abs(a - b) < _TOLERANCE_MM
