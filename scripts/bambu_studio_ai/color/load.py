"""Load a textured model (GLB, glTF or OBJ) into one Z-up mesh with its colour sources.

Every glTF primitive keeps its own material: the colour of a triangle comes from *its*
material's base-colour texture (never "the first image in the file") times the
material's ``baseColorFactor`` and the vertex colours, as the glTF spec defines it.
Vertices are loaded with ``process=False`` so UV-seam duplicates stay split, which keeps
each vertex's UV intact; :func:`bambu_studio_ai.color.segment.weld` joins them later.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import trimesh
from numpy.typing import NDArray
from PIL import Image
from trimesh.visual import ColorVisuals
from trimesh.visual.material import SimpleMaterial

from bambu_studio_ai.color.lab import FloatArray, linear_to_srgb, srgb_to_linear

SUPPORTED_SUFFIXES = (".glb", ".gltf", ".obj")
GLTF_SUFFIXES = (".glb", ".gltf")
METRES_TO_MM = 1000.0

# glTF is +Y up, +Z towards the viewer; slicers are +Z up with the front at -Y.
# A +90 degree turn about X maps (x, y, z) to (x, -z, y).
Y_UP_TO_Z_UP: FloatArray = np.array(
    [[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]], dtype=np.float64
)


class ModelLoadError(RuntimeError):
    """The file could not be read as a mesh."""


class NoColourError(ValueError):
    """The model carries no base-colour texture, vertex colours or material colours."""


@dataclass(frozen=True)
class Part:
    """The triangles of one primitive (one material) and where their colour comes from."""

    faces: slice
    """Range of this part's triangles in :attr:`SourceModel.faces`."""
    texture: NDArray[np.uint8] | None
    """Base-colour image as RGBA ``(height, width, 4)``, or ``None`` when untextured."""
    factor: FloatArray
    """``baseColorFactor`` as linear RGBA, multiplied into every sample."""
    alpha_mode: str
    """glTF ``alphaMode``: ``OPAQUE``, ``MASK`` or ``BLEND``."""
    alpha_cutoff: float
    has_colour: bool
    """Whether this part carries any colour information at all."""


@dataclass(frozen=True)
class SourceModel:
    """All triangles of a model, Z-up, in millimetres, with per-vertex UVs and colours."""

    vertices: FloatArray
    """``(V, 3)`` positions in mm, Z up. Seam vertices are still duplicated."""
    faces: NDArray[np.int64]
    """``(F, 3)`` vertex indices."""
    uv: FloatArray
    """``(V, 2)`` texture coordinates with the origin at the image's bottom-left."""
    vertex_colours: FloatArray
    """``(V, 4)`` sRGB + alpha in [0, 1]; white where the file has none."""
    parts: tuple[Part, ...]
    warnings: tuple[str, ...] = field(default=())

    @property
    def has_colour(self) -> bool:
        """Whether any part carries colour information."""
        return any(part.has_colour for part in self.parts)


