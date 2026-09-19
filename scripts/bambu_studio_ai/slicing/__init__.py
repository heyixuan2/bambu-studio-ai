"""Slice models with the Bambu Studio command line, using Bambu Studio's own profiles.

Profiles are read from the installed Bambu Studio, flattened (the command line does
not follow ``inherits``) and chosen from the profile graph for the printer, nozzle,
quality and material. The printer's start and filament-change G-code are passed
through untouched. The result is a Bambu Studio project with G-code and the slicer's
own time and filament estimate.
"""

from bambu_studio_ai.slicing.discovery import Host, find_cli, find_profiles_dir
from bambu_studio_ai.slicing.estimate import Estimate, EstimateError, FilamentUse
from bambu_studio_ai.slicing.profiles import ProfileError, ProfileLibrary
from bambu_studio_ai.slicing.resolve import (
    PRINTER_FAMILIES,
    QUALITIES,
    PrintRequest,
    ProfileChoice,
    ResolveError,
    printer_key,
    resolve_profiles,
)
from bambu_studio_ai.slicing.runner import (
    GUI_ONLY_SUFFIXES,
    MODEL_SUFFIXES,
    SliceError,
    SliceJob,
    SliceResult,
    run_slice,
)

__all__ = [
    "GUI_ONLY_SUFFIXES",
    "MODEL_SUFFIXES",
    "PRINTER_FAMILIES",
    "QUALITIES",
    "Estimate",
    "EstimateError",
    "FilamentUse",
    "Host",
    "PrintRequest",
    "ProfileChoice",
    "ProfileError",
    "ProfileLibrary",
    "ResolveError",
    "SliceError",
    "SliceJob",
    "SliceResult",
    "find_cli",
    "find_profiles_dir",
    "printer_key",
    "resolve_profiles",
    "run_slice",
]
