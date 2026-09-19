"""Printability analysis for 3D-print meshes: load, fix units, repair, orient, check, score.

Every function takes and returns data; nothing here prints or exits. ``scripts/analyze.py``
is the command-line front end.
"""

from bambu_studio_ai.mesh.load import (
    LoadedMesh,
    MeshLoadError,
    MeshSaveError,
    derived_path,
    load_mesh,
    save_mesh,
)
from bambu_studio_ai.mesh.orient import OrientResult, orient_for_printing
from bambu_studio_ai.mesh.profiles import MaterialProfile, PrinterProfile
from bambu_studio_ai.mesh.repair import KeepMainResult, RepairResult, keep_largest_body, repair_mesh
from bambu_studio_ai.mesh.report import Analysis, Purpose, analyze
from bambu_studio_ai.mesh.topology import MeshDiagnosis, diagnose
from bambu_studio_ai.mesh.units import MM_PER_UNIT, UnitDecision, decide_units

__all__ = [
    "MM_PER_UNIT",
    "Analysis",
    "KeepMainResult",
    "LoadedMesh",
    "MaterialProfile",
    "MeshDiagnosis",
    "MeshLoadError",
    "MeshSaveError",
    "OrientResult",
    "PrinterProfile",
    "Purpose",
    "RepairResult",
    "UnitDecision",
    "analyze",
    "decide_units",
    "derived_path",
    "diagnose",
    "keep_largest_body",
    "load_mesh",
    "orient_for_printing",
    "repair_mesh",
    "save_mesh",
]
