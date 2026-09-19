"""Small models for the preview tests, built with trimesh at test time.

Building them here (instead of committing binary fixtures) keeps each test's input
readable: the sizes, colours and axes a test asserts on are right in this file.
"""

import numpy as np
import trimesh
from PIL import Image
from trimesh.visual import TextureVisuals
from trimesh.visual.material import PBRMaterial

RED = (230, 30, 30, 255)
GREEN = (30, 200, 30, 255)


def box(extents=(20, 20, 30), corner=(0, 0, 0)):
    """An axis-aligned box whose minimum corner sits at ``corner``."""
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation(np.asarray(corner, dtype=float) - mesh.bounds[0])
    return mesh


def bracket():
    """An L-shaped part: asymmetric, so every view and turntable frame differs."""
    return trimesh.util.concatenate([box((60, 30, 6)), box((6, 30, 40))])


def write_stl(path, extents=(20, 20, 30)):
    box(extents).export(path)
    return path


def write_3mf(path):
    """Two parts: a 20 x 20 x 30 box and a 10 mm cube beside it (40 x 20 x 30 overall)."""
    trimesh.Scene([box((20, 20, 30)), box((10, 10, 10), (30, 0, 0))]).export(path)
    return path


def write_two_color_glb(path):
    """Red and green cubes whose colour is only a PBR baseColorFactor (no texture)."""
    red = box((20, 20, 20))
    red.visual = TextureVisuals(material=PBRMaterial(baseColorFactor=RED))
    green = box((20, 20, 20), (25, 0, 0))
    green.visual = TextureVisuals(material=PBRMaterial(baseColorFactor=GREEN))
    trimesh.Scene([red, green]).export(path)
    return path


def write_textured_glb(path):
    """A 30 mm sphere with a red/blue checker texture and spherical UVs."""
    sphere = trimesh.creation.icosphere(subdivisions=3, radius=15)
    sphere.apply_translation((0, 0, 15))
    unit = sphere.vertices - (0, 0, 15)
    unit /= np.linalg.norm(unit, axis=1, keepdims=True)
    uv = np.stack(
        [np.arctan2(unit[:, 1], unit[:, 0]) / (2 * np.pi) + 0.5, np.arcsin(unit[:, 2]) / np.pi + 0.5],
        axis=1,
    )
    cells = (np.indices((64, 64)) // 16).sum(axis=0) % 2
    texture = np.where(cells[..., None] == 1, [220, 30, 30], [30, 30, 220]).astype(np.uint8)
    sphere.visual = TextureVisuals(uv=uv, image=Image.fromarray(texture, "RGB"))
    sphere.export(path)
    return path


def write_y_tall_glb(path):
    """A slab that is 50 long along the file's Y axis and 10 high along Z."""
    box((20, 50, 10)).export(path)
    return path
