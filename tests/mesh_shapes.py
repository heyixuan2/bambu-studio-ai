"""Test meshes with known geometry, all in millimetres and resting on z = 0."""

import math

import manifold3d
import numpy as np
import trimesh

from bambu_studio_ai.mesh import MaterialProfile, PrinterProfile

PLA = MaterialProfile("PLA", 1.2, 190, 220, 60, 15, 30, needs_enclosure=False)
ABS = MaterialProfile("ABS", 1.2, 230, 260, 100, 15, 30, needs_enclosure=True)
HOT = MaterialProfile("HOT", 2.0, 330, 350, 120, 25, 50, needs_enclosure=True)
OPEN_PRINTER = PrinterProfile("Open", (230.0, 230.0, 230.0), enclosed=False, high_temp=False)
WIDE_PRINTER = PrinterProfile("Wide", (300.0, 200.0, 200.0), enclosed=True, high_temp=False)


def on_plate(mesh):
    mesh.apply_translation([0, 0, -mesh.bounds[0][2]])
    return mesh


def box(x, y, z, at=(0.0, 0.0, 0.0)):
    """Axis-aligned box whose lowest corner is at ``at``."""
    mesh = trimesh.creation.box(extents=[x, y, z])
    mesh.apply_translation(np.add(at, [x / 2, y / 2, z / 2]))
    return mesh


def wedge(angle_from_vertical, height=20.0, width=20.0, depth=20.0):
    """Prism on the plate whose two long sides lean outwards by ``angle_from_vertical``."""
    lean = height * math.tan(math.radians(angle_from_vertical))
    points = [(x, y, 0.0) for x in (0.0, width) for y in (0.0, depth)]
    points += [(x, y, height) for x in (-lean, width + lean) for y in (0.0, depth)]
    return trimesh.convex.convex_hull(np.array(points))


def from_manifold(solid):
    mesh = solid.to_mesh()
    return on_plate(trimesh.Trimesh(vertices=np.array(mesh.vert_properties[:, :3]),
                                    faces=np.array(mesh.tri_verts)))


def cup(radius=20.0, height=90.0, wall=2.0):
    """Open-topped cup standing upright on its solid floor."""
    outer = manifold3d.Manifold.cylinder(height, radius, radius, 64)
    inner = manifold3d.Manifold.cylinder(height, radius - wall, radius - wall, 64).translate([0, 0, wall])
    return from_manifold(outer - inner)


def hollow_sphere(radius=30.0, wall=0.6):
    """Closed sphere with a spherical cavity: two shells, the inner one facing inwards."""
    outer = trimesh.creation.icosphere(subdivisions=4, radius=radius)
    inner = trimesh.creation.icosphere(subdivisions=4, radius=radius - wall)
    inner.invert()
    return on_plate(trimesh.util.concatenate([outer, inner]))


def t_shape():
    """A T standing on its stem: the underside of the bar is a 90 degree overhang."""
    return trimesh.util.concatenate([box(10, 10, 30, at=(-5, -5, 0)), box(60, 10, 5, at=(-30, -5, 30))])


def box_missing_a_triangle(size=30.0):
    closed = box(size, size, size)
    return trimesh.Trimesh(vertices=closed.vertices, faces=closed.faces[1:])


def open_sheets():
    """Two unconnected squares, 50 mm apart: not a solid at all."""
    vertices = np.array([[0, 0, 0], [50, 0, 0], [50, 50, 0], [0, 50, 0],
                         [0, 0, 50], [50, 0, 50], [50, 50, 50], [0, 50, 50]], dtype=np.float64)
    return trimesh.Trimesh(vertices=vertices, faces=[[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
