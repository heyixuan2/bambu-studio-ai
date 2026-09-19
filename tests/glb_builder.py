"""Build small GLB files for the colour tests, with full control over images and materials.

trimesh can't write a file whose normal map comes before its base-colour texture, or a
primitive with vertex colours and no material, so the tests write glTF themselves.
"""

import io
import json
import struct

import numpy as np
from PIL import Image

FLOAT, UINT32 = 5126, 5125


def png(pixels):
    """PNG bytes for an ``(H, W, 3|4)`` uint8 array."""
    buffer = io.BytesIO()
    Image.fromarray(np.asarray(pixels, dtype=np.uint8)).save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


def bands(colours, size=64, alpha=None):
    """Texture of vertical bands, one per ``(r, g, b)`` colour, left to right."""
    image = np.zeros((size, size, 4 if alpha else 3), np.uint8)
    edges = np.linspace(0, size, len(colours) + 1).astype(int)
    for i, colour in enumerate(colours):
        image[:, edges[i]:edges[i + 1], :3] = colour
        if alpha:
            image[:, edges[i]:edges[i + 1], 3] = alpha[i]
    return image


def box(size=(1.0, 1.0, 1.0)):
    """8-vertex box (glTF axes, metres) with planar UVs u = x, v = y, touching 0 and 1."""
    half = np.array(size) / 2
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float) * half
    faces = np.array([
        [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
        [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3],
    ])
    uv = np.stack([(corners[:, 0] + half[0]) / size[0], (corners[:, 1] + half[1]) / size[1]], 1)
    return corners, faces, uv


def grid(cells, width=1.0):
    """Flat square in the glTF XY plane, ``cells`` x ``cells`` quads, UV = position."""
    ticks = np.linspace(0, 1, cells + 1)
    u, v = np.meshgrid(ticks, ticks)
    uv = np.stack([u.ravel(), v.ravel()], 1)
    positions = np.stack([uv[:, 0] * width, (1 - uv[:, 1]) * width, np.zeros(len(uv))], 1)
    index = np.arange((cells + 1) ** 2).reshape(cells + 1, cells + 1)
    a, b = index[:-1, :-1].ravel(), index[:-1, 1:].ravel()
    c, d = index[1:, :-1].ravel(), index[1:, 1:].ravel()
    faces = np.concatenate([np.stack([a, c, b], 1), np.stack([b, c, d], 1)])
    return positions, faces, uv


def seamed_sphere(rings=24, segments=48, radius=0.02):
    """UV sphere whose seam column is duplicated (as every exporter does), UV = lat-long."""
    lat = np.linspace(0, np.pi, rings + 1)
    lon = np.linspace(0, 2 * np.pi, segments + 1)  # last column repeats the first: the seam
    la, lo = np.meshgrid(lat, lon, indexing="ij")
    positions = radius * np.stack([np.sin(la) * np.cos(lo), np.cos(la), np.sin(la) * np.sin(lo)], -1)
    uv = np.stack([lo / (2 * np.pi), la / np.pi], -1).reshape(-1, 2)
    index = np.arange((rings + 1) * (segments + 1)).reshape(rings + 1, segments + 1)
    a, b = index[:-1, :-1].ravel(), index[:-1, 1:].ravel()
    c, d = index[1:, :-1].ravel(), index[1:, 1:].ravel()
    faces = np.concatenate([np.stack([a, b, c], 1), np.stack([b, d, c], 1)])
    return positions.reshape(-1, 3), faces, uv


def write_glb(path, primitives, materials=(), images=(), node_matrices=None):
    """Write a GLB.

    primitives: dicts with ``positions`` (N, 3), ``faces`` (M, 3), optional ``uv`` (N, 2)
    in glTF convention (v down), ``colors`` (N, 4) linear floats and ``material`` index.
    materials: glTF material dicts (texture indices refer to ``images``, one texture each).
    images: PNG bytes. Each primitive becomes its own mesh and node.
    """
    blob, views, accessors = bytearray(), [], []

    def view(data):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
        blob.extend(data)
        return len(views) - 1

    def accessor(array, kind, component, minmax=False):
        array = np.ascontiguousarray(array, np.float32 if component == FLOAT else np.uint32)
        entry = {"bufferView": view(array.tobytes()), "componentType": component,
                 "count": len(array), "type": kind}
        if minmax:
            entry.update(min=array.min(0).tolist(), max=array.max(0).tolist())
        accessors.append(entry)
        return len(accessors) - 1

    meshes, nodes = [], []
    for i, prim in enumerate(primitives):
        attributes = {"POSITION": accessor(prim["positions"], "VEC3", FLOAT, minmax=True)}
        if prim.get("uv") is not None:
            attributes["TEXCOORD_0"] = accessor(prim["uv"], "VEC2", FLOAT)
        if prim.get("colors") is not None:
            attributes["COLOR_0"] = accessor(prim["colors"], "VEC4", FLOAT)
        primitive = {"attributes": attributes, "indices": accessor(np.ravel(prim["faces"]), "SCALAR", UINT32)}
        if prim.get("material") is not None:
            primitive["material"] = prim["material"]
        meshes.append({"primitives": [primitive]})
        node = {"mesh": i}
        if node_matrices and node_matrices[i] is not None:
            node["matrix"] = np.asarray(node_matrices[i], float).T.ravel().tolist()  # column-major
        nodes.append(node)
    image_entries = [{"bufferView": view(data), "mimeType": "image/png"} for data in images]
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
    }
    if materials:
        gltf["materials"] = list(materials)
    if images:
        gltf["images"] = image_entries
        gltf["textures"] = [{"source": i} for i in range(len(images))]
    while len(blob) % 4:
        blob.append(0)
    text = json.dumps(gltf).encode()
    text += b" " * (-len(text) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    path.write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
    return path


def textured(base_image, factor=None, alpha_mode=None):
    """Material whose base colour is texture ``base_image`` (an index into ``images``)."""
    pbr = {"baseColorTexture": {"index": base_image}}
    if factor is not None:
        pbr["baseColorFactor"] = factor
    material = {"pbrMetallicRoughness": pbr}
    if alpha_mode:
        material["alphaMode"] = alpha_mode
    return material
