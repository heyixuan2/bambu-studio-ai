"""The printability score: graded deductions, hard-failure caps, and the published rubric."""

import json

import pytest
import trimesh

from bambu_studio_ai.mesh import analyze
from bambu_studio_ai.mesh.score import HARD_FAIL_CAP, MAX_SCORE
from mesh_shapes import ABS, OPEN_PRINTER, PLA, box, box_missing_a_triangle, open_sheets, t_shape, wedge


def run(mesh, material=PLA, printer=OPEN_PRINTER, purpose="general"):
    return analyze(mesh, material=material, printer=printer, purpose=purpose)


def check(analysis, check_id):
    return next(c for c in analysis.to_dict()["checks"] if c["id"] == check_id)


class TestScore:
    def test_clean_cube_scores_full_marks(self):
        assert run(box(50, 50, 50)).score.value == MAX_SCORE

    def test_open_mesh_is_capped(self):
        """Was only asserted "< 9": the open mesh scored 6.7 because free points
        (tolerance, load direction, a swallowed split error) padded it."""
        assert run(open_sheets()).score.value <= HARD_FAIL_CAP

    def test_one_hole_is_enough_to_cap(self):
        assert run(box_missing_a_triangle()).score.value <= HARD_FAIL_CAP

    def test_oversized_model_is_capped(self):
        """Was "< 8" (the old cap was 5)."""
        assert run(box(500, 500, 500)).score.value <= HARD_FAIL_CAP

    def test_floating_body_is_capped(self):
        loose = trimesh.util.concatenate([box(30, 30, 30), box(5, 5, 5, at=(50, 50, 20))])
        assert run(loose).score.value <= HARD_FAIL_CAP

    def test_heavy_overhang_is_graded_down(self):
        """Regression: a model with 25 % overhangs scored 7.8/10."""
        analysis = run(wedge(60))
        assert analysis.overhangs.area_pct > 25
        assert analysis.score.value <= 6.0

    def test_garbage_scores_at_the_floor_not_above_three(self):
        """Regression: the old pass-count formula gave any mesh about 3.3 for free."""
        broken = trimesh.util.concatenate([wedge(60), box(5, 5, 5, at=(80, 80, 40))])
        broken = trimesh.Trimesh(vertices=broken.vertices, faces=broken.faces[2:])
        assert run(broken).score.value <= HARD_FAIL_CAP

    def test_purpose_changes_settings_not_score(self):
        """Replaces "recommendations don't inflate": suggestions are not checks at all now."""
        general, functional = run(box(50, 50, 50)), run(box(50, 50, 50), purpose="functional")
        assert general.score == functional.score
        assert general.print_settings.walls != functional.print_settings.walls
        assert {c["id"] for c in general.to_dict()["checks"]} == {
            "mesh", "build_volume", "floating_parts", "overhangs", "wall_thickness", "bed_contact", "material"}

    def test_incompatible_material_loses_points(self):
        analysis = run(box(50, 50, 50), material=ABS)
        assert any("enclosed" in issue for issue in analysis.to_dict()["issues"])
        assert analysis.score.value == MAX_SCORE - 3


class TestRubric:
    def test_rubric_is_published_and_adds_up(self):
        analysis = run(wedge(50))
        rubric = analysis.to_dict()["score_rubric"]
        assert rubric["max"] == MAX_SCORE
        assert {line["check"] for line in rubric["deductions"]} == {
            "overhangs", "wall_thickness", "bed_contact", "material"}
        assert all(line["rule"] for line in rubric["deductions"] + rubric["caps"])
        total = MAX_SCORE + sum(line["points"] for line in rubric["deductions"])
        assert analysis.score.value == pytest.approx(total)

    def test_applied_caps_are_marked(self):
        rubric = run(box(500, 500, 500)).to_dict()["score_rubric"]
        applied = {cap["check"]: cap["applied"] for cap in rubric["caps"]}
        assert applied == {"mesh": False, "floating_parts": False, "build_volume": True}

    def test_report_is_strict_json(self):
        """Regression: open meshes put NaN (centre of mass) and numpy scalars in the report."""
        text = json.dumps(run(open_sheets()).to_dict(), allow_nan=False)
        assert json.loads(text)["geometry"]["volume_cm3"] is None


class TestOverhangReport:
    def test_flat_plate_on_bed_has_no_overhang(self):
        """Regression: the face resting on the bed was counted as a 100%-downward overhang,
        so every flat part reported 'Supports: needed'."""
        analysis = run(box(40, 30, 5))
        assert check(analysis, "overhangs")["area_pct"] == 0.0
        assert analysis.print_settings.supports == "likely not needed"

    def test_real_overhang_is_still_detected(self):
        """A T shape: the underside of the top bar is a genuine 90 degree overhang."""
        analysis = run(t_shape())
        assert check(analysis, "overhangs")["area_pct"] > 5
        assert analysis.print_settings.supports == "needed for the overhangs"
