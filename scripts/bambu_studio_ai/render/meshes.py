"""Read a model on the host with trimesh: measure it, colour it, convert it for Blender.

Dimensions come from the same loader ``analyze.py`` uses (``trimesh.load``), in the
file's own units and axes with Z up, so the two commands always agree on a model's
size. Blender can't import 3MF (or anything else trimesh reads but Blender doesn't),
so those files are converted here to a temporary PLY, or GLB when they carry a
texture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, cast

import numpy as np
import trimesh
from numpy.typing import NDArray
from PIL import Image
from trimesh.visual import ColorVisuals, TextureVisuals

from bambu_studio_ai.render.errors import ModelError

if TYPE_CHECKING:
    from pathlib import Path

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
ByteArray = NDArray[np.uint8]

BLENDER_FORMATS: Final = frozenset({".stl", ".obj", ".ply", ".glb", ".gltf", ".fbx"})
"""Formats Blender imports itself; everything else is converted on the host first."""
BLENDER_ONLY_FORMATS: Final = frozenset({".fbx"})
"""Formats trimesh can't read: only the Blender renderer can show them."""
PREVIEW_RGB: Final = (91, 155, 213)
"""Colour for models that carry none (the same blue as Blender's preview material)."""

# From most to least specific; a model reports the first kind any of its parts has.
COLOR_KINDS: Final = ("texture", "vertex", "face", "material", "none")

# analyze.py treats a largest side under 0.5 as metres and under 5 as probably metres.
_METRES_SURE: Final = 0.5
_METRES_LIKELY: Final = 5.0


@dataclass(frozen=True, eq=False)
class Part:
    """One triangle mesh in world coordinates and the colour it carries.

    ``corner_rgb`` holds the colour at each corner of each face, ``(faces, 3, 3)``:
    vertex colours, or the face / material colour repeated, or the texture sampled
    at the vertices. Textured parts also keep the image and per-corner UVs so a
    renderer can sample it per pixel.
    """

    vertices: FloatArray
    faces: IntArray
    color_kind: str
    corner_rgb: ByteArray | None = None
    texture: ByteArray | None = None
    corner_uv: FloatArray | None = None


@dataclass(frozen=True, eq=False)
class LoadedModel:
    """A model as trimesh reads it: its parts, size and what colour it carries."""

    parts: tuple[Part, ...]
    dimensions: tuple[float, float, float]

    @property
    def faces(self) -> int:
        """Total triangle count."""
        return sum(len(part.faces) for part in self.parts)

    @property
    def color_kind(self) -> str:
        """The most specific colour source of any part (``texture`` … ``none``)."""
        kinds = {part.color_kind for part in self.parts}
        return next(kind for kind in COLOR_KINDS if kind in kinds or kind == "none")


def supported_suffixes() -> frozenset[str]:
    """Every file suffix the preview accepts (lower case, with the dot)."""
    return BLENDER_FORMATS | frozenset(f".{name}" for name in trimesh.available_formats())


class _Material(Protocol):
    """What this module reads from trimesh's material classes (which trimesh leaves unannotated)."""

    @property
    def main_color(self) -> NDArray[np.uint8]:
        """RGBA colour of an untextured material."""
        ...

    def to_color(self, uv: FloatArray) -> NDArray[np.uint8] | None:
        """The texture (or material colour) sampled at each UV."""
        ...


def _material(visual: TextureVisuals) -> _Material:
    return cast("_Material", visual.material)  # pyright: ignore[reportUnknownMemberType]


def _uv(visual: TextureVisuals) -> FloatArray | None:
    uv = cast("object", visual.uv)  # pyright: ignore[reportUnknownMemberType]
    return None if uv is None else np.asarray(uv, dtype=np.float64)


def write_mesh(geometry: trimesh.Trimesh | trimesh.Scene, target: Path) -> None:
    """Write ``geometry`` in the format its suffix names (PLY is binary by default)."""
    geometry.export(str(target))  # pyright: ignore[reportUnknownMemberType]


def _to_part(mesh: trimesh.Trimesh) -> Part:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    visual = mesh.visual
    if isinstance(visual, TextureVisuals):
        material = _material(visual)
        image = getattr(material, "baseColorTexture", None) or getattr(material, "image", None)
        uv = _uv(visual)
        if image is not None and uv is not None:
            texture = np.asarray(image.convert("RGB"), dtype=np.uint8)
            sampled = np.asarray(material.to_color(uv), dtype=np.uint8)[:, :3]
            return Part(vertices, faces, "texture", sampled[faces], texture, uv[faces])
        rgb = np.asarray(material.main_color, dtype=np.uint8)[:3]
        corners = np.tile(rgb, (len(faces), 3, 1))
        return Part(vertices, faces, "material", corners)
    if isinstance(visual, ColorVisuals) and visual.kind == "vertex":
        colors = np.asarray(visual.vertex_colors, dtype=np.uint8)[:, :3]
        return Part(vertices, faces, "vertex", colors[faces])
    if isinstance(visual, ColorVisuals) and visual.kind == "face":
        colors = np.asarray(visual.face_colors, dtype=np.uint8)[:, :3]
        return Part(vertices, faces, "face", np.repeat(colors[:, None, :], 3, axis=1))
    return Part(vertices, faces, "none")


