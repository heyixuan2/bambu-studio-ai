"""Read, measure and rescale binary glTF (GLB) files without touching materials or textures.

Measurements follow what Bambu Studio 2.7 does on import (verified against its source,
``src/libslic3r/Format/AssimpImport.cpp``, and by exporting a test GLB through
``bambu-studio --export-stl``): node transforms are baked into the vertices, coordinates
are read as millimetres, and the file's Z axis is the vertical. glTF's own convention
is Y-up, and Bambu Studio does not convert it, so a provider's model can import lying
on its back; its Z extent is still what Bambu Studio shows as the height.

Rescaling multiplies the vertex positions and every node translation by the same factor,
which scales the whole scene uniformly and leaves the node hierarchy, UVs, materials and
embedded textures byte-for-byte as they were.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from numpy.typing import NDArray

from bambu_studio_ai.generation.errors import InputError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_FLOAT = 5126
_INDEX_TYPES = {5121: "<u1", 5123: "<u2", 5125: "<u4"}
_TRIANGLE_MODES = {4, 5, 6}  # triangles, strip, fan; points and lines are dropped on import
_TRIANGLES = 4
_COMPRESSION = ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization")

Json = dict[str, Any]
Matrix = NDArray[np.float64]


@dataclass
class Glb:
    """A parsed GLB: the JSON document and the binary chunk (mutable)."""

    document: Json
    binary: bytearray


def read_glb(path: Path) -> Glb:
    """Parse a GLB file.

    Raises:
        InputError: the file is not a version-2 GLB.
    """
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != _MAGIC:  # noqa: PLR2004  (12-byte header + chunk header)
        raise InputError(f"{path.name} is not a GLB file")
    (version,) = struct.unpack_from("<I", data, 4)
    if version != 2:  # noqa: PLR2004
        raise InputError(f"{path.name} is glTF version {version}; only version 2 is supported")
    offset, document, binary = 12, None, bytearray()
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8 : offset + 8 + length]
        if kind == _JSON_CHUNK:
            document = cast("Json", json.loads(chunk.decode("utf-8")))
        elif kind == _BIN_CHUNK:
            binary = bytearray(chunk)
        offset += 8 + length
    if document is None:
        raise InputError(f"{path.name} has no glTF JSON chunk")
    return Glb(document, binary)


def write_glb(path: Path, glb: Glb) -> None:
    """Write ``glb`` to ``path`` (chunks padded to 4 bytes as the spec requires)."""
    json_bytes = json.dumps(glb.document, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * (-len(json_bytes) % 4)
    binary = bytes(glb.binary) + b"\0" * (-len(glb.binary) % 4)
    chunks = struct.pack("<II", len(json_bytes), _JSON_CHUNK) + json_bytes
    if binary:
        chunks += struct.pack("<II", len(binary), _BIN_CHUNK) + binary
    path.write_bytes(_MAGIC + struct.pack("<II", 2, 12 + len(chunks)) + chunks)


def extents_mm(glb: Glb) -> tuple[float, float, float]:
    """X, Y, Z size of the scene as Bambu Studio will import it (Z is vertical)."""
    points = [positions for positions, _, _ in _placed_primitives(glb)]
    if not points:
        raise InputError("the GLB contains no triangle meshes")
    stacked = np.vstack(points)
    size = stacked.max(axis=0) - stacked.min(axis=0)
    return (float(size[0]), float(size[1]), float(size[2]))


def triangles(glb: Glb) -> tuple[Matrix, NDArray[np.int64]]:
    """All triangles in world space, as (vertices, faces) arrays, for format conversion."""
    vertices: list[Matrix] = []
    faces: list[NDArray[np.int64]] = []
    base = 0
    for positions, primitive, _ in _placed_primitives(glb):
        if primitive.get("mode", _TRIANGLES) != _TRIANGLES:
            raise InputError("triangle strips/fans are not supported for conversion")
        if "indices" in primitive:
            flat = _index_array(glb, primitive["indices"])
        else:
            flat = np.arange(len(positions), dtype=np.int64)
        index = np.stack((flat[0::3], flat[1::3], flat[2::3]), axis=1)
        vertices.append(positions)
        faces.append(index + base)
        base += len(positions)
    if not vertices:
        raise InputError("the GLB contains no triangle meshes")
    return np.vstack(vertices), np.vstack(faces)


def scale_in_place(glb: Glb, factor: float) -> None:
    """Scale the whole scene uniformly by ``factor`` (positions and node translations)."""
    seen: set[int] = set()
    for primitive in _primitives(glb):
        targets = cast("list[Json]", primitive.get("targets", []))
        for attributes in (primitive.get("attributes", {}), *targets):
            accessor_index = cast("Json", attributes).get("POSITION")
            if accessor_index is None or accessor_index in seen:
                continue
            seen.add(accessor_index)
            _position_view(glb, accessor_index)[:] *= np.float32(factor)
            accessor = glb.document["accessors"][accessor_index]
            for bound in ("min", "max"):
                if bound in accessor:
                    accessor[bound] = [value * factor for value in accessor[bound]]
    for node in glb.document.get("nodes", []):
        if "matrix" in node:
            for i in (12, 13, 14):
                node["matrix"][i] *= factor
        if "translation" in node:
            node["translation"] = [value * factor for value in node["translation"]]


def has_texture(glb: Glb) -> bool:
    """Whether any material has a base-colour texture (what Bambu Studio turns into paint)."""
    for material in glb.document.get("materials", []):
        pbr = cast("Json", material).get("pbrMetallicRoughness", {})
        if "baseColorTexture" in pbr:
            return True
    return False


def _primitives(glb: Glb) -> Iterator[Json]:
    for mesh in glb.document.get("meshes", []):
        for primitive in cast("Json", mesh).get("primitives", []):
            if any(name in primitive.get("extensions", {}) for name in _COMPRESSION):
                raise InputError("compressed GLB meshes (Draco/meshopt) are not supported")
            yield cast("Json", primitive)


def _placed_primitives(glb: Glb) -> Iterator[tuple[Matrix, Json, int]]:
    """(world-space positions, primitive, mesh index) for every triangle primitive in the scene."""
    document = glb.document
    nodes = cast("list[Json]", document.get("nodes", []))
    scenes = cast("list[Json]", document.get("scenes", []))
    if scenes:
        roots = cast("list[int]", scenes[int(document.get("scene", 0))].get("nodes", []))
    else:
        children = {child for node in nodes for child in node.get("children", [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    stack: list[tuple[int, Matrix]] = [(root, np.eye(4)) for root in roots]
    while stack:
        index, parent = stack.pop()
        node = nodes[index]
        world: Matrix = parent @ _local_matrix(node)
        stack.extend((child, world) for child in node.get("children", []))
        if "mesh" not in node:
            continue
        for primitive in document["meshes"][node["mesh"]].get("primitives", []):
            if primitive.get("mode", _TRIANGLES) not in _TRIANGLE_MODES:
                continue
            local = _position_view(glb, primitive["attributes"]["POSITION"]).astype(np.float64)
            rotation_scale: Matrix = np.transpose(world[:3, :3])
            placed: Matrix = local @ rotation_scale + world[:3, 3]
            yield placed, cast("Json", primitive), node["mesh"]


def _local_matrix(node: Json) -> Matrix:
    if "matrix" in node:
        values = cast("list[float]", node["matrix"])  # column-major
        columns = [values[i : i + 4] for i in range(0, 16, 4)]
        return np.transpose(np.array(columns, dtype=np.float64))
    x, y, z, w = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )
    matrix = np.eye(4)
    matrix[:3, :3] = rotation * np.array(node.get("scale", [1.0, 1.0, 1.0]))
    matrix[:3, 3] = node.get("translation", [0.0, 0.0, 0.0])
    return matrix


def _position_view(glb: Glb, accessor_index: int) -> NDArray[np.float32]:
    """A writable (count, 3) view of a float VEC3 accessor inside the binary chunk."""
    accessor = glb.document["accessors"][accessor_index]
    if accessor.get("componentType") != _FLOAT or accessor.get("type") != "VEC3":
        raise InputError(
            "GLB vertex positions are not plain float32 (quantized meshes unsupported)"
        )
    if "sparse" in accessor or "bufferView" not in accessor:
        raise InputError("sparse GLB accessors are not supported")
    view = glb.document["bufferViews"][accessor["bufferView"]]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    stride = view.get("byteStride") or 12
    count = accessor["count"]
    if count and offset + stride * (count - 1) + 12 > len(glb.binary):
        raise InputError("GLB accessor runs past the end of the binary chunk")
    return np.ndarray(
        (count, 3), dtype="<f4", buffer=glb.binary, offset=offset, strides=(stride, 4)
    )


def _index_array(glb: Glb, accessor_index: int) -> NDArray[np.int64]:
    accessor = glb.document["accessors"][accessor_index]
    dtype = _INDEX_TYPES.get(accessor.get("componentType", 0))
    if dtype is None or "bufferView" not in accessor:
        raise InputError("unsupported GLB index accessor")
    view = glb.document["bufferViews"][accessor["bufferView"]]
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    data = np.frombuffer(glb.binary, dtype=dtype, count=accessor["count"], offset=offset)
    return data.astype(np.int64)
