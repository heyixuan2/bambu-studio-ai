"""Mesh diagnosis, tiered repair, --keep-main and auto-orient in bambu_studio_ai.mesh."""

import math

import numpy as np
import pytest
import trimesh

from bambu_studio_ai.mesh import diagnose, keep_largest_body, orient_for_printing, repair_mesh
from bambu_studio_ai.mesh.checks import check_overhangs
from mesh_shapes import box, box_missing_a_triangle, cup, open_sheets, t_shape


class TestDiagnosis:
    """Regression: holes were reported as "non-manifold edges" and the minor tier could
    never be reached, because is_volume implies is_watertight."""

    def test_closed_box(self):
        report = diagnose(box(10, 10, 10))
        assert (report.watertight, report.boundary_edges, report.nonmanifold_edges) == (True, 0, 0)
        assert report.repair_tier == "none"

    def test_missing_triangle_is_a_hole_not_non_manifold(self):
        report = diagnose(box_missing_a_triangle())
        assert (report.watertight, report.boundary_edges, report.nonmanifold_edges) == (False, 3, 0)
        assert report.repair_tier == "minor"

    def test_three_faces_on_one_edge_are_non_manifold(self):
        closed = box(10, 10, 10)
        fin = trimesh.Trimesh(vertices=np.vstack([closed.vertices, [[5, 5, 20]]]),
                              faces=np.vstack([closed.faces, [closed.faces[0][:2].tolist() + [8]]]))
        report = diagnose(fin)
        assert report.nonmanifold_edges == 1
        assert report.repair_tier == "major"

    def test_inside_out_box(self):
        inverted = box(10, 10, 10)
        inverted.invert()
        report = diagnose(inverted)
        assert (report.watertight, report.inside_out, report.repair_tier) == (True, True, "minor")

    def test_counts_bodies(self):
        assert diagnose(trimesh.util.concatenate([box(5, 5, 5), box(5, 5, 5, at=(10, 0, 0))])).bodies == 2


class TestRepair:
    def test_box_with_a_missing_triangle_becomes_watertight(self):
        broken = box_missing_a_triangle()
        repaired, result = repair_mesh(broken, thorough=False)
        assert repaired.is_watertight
        assert result.after.watertight and result.after.boundary_edges == 0
        assert result.before.boundary_edges == 3
        assert repaired.volume == pytest.approx(30**3)
        assert len(broken.faces) == 11  # the input is not modified

    def test_inside_out_mesh_is_turned_round(self):
        inverted = box(10, 10, 10)
        inverted.invert()
        repaired, result = repair_mesh(inverted, thorough=False)
        assert repaired.volume == pytest.approx(1000)
        assert "turned the inside-out mesh the right way round" in result.steps

    def test_large_hole_needs_the_thorough_pass(self):
        cylinder = trimesh.creation.cylinder(radius=10, height=20, sections=32)
        cap = np.flatnonzero(cylinder.face_normals[:, 2] > 0.99)
        opened = trimesh.Trimesh(vertices=cylinder.vertices,
                                 faces=np.delete(cylinder.faces, cap, axis=0))
        light, light_result = repair_mesh(opened, thorough=False)
        assert not light.is_watertight
        assert any("run with --repair" in note for note in light_result.notes)
        full, _ = repair_mesh(opened, thorough=True)
        assert full.is_watertight

    def test_open_sheets_are_not_doubled_up(self):
        repaired, result = repair_mesh(open_sheets(), thorough=False)
        assert not result.changed
        assert result.after.nonmanifold_edges == 0
        assert len(repaired.faces) == 4


class TestKeepMain:
    def test_removes_small_loose_body(self):
        mesh = trimesh.util.concatenate([box(40, 40, 40), box(2, 2, 2, at=(60, 0, 0))])
        kept, result = keep_largest_body(mesh)
        assert (result.bodies, result.removed) == (2, 1)
        assert kept.extents == pytest.approx([40, 40, 40])

    def test_refuses_when_no_body_dominates(self):
        """Regression: with two equal bodies the old 50 % guard used <, so one was deleted."""
        mesh = trimesh.util.concatenate([box(20, 20, 20), box(20, 20, 20, at=(30, 0, 0))])
        kept, result = keep_largest_body(mesh)
        assert result.removed == 0
        assert len(kept.faces) == len(mesh.faces)
        assert "not removed" in result.note


class TestOrient:
    """Regression: auto-orient maximised footprint/height, so it laid an upright cup on
    its side (0 % -> 25 % overhang)."""

    def test_upright_cup_stays_upright(self):
        oriented, result = orient_for_printing(cup())
        assert not result.rotated
        assert oriented.extents[2] == pytest.approx(90)
        assert result.reason.startswith("kept")

    def test_cup_lying_on_its_side_is_stood_up(self):
        lying = cup()
        lying.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [1, 0, 0]))
        oriented, result = orient_for_printing(lying)
        assert result.rotated
        assert oriented.extents[2] == pytest.approx(90)
        assert result.contact_after_mm2 == pytest.approx(math.pi * 20**2, rel=0.01)  # the floor
        assert oriented.bounds[0][2] == pytest.approx(0)

    def test_t_on_its_stem_is_laid_on_a_wide_face(self):
        oriented, result = orient_for_printing(t_shape())
        assert result.rotated
        assert (result.contact_before_mm2, result.contact_after_mm2) == (100, 600)
        assert check_overhangs(oriented, limit_deg=45).area_pct == 0

    def test_model_above_the_plate_is_dropped_onto_it(self):
        oriented, result = orient_for_printing(box(20, 20, 5, at=(0, 0, 12)))
        assert (result.rotated, result.moved) == (False, True)
        assert oriented.bounds[0][2] == pytest.approx(0)