def load_model(path: Path) -> LoadedModel:
    """Load every triangle mesh in ``path`` with its scene transforms applied.

    Raises:
        ModelError: the file can't be read or contains no triangles.
    """
    try:
        loaded = trimesh.load(str(path))  # pyright: ignore[reportUnknownMemberType]
    except Exception as exc:  # trimesh raises many types for malformed files
        raise ModelError(f"could not read {path.name}: {exc}") from exc
    geometries: list[object] = (
        list(loaded.dump()) if isinstance(loaded, trimesh.Scene) else [loaded]  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
    )
    meshes = [g for g in geometries if isinstance(g, trimesh.Trimesh) and len(g.faces) > 0]
    if not meshes:
        raise ModelError(f"{path.name} contains no triangles")
    parts = tuple(_to_part(mesh) for mesh in meshes)
    stacked = np.vstack([part.vertices for part in parts])
    extents = stacked.max(axis=0) - stacked.min(axis=0)
    return LoadedModel(parts, (float(extents[0]), float(extents[1]), float(extents[2])))


def units_warning(dimensions: tuple[float, float, float]) -> str | None:
    """Say so when a model is probably not in millimetres (analyze.py's thresholds)."""
    largest = max(dimensions)
    if largest < _METRES_SURE:
        certainty = "almost certainly"
    elif largest < _METRES_LIKELY:
        certainty = "probably"
    else:
        return None
    return (
        f"largest side is {largest:g} units: the file is {certainty} in metres, not mm. "
        "Bambu Studio will import it at this size; analyze.py converts it to mm."
    )


def _corners(part: Part) -> tuple[FloatArray, IntArray]:
    """One vertex per face corner, so each corner can carry its own colour or UV."""
    vertices = np.reshape(part.vertices[part.faces], (-1, 3))
    faces = np.reshape(np.arange(len(vertices), dtype=np.int64), (-1, 3))
    return vertices, faces


def _baked_mesh(part: Part) -> trimesh.Trimesh:
    """The part with its colour baked into per-corner vertex colours."""
    vertices, faces = _corners(part)
    if part.corner_rgb is None:
        rgb = np.tile(np.array(PREVIEW_RGB, dtype=np.uint8), (len(vertices), 1))
    else:
        rgb = np.reshape(part.corner_rgb, (-1, 3))
    return trimesh.Trimesh(vertices, faces, vertex_colors=rgb, process=False)


def blender_input(path: Path, model: LoadedModel | None, workdir: Path) -> Path:
    """The file Blender should import: ``path`` itself, or a converted copy in ``workdir``.

    Textured models become GLB (the Blender side undoes glTF's Y-up turn); the rest
    become a binary PLY, with vertex colours only if the model has any colour.

    Raises:
        ModelError: the file needs converting but trimesh could not read it.
    """
    if path.suffix.lower() in BLENDER_FORMATS:
        return path
    if model is None:
        raise ModelError(f"can't convert {path.name} for Blender")
    if model.color_kind == "texture":
        target = workdir / "model.glb"
        write_mesh(trimesh.Scene([_textured_mesh(part) for part in model.parts]), target)
        return target
    target = workdir / "model.ply"
    if model.color_kind == "none":
        write_mesh(geometry(model), target)
    else:
        write_mesh(_join([_baked_mesh(part) for part in model.parts]), target)
    return target


def _join(meshes: list[trimesh.Trimesh]) -> trimesh.Trimesh:
    joined = cast("object", trimesh.util.concatenate(meshes))  # pyright: ignore[reportUnknownMemberType]
    if not isinstance(joined, trimesh.Trimesh):
        raise ModelError("could not combine the model's parts")
    return joined


def geometry(model: LoadedModel) -> trimesh.Trimesh:
    """All parts as one uncoloured mesh (for renderers that ignore colour)."""
    offsets = np.cumsum([0] + [len(part.vertices) for part in model.parts[:-1]])
    return trimesh.Trimesh(
        np.vstack([part.vertices for part in model.parts]),
        np.vstack([p.faces + o for p, o in zip(model.parts, offsets, strict=True)]),
        process=False,
    )


def _textured_mesh(part: Part) -> trimesh.Trimesh:
    if part.texture is None or part.corner_uv is None:
        return _baked_mesh(part)
    vertices, faces = _corners(part)
    visual = TextureVisuals(
        uv=np.reshape(part.corner_uv, (-1, 2)), image=Image.fromarray(part.texture, "RGB")
    )
    return trimesh.Trimesh(vertices, faces, visual=visual, process=False)
