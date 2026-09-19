"""Printability checks in bambu_studio_ai.mesh: each asserts numbers on meshes of known shape."""

import numpy as np
import pytest
import trimesh

from bambu_studio_ai.mesh.checks import (
    check_bed_contact,
    check_fit,
    check_floating,
    check_material,
    check_overhangs,
)
from bambu_studio_ai.mesh.thickness import check_wall_thickness
from bambu_studio_ai.mesh.topology import diagnose
from mesh_shapes import (
    ABS, HOT, OPEN_PRINTER, PLA, WIDE_PRINTER, box, from_manifold, hollow_sphere, on_plate, wedge,
)


def side_share(mesh):
    """Area share of the two leaning sides of a wedge (the faces with |normal x| > 0.1)."""
    sides = np.abs(mesh.face_normals[:, 0]) > 0.1
    return 100 * mesh.area_faces[sides].sum() / mesh.area


class TestOverhangAngle:
    """Regression: the threshold was -cos(limit) instead of -sin(limit), so a 50 deg
    limit flagged anything leaning more than 40 deg from vertical."""

    @pytest.mark.parametrize(("angle", "flagged"), [(40, False), (50, True), (60, True)])
    def test_wedges_against_the_45_degree_rule(self, angle, flagged):
        mesh = wedge(angle)
        result = check_overhangs(mesh, limit_deg=45)
        if flagged:
            assert result.area_pct == pytest.approx(side_share(mesh), abs=0.1)
            assert result.status == "fail"
        else:
            assert result.area_pct == 0.0
            assert result.status == "pass"

    @pytest.mark.parametrize(("limit", "angle", "flagged"), [
        (50, 42, False),  # the old code flagged this (-cos 50 = -sin 40)
        (50, 60, True),
        (30, 40, True),   # the old code missed this
        (60, 50, False),
    ])
    def test_limit_is_measured_from_vertical(self, limit, angle, flagged):
        assert (check_overhangs(wedge(angle), limit_deg=limit).area_pct > 0) is flagged

    def test_faces_on_the_plate_are_not_overhangs(self):
        result = check_overhangs(box(40, 30, 5), limit_deg=45)
        assert result.area_pct == 0.0

    def test_ceiling_of_a_t_is_an_overhang(self):
        stem = box(10, 10, 30, at=(-5, -5, 0))
        bar = box(60, 10, 5, at=(-30, -5, 30))
        result = check_overhangs(trimesh.util.concatenate([stem, bar]), limit_deg=45)
        underside = 60 * 10  # the whole bar underside faces down, including the part on the stem
        assert result.area_mm2 == pytest.approx(underside, rel=1e-6)


class TestWallThickness:
    """Regression: "wall thickness" was the smallest bounding-box side, so a 60 mm
    sphere with a 0.6 mm wall passed."""

    def test_hollow_sphere_with_thin_wall_fails(self):
        mesh = hollow_sphere(radius=30, wall=0.6)
        result = check_wall_thickness(mesh, diagnose(mesh), PLA.min_wall_mm)
        assert result.status == "fail"
        assert result.thin_area_pct > 95
        assert result.p5_mm == pytest.approx(0.6, abs=0.02)

    def test_hollow_sphere_with_thick_wall_passes(self):
        mesh = hollow_sphere(radius=30, wall=3.0)
        result = check_wall_thickness(mesh, diagnose(mesh), PLA.min_wall_mm)
        assert result.status == "pass"
        assert result.p5_mm == pytest.approx(3.0, abs=0.05)

    def test_thin_plate_is_measured_through_its_thickness(self):
        result = check_wall_thickness(box(60, 40, 0.8), diagnose(box(60, 40, 0.8)), 1.2)
        assert result.status == "fail"
        assert result.p5_mm == pytest.approx(0.8, abs=0.01)

    def test_solid_block_is_reported_as_at_least_the_measuring_range(self):
        mesh = box(50, 50, 50)
        result = check_wall_thickness(mesh, diagnose(mesh), 1.2)
        assert (result.status, result.thin_area_pct, result.min_mm) == ("pass", 0.0, result.max_measured_mm)

    def test_open_mesh_is_not_guessed_at(self):
        closed = box(30, 30, 30)
        mesh = trimesh.Trimesh(vertices=closed.vertices, faces=closed.faces[2:])
        result = check_wall_thickness(mesh, diagnose(mesh), 1.2)
        assert result.status == "skipped"
        assert result.thin_area_pct is None

    def test_large_mesh_stays_fast(self):
        import time
        mesh = on_plate(trimesh.creation.icosphere(subdivisions=6, radius=30))  # 82k faces
        start = time.perf_counter()
        check_wall_thickness(mesh, diagnose(mesh), 1.2)
        assert time.perf_counter() - start < 5


