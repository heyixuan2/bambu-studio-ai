"""Model previews: a PNG, a labelled 2x2 grid or a turntable GIF of a 3D model.

Three renderers, tried best first: Blender (Cycles; materials, textures, GPU),
Bambu Studio's own thumbnail (flat, fast) and a built-in numpy + Pillow renderer that
needs nothing else installed. Every renderer shows the model in the file's own axes
with Z up, which is how Bambu Studio and ``analyze.py`` read it.
"""

from bambu_studio_ai.render.bambu_studio import find_bambu_studio_cli
from bambu_studio_ai.render.errors import (
    BackendError,
    ModelError,
    PreviewError,
    RendererMissingError,
    RenderFailedError,
    RequestError,
)
from bambu_studio_ai.render.pipeline import (
    MODES,
    RENDERERS,
    HeightCheck,
    PreviewRequest,
    PreviewResult,
    Tools,
    default_timeout,
    plan,
    render_preview,
)

__all__ = [
    "MODES",
    "RENDERERS",
    "BackendError",
    "HeightCheck",
    "ModelError",
    "PreviewError",
    "PreviewRequest",
    "PreviewResult",
    "RenderFailedError",
    "RendererMissingError",
    "RequestError",
    "Tools",
    "default_timeout",
    "find_bambu_studio_cli",
    "plan",
    "render_preview",
]
