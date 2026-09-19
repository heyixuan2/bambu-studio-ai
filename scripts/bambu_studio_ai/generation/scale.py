"""Measure a downloaded model, set its height, and (as a fallback) convert it locally.

"Height" is the Z extent, because Bambu Studio 2.7 reads every format's coordinates
as millimetres with Z up and does not rotate glTF's Y-up axis (see ``glb.py``). The
same rule is used by ``analyze.py --height``. Nothing is rescaled unless a height is
asked for: AI providers return arbitrary units, so a model that comes back 1.8 mm
tall is reported as such rather than guessed at.

All trimesh use is here; trimesh is only needed for STL/3MF/OBJ files, never for GLB.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bambu_studio_ai.generation import glb
from bambu_studio_ai.generation.errors import DependencyError, InputError

if TYPE_CHECKING:
    from pathlib import Path

    import trimesh

    from bambu_studio_ai.generation.providers.base import OutputFormat

Extents = tuple[float, float, float]
#: Below this, Bambu Studio's "object too small, convert units?" prompt appears.
TINY_MODEL_MM = 5.0


def height_factor(extents: Extents, height_mm: float) -> float:
    """The uniform scale factor that makes the Z extent ``height_mm``.

    Raises:
        InputError: the target is not positive, or the model is flat.
    """
    if height_mm <= 0:
        raise InputError("--height must be a positive number of millimetres")
    if extents[2] <= 0:
        raise InputError("the model has no height (Z extent is 0), so it cannot be scaled")
    return height_mm / extents[2]


def measure(path: Path, output_format: OutputFormat) -> Extents:
    """X, Y, Z size in millimetres as Bambu Studio will import the file."""
    if output_format == "glb":
        return glb.extents_mm(glb.read_glb(path))
    return _extents(_load_mesh(path))


def scale_to_height(path: Path, output_format: OutputFormat, height_mm: float) -> Extents:
    """Rescale the file in place so its Z extent is ``height_mm``; return the new extents.

    GLB files keep their materials and textures untouched (only vertex positions and
    node translations change). STL/3MF/OBJ files are geometry-only and are rewritten.
    """
    if output_format == "glb":
        model = glb.read_glb(path)
        glb.scale_in_place(model, height_factor(glb.extents_mm(model), height_mm))
        glb.write_glb(path, model)
        return glb.extents_mm(model)
    mesh = _load_mesh(path)
    mesh.apply_scale(height_factor(_extents(mesh), height_mm))  # pyright: ignore[reportUnknownMemberType]
    _export(mesh, path, output_format)
    return _extents(mesh)


def has_texture(path: Path, output_format: OutputFormat) -> bool:
    """Whether the file carries a colour texture (only GLB output does)."""
    return output_format == "glb" and glb.has_texture(glb.read_glb(path))


def convert_glb_locally(source: Path, dest: Path, output_format: OutputFormat) -> None:
    """Write the GLB's triangles as STL/3MF/OBJ. Colour and textures are discarded.

    Used only when the provider cannot deliver ``output_format`` itself.

    Raises:
        DependencyError: trimesh (or networkx, for 3MF) is not installed.
        InputError: the GLB cannot be read.
    """
    vertices, faces = glb.triangles(glb.read_glb(source))
    trimesh_module = _trimesh()
    mesh = trimesh_module.Trimesh(vertices=vertices, faces=faces, process=False)
    _export(mesh, dest, output_format)


def _trimesh():  # noqa: ANN202  (returns the optional trimesh module)
    try:
        import trimesh  # noqa: PLC0415  (optional dependency)
    except ImportError as exc:
        raise DependencyError(
            "trimesh is needed for STL/3MF/OBJ files: pip install trimesh"
        ) from exc
    return trimesh


def _load_mesh(path: Path) -> trimesh.Trimesh:
    try:
        loaded = _trimesh().load(str(path), force="mesh")  # pyright: ignore[reportUnknownMemberType]
    except ImportError as exc:  # trimesh's 3MF reader needs networkx
        raise DependencyError(
            f"reading {path.suffix} needs {exc.name}: pip install {exc.name}"
        ) from exc
    return cast("trimesh.Trimesh", loaded)


def _export(mesh: trimesh.Trimesh, path: Path, output_format: OutputFormat) -> None:
    options = {"include_texture": False} if output_format == "obj" else {}
    try:
        mesh.export(str(path), file_type=output_format, **options)  # pyright: ignore[reportUnknownMemberType]
    except ImportError as exc:  # trimesh's 3MF writer needs networkx
        raise DependencyError(
            f"writing {output_format.upper()} needs {exc.name}: pip install {exc.name}"
        ) from exc


def _extents(mesh: trimesh.Trimesh) -> Extents:
    size = mesh.bounds[1] - mesh.bounds[0]
    return (float(size[0]), float(size[1]), float(size[2]))