class TestFloatingParts:
    """Regression: every multi-body model failed (an enclosure next to its lid, a
    hollow part's inner shell), and split errors were counted as "one body"."""

    def test_two_parts_side_by_side_on_the_plate(self):
        result = check_floating(trimesh.util.concatenate([box(40, 40, 20), box(40, 40, 3, at=(50, 0, 0))]))
        assert (result.status, result.bodies, result.floating) == ("pass", 2, 0)

    def test_cavity_of_a_hollow_part_is_not_floating(self):
        result = check_floating(hollow_sphere())
        assert (result.status, result.bodies, result.floating) == ("pass", 2, 0)

    def test_body_resting_on_another_body_is_supported(self):
        stacked = trimesh.util.concatenate([box(10, 10, 30, at=(-5, -5, 0)), box(60, 10, 5, at=(-30, -5, 30))])
        assert check_floating(stacked).floating == 0

    def test_body_hovering_above_the_plate_floats(self):
        result = check_floating(trimesh.util.concatenate([box(20, 20, 20), box(5, 5, 5, at=(40, 40, 12))]))
        assert (result.status, result.floating, result.lowest_floating_gap_mm) == ("fail", 1, 12.0)

    def test_ball_inside_a_cavity_floats(self):
        ball = trimesh.creation.icosphere(subdivisions=3, radius=5)
        ball.apply_translation([0, 0, 30])  # centre of the hollow sphere below
        result = check_floating(trimesh.util.concatenate([hollow_sphere(radius=30, wall=2), ball]))
        assert result.floating == 1

    def test_bodies_touching_at_a_vertex_count_as_one(self):
        first = trimesh.Trimesh([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]],
                                [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
        second = trimesh.Trimesh([[0, 0, 10], [10, 0, 20], [0, 10, 20], [0, 0, 20]],
                                 [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
        merged = trimesh.util.concatenate([first, second])
        merged.merge_vertices()
        assert check_floating(merged).bodies == 1


class TestBuildVolume:
    """Regression: "exceeds A1 build volume (230mm)" hid that 230 already has a margin."""

    def test_too_big_names_the_usable_volume_and_the_scale_that_fits(self):
        result = check_fit(np.array([300.0, 50.0, 100.0]), OPEN_PRINTER)
        assert (result.status, result.fits) == ("fail", False)
        assert "X 300.0 mm > 230 mm" in result.summary
        assert "230 x 230 x 230 mm usable, a safety margin inside the printer's spec" in result.summary
        assert result.max_scale_pct == 76.6
        assert "Scale to at most 76.6 %" in result.summary

    def test_fits_when_turned_on_the_plate(self):
        result = check_fit(np.array([150.0, 250.0, 100.0]), WIDE_PRINTER)
        assert (result.status, result.fits, result.rotate_on_plate) == ("warn", True, True)

    def test_unknown_printer_is_skipped_not_assumed(self):
        result = check_fit(np.array([500.0, 500.0, 500.0]), None)
        assert (result.status, result.fits) == ("skipped", None)


class TestMaterial:
    def test_enclosure_needed(self):
        result = check_material(ABS, OPEN_PRINTER)
        assert result.status == "fail"
        assert "enclosed" in result.summary

    def test_hotend_too_cool(self):
        result = check_material(HOT, WIDE_PRINTER)
        assert result.status == "fail"
        assert "hotter than" in result.summary

    def test_pla_on_open_printer(self):
        assert check_material(PLA, OPEN_PRINTER).status == "pass"


class TestBedContact:
    def test_block_sits_on_its_whole_base(self):
        result = check_bed_contact(box(40, 20, 10))
        assert (result.status, result.contact_mm2, result.contact_pct) == ("pass", 800.0, 100.0)

    def test_sphere_touches_at_a_point(self):
        sphere = on_plate(trimesh.creation.uv_sphere(radius=10))
        assert check_bed_contact(sphere).status == "warn"

    def test_area_not_face_count(self):
        """Regression: the old check counted faces, so a finely meshed dome with a small
        flat base read as having no base at all."""
        import manifold3d
        dome = from_manifold(manifold3d.Manifold.sphere(20, 256).trim_by_plane([0, 0, 1], -15))
        result = check_bed_contact(dome)
        base = np.pi * (20**2 - 15**2)
        assert result.contact_mm2 == pytest.approx(base, rel=0.02)
        assert result.status == "pass"