def load_model(path: Path) -> SourceModel:
    """Read ``path`` and return its triangles, Z-up and in millimetres.

    glTF files are in metres by specification; OBJ files have no unit, so their numbers
    are taken as millimetres. Both are assumed to be Y-up, which is what glTF requires
    and what textured-OBJ exporters write by default.

    Raises:
        ModelLoadError: the file is missing, unsupported, unreadable or has no triangles.
        NoColourError: no part of the model carries colour information.
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ModelLoadError(
            f"{path.name}: unsupported format {suffix or '(none)'}; use GLB, glTF or OBJ"
        )
    if not path.is_file():
        raise ModelLoadError(f"file not found: {path}")
    try:
        scene = _load_scene(path)
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        # trimesh surfaces malformed files as any of these, depending on the format.
        raise ModelLoadError(f"could not read {path.name}: {exc}") from exc
    scale = METRES_TO_MM if suffix in GLTF_SUFFIXES else 1.0
    model = _collect(scene, scale, gltf=suffix in GLTF_SUFFIXES)
    if len(model.faces) == 0:
        raise ModelLoadError(f"{path.name} contains no triangles")
    if not model.has_colour:
        raise NoColourError(
            f"{path.name} has no base-colour texture, vertex colours or material colours; "
            "there is nothing to turn into filament colours"
        )
    return model


def _load_scene(path: Path) -> trimesh.Scene:
    # trimesh.load's signature has unannotated **kwargs, hence the targeted ignore.
    scene = trimesh.load(str(path), process=False, force="scene")  # pyright: ignore[reportUnknownMemberType]
    return cast("trimesh.Scene", scene)


def _collect(scene: trimesh.Scene, scale: float, *, gltf: bool) -> SourceModel:
    vertices: list[FloatArray] = []
    faces: list[NDArray[np.int64]] = []
    uvs: list[FloatArray] = []
    colours: list[FloatArray] = []
    parts: list[Part] = []
    warnings: list[str] = []
    vertex_count = face_count = 0
    # Scene.geometry is an untyped OrderedDict of name -> Trimesh (or Path, PointCloud).
    geometry = cast("dict[str, object]", scene.geometry)  # pyright: ignore[reportUnknownMemberType]
    for node in scene.graph.nodes_geometry:
        transform, geometry_name = scene.graph[node]
        mesh = geometry.get(str(geometry_name))
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
            continue
        matrix = np.asarray(transform, dtype=np.float64)
        rotation = np.transpose(matrix[:3, :3])
        points = np.matmul(np.asarray(mesh.vertices, dtype=np.float64), rotation) + matrix[:3, 3]
        triangles = np.asarray(mesh.faces, dtype=np.int64)
        if np.linalg.det(matrix[:3, :3]) < 0:
            triangles = triangles[:, ::-1]  # a mirroring node transform flips the winding
        part, uv, vertex_colour, note = _colour_source(mesh, gltf=gltf)
        if note:
            warnings.append(f"{geometry_name}: {note}")
        vertices.append(points)
        faces.append(triangles + vertex_count)
        uvs.append(uv)
        colours.append(vertex_colour)
        parts.append(replace(part, faces=slice(face_count, face_count + len(triangles))))
        vertex_count += len(points)
        face_count += len(triangles)
    if not vertices:
        empty = np.zeros((0, 3))
        return SourceModel(empty, np.zeros((0, 3), np.int64), np.zeros((0, 2)), empty, ())
    all_vertices = np.matmul(np.concatenate(vertices), np.transpose(Y_UP_TO_Z_UP)) * scale
    return SourceModel(
        vertices=all_vertices,
        faces=np.concatenate(faces),
        uv=np.concatenate(uvs),
        vertex_colours=np.concatenate(colours),
        parts=tuple(parts),
        warnings=tuple(warnings),
    )


def _colour_source(
    mesh: trimesh.Trimesh, *, gltf: bool
) -> tuple[Part, FloatArray, FloatArray, str]:
    """Return (part without face range, UVs, vertex colours, warning) for one mesh."""
    count = len(mesh.vertices)
    uv = np.zeros((count, 2))
    white = np.ones((count, 4))
    visual: Any = mesh.visual  # trimesh's visuals are untyped
    plain = Part(slice(0), None, np.ones(4), "OPAQUE", 0.5, has_colour=False)
    if isinstance(visual, ColorVisuals):
        if visual.kind == "vertex":
            colours = _vertex_colours(visual.vertex_colors, gltf=gltf)
            return replace(plain, has_colour=True), uv, colours, ""
        if visual.kind == "face":
            # GLB and OBJ cannot store per-face colours; only other formats reach here.
            return plain, uv, white, "per-face colours are not supported; ignored"
        return plain, uv, white, ""
    material: Any = getattr(visual, "material", None)
    if material is None:
        return plain, uv, white, ""
    note = ""
    texture_uv = getattr(visual, "uv", None)
    extra = getattr(visual, "vertex_attributes", {}).get("color")
    vertex_colour = white if extra is None else _vertex_colours(extra, gltf=gltf)
    if isinstance(material, SimpleMaterial):
        image = getattr(material, "image", None)
        # MTL colours are written in display (sRGB) space; convert to the linear factor.
        factor = _factor(getattr(material, "diffuse", (255, 255, 255, 255)))
        factor[:3] = srgb_to_linear(factor[:3])
        alpha_mode, cutoff = "OPAQUE", 0.5
    else:
        image = getattr(material, "baseColorTexture", None)
        raw = getattr(material, "baseColorFactor", None)
        factor = np.ones(4) if raw is None else _factor(raw)
        alpha_mode = str(getattr(material, "alphaMode", None) or "OPAQUE").upper()
        cutoff = float(getattr(material, "alphaCutoff", None) or 0.5)
    texture = None
    if image is not None and texture_uv is not None and len(texture_uv) == count:
        texture = np.asarray(cast("Image.Image", image).convert("RGBA"), dtype=np.uint8)
        uv = np.asarray(texture_uv, dtype=np.float64)[:, :2]
    elif image is not None:
        note = "has a texture but no texture coordinates; using the material colour"
    has_colour = texture is not None or extra is not None or not np.allclose(factor, 1.0)
    part = Part(slice(0), texture, factor, alpha_mode, cutoff, has_colour=has_colour)
    return part, uv, vertex_colour, note


def _unit_rgba(raw: object) -> FloatArray:
    """Colour channels in [0, 1], padded with opaque alpha: ``(..., 3 or 4)`` -> ``(..., 4)``."""
    values = np.asarray(raw)
    if values.dtype.kind in "iu":
        values = values / np.iinfo(values.dtype).max
    rgba = np.ones((*values.shape[:-1], 4))
    rgba[..., : values.shape[-1]] = values
    return rgba


def _factor(raw: object) -> FloatArray:
    return _unit_rgba(np.asarray(raw).ravel())


def _vertex_colours(raw: object, *, gltf: bool) -> FloatArray:
    """RGBA vertex colours as sRGB in [0, 1] (glTF stores them in linear light)."""
    colours = _unit_rgba(raw)
    if gltf:
        colours[:, :3] = linear_to_srgb(colours[:, :3])
    return colours
