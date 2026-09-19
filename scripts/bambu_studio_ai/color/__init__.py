"""Turn a textured model into a Bambu Studio project painted with up to 8 filaments.

Pure Python (trimesh + numpy): load the model with its materials, sample each
triangle's colour from its own base-colour texture, pick a palette in CIELAB, give every
triangle one filament, and write a project 3MF whose triangles carry Bambu Studio's
``paint_color``. No Blender, no temporary files.
"""

from bambu_studio_ai.color.bambu_3mf import (
    TEMPLATE_PRINTER,
    build_project,
    paint_code,
    paint_filament,
    read_project,
)
from bambu_studio_ai.color.filaments import METRIC, Filament, FilamentMatch, nearest_filaments
from bambu_studio_ai.color.load import ModelLoadError, NoColourError, load_model
from bambu_studio_ai.color.obj import build_obj
from bambu_studio_ai.color.palette import (
    DEFAULT_MAX_COLORS,
    DEFAULT_MIN_AREA,
    MAX_COLORS,
    Palette,
)
from bambu_studio_ai.color.pipeline import (
    DEFAULT_SMOOTH_PASSES,
    ColorizeOptions,
    ColorizeResult,
    ColorsLostError,
    colorize,
)
from bambu_studio_ai.color.preview import render_preview

__all__ = [
    "DEFAULT_MAX_COLORS",
    "DEFAULT_MIN_AREA",
    "DEFAULT_SMOOTH_PASSES",
    "MAX_COLORS",
    "METRIC",
    "TEMPLATE_PRINTER",
    "ColorizeOptions",
    "ColorizeResult",
    "ColorsLostError",
    "Filament",
    "FilamentMatch",
    "ModelLoadError",
    "NoColourError",
    "Palette",
    "build_obj",
    "build_project",
    "colorize",
    "load_model",
    "nearest_filaments",
    "paint_code",
    "paint_filament",
    "read_project",
    "render_preview",
]
