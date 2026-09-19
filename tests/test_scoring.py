"""Tests for analyze.py scoring logic — ensure recommendations don't inflate score."""

import sys
import os
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))


def _make_cube_mesh(size=50.0):
    """Create a simple watertight cube mesh using trimesh."""
    import trimesh
    return trimesh.creation.box(extents=[size, size, size])


def _make_broken_mesh():
    """Create a non-watertight mesh (open surface) that should score low."""
    import trimesh
    verts = np.array([
        [0, 0, 0], [50, 0, 0], [50, 50, 0], [0, 50, 0],
        [0, 0, 50], [50, 0, 50], [50, 50, 50], [0, 50, 50],
    ], dtype=np.float64)
    # Only 4 faces — not watertight, not a volume
    faces = np.array([
        [0, 1, 2], [0, 2, 3],
        [4, 5, 6], [4, 6, 7],
    ])
    return trimesh.Trimesh(vertices=verts, faces=faces)


class TestAnalyzeScoring:
    def test_perfect_cube_scores_high(self):
        from analyze import analyze_mesh
        mesh = _make_cube_mesh(50.0)
        report = analyze_mesh(mesh, "A1", "PLA")
        assert report["score"] >= 7.0, f"Perfect cube should score ≥7, got {report['score']}"

    def test_broken_mesh_scores_low(self):
        from analyze import analyze_mesh
        mesh = _make_broken_mesh()
        report = analyze_mesh(mesh, "A1", "PLA")
        # Open mesh = not watertight → should lose points
        assert report["score"] < 9.0, f"Broken mesh should score <9, got {report['score']}"

    def test_recommendations_dont_inflate(self):
        """Checks 6-9 (layer height, infill, wall, top layers) should NOT
        affect the score — they are informational only."""
        from analyze import analyze_mesh
        mesh = _make_cube_mesh(50.0)
        report = analyze_mesh(mesh, "A1", "PLA")
        # Verify recommendation checks have status 'info', not 'pass'
        rec_checks = [c for c in report["checks"]
                      if "recommendation" in c["name"].lower()]
        for check in rec_checks:
            assert check["status"] == "info", (
                f"{check['name']} should be 'info' not '{check['status']}'")

    def test_oversized_model_loses_points(self):
        from analyze import analyze_mesh
        mesh = _make_cube_mesh(500.0)  # Way bigger than any build volume
        report = analyze_mesh(mesh, "A1 Mini", "PLA")
        assert report["score"] < 8.0, (
            f"Oversized model should lose points, got {report['score']}")

    def test_incompatible_material_loses_points(self):
        from analyze import analyze_mesh
        mesh = _make_cube_mesh(50.0)
        # ABS needs enclosed printer, A1 is open-frame
        report = analyze_mesh(mesh, "A1", "ABS")
        assert any("enclosed" in iss.lower() for iss in report["issues"]), (
            "ABS on A1 should flag enclosed printer issue")


class TestOverhangCheck:
    @staticmethod
    def _overhang(report):
        return next(c for c in report["checks"] if "verhang" in c["name"])

    def test_flat_plate_on_bed_has_no_overhang(self):
        """Regression: the face resting on the bed was counted as a 100%-downward overhang,
        so every flat part reported 'Supports: needed'."""
        import trimesh
        from analyze import analyze_mesh
        plate = trimesh.creation.box(extents=[40, 30, 5])
        plate.apply_translation([0, 0, 2.5])  # sit on z=0 like a print
        report = analyze_mesh(plate, "A1", "PETG", "functional")
        assert self._overhang(report)["overhang_area_pct"] == 0.0
        assert report["print_settings"]["supports"] != "needed"

    def test_real_overhang_is_still_detected(self):
        """A T shape: the underside of the top bar is a genuine 90° overhang."""
        import trimesh
        from analyze import analyze_mesh
        stem = trimesh.creation.box(extents=[10, 10, 30]); stem.apply_translation([0, 0, 15])
        bar = trimesh.creation.box(extents=[60, 10, 5]); bar.apply_translation([0, 0, 32.5])
        t_shape = trimesh.util.concatenate([stem, bar])
        report = analyze_mesh(t_shape, "A1", "PLA")
        assert self._overhang(report)["overhang_area_pct"] > 5
