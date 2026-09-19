"""Tests for parametric.py — CSG modeling via manifold3d."""

import json
import os
import subprocess
import sys
import tempfile

import pytest

manifold3d = pytest.importorskip("manifold3d", reason="manifold3d not installed")

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "parametric.py")


def _run(args, expect_ok=True):
    """Run parametric.py with args, return CompletedProcess."""
    r = subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True, text=True, timeout=30,
    )
    if expect_ok:
        assert r.returncode == 0, f"Expected exit 0, got {r.returncode}\nstderr: {r.stderr}\nstdout: {r.stdout}"
    return r


class TestHelp:
    def test_main_help(self):
        r = _run(["--help"])
        assert "parametric" in r.stdout.lower()

    def test_box_help(self):
        r = _run(["box", "--help"])
        assert "width" in r.stdout.lower()


class TestBox:
    def test_basic(self, tmp_path):
        out = str(tmp_path / "box.stl")
        r = _run(["box", "30", "20", "10", "-o", out])
        assert os.path.exists(out)
        assert os.path.getsize(out) > 0
        assert "30.00 x 20.00 x 10.00" in r.stdout

    def test_centered(self, tmp_path):
        out = str(tmp_path / "box_c.stl")
        _run(["box", "10", "10", "10", "--center", "-o", out])
        assert os.path.exists(out)


class TestCylinder:
    def test_basic(self, tmp_path):
        out = str(tmp_path / "cyl.stl")
        r = _run(["cylinder", "--radius", "5", "--height", "20", "-o", out])
        assert os.path.exists(out)
        assert "Watertight: YES" in r.stdout

    def test_cone(self, tmp_path):
        out = str(tmp_path / "cone.stl")
        _run(["cylinder", "--radius", "5", "--height", "20", "--radius-top", "2", "-o", out])
        assert os.path.exists(out)


class TestSphere:
    def test_basic(self, tmp_path):
        out = str(tmp_path / "sphere.stl")
        _run(["sphere", "--radius", "10", "-o", out])
        assert os.path.exists(out)


class TestBracket:
    def test_with_holes(self, tmp_path):
        out = str(tmp_path / "bracket.stl")
        r = _run([
            "bracket", "--width", "30", "--height", "40",
            "--thickness", "3", "--hole-diameter", "3.2", "-o", out,
        ])
        assert os.path.exists(out)
        assert "Watertight: YES" in r.stdout

    # Geometry checks: v1.0 produced a flat plate (base arm hidden inside the upright)
    # with the holes placed outside the part — existence/watertight checks didn't notice.
    @staticmethod
    def _mesh(tmp_path, *extra):
        import trimesh
        out = str(tmp_path / "b.stl")
        _run(["bracket", "--width", "30", "--height", "40", "--thickness", "3", *extra, "-o", out])
        return trimesh.load(out)

    def test_is_an_l_shape(self, tmp_path):
        m = self._mesh(tmp_path)
        assert m.extents == pytest.approx([30, 40, 40], abs=0.01)   # depth defaults to height
        assert m.volume == pytest.approx(30 * 40 * 3 + 30 * 3 * 37, rel=1e-3)

    def test_depth_option(self, tmp_path):
        m = self._mesh(tmp_path, "--depth", "25")
        assert m.extents == pytest.approx([30, 25, 40], abs=0.01)

    def test_holes_go_through_both_arms(self, tmp_path):
        import math
        solid = self._mesh(tmp_path).volume
        holed = self._mesh(tmp_path, "--hole-diameter", "3.2").volume
        two_holes = 2 * math.pi * 1.6 ** 2 * 3
        assert solid - holed == pytest.approx(two_holes, rel=0.05)

    def test_fillet_adds_material(self, tmp_path):
        assert self._mesh(tmp_path, "--fillet", "3").volume > self._mesh(tmp_path).volume


class TestPlateWithHoles:
    def test_four_holes(self, tmp_path):
        out = str(tmp_path / "plate.stl")
        _run([
            "plate-with-holes", "--width", "60", "--depth", "40",
            "--holes", "4", "--hole-diameter", "3.2",
            "--hole-spacing", "25", "-o", out,
        ])
        assert os.path.exists(out)


class TestEnclosure:
    def test_with_lid(self, tmp_path):
        out = str(tmp_path / "enc.stl")
        r = _run([
            "enclosure", "--width", "60", "--depth", "40",
            "--height", "30", "--wall", "2", "--lid", "-o", out,
        ])
        assert os.path.exists(out)
        assert "Watertight: YES" in r.stdout

    def test_lid_sits_on_the_build_plate(self, tmp_path):
        """v1.0 placed the lid 2 mm above the body, so it would print in mid-air."""
        import trimesh
        out = str(tmp_path / "enc.stl")
        _run(["enclosure", "--width", "60", "--depth", "40", "--height", "30",
              "--wall", "2", "--lid", "-o", out])
        parts = trimesh.load(out).split(only_watertight=False)
        assert len(parts) == 2
        assert all(p.bounds[0][2] == pytest.approx(0, abs=1e-6) for p in parts)
        assert max(p.extents[2] for p in parts) == pytest.approx(30, abs=0.01)


class TestCSG:
    def test_subtract(self, tmp_path):
        spec = {
            "ops": [
                {"type": "cube", "size": [30, 30, 10], "id": "base"},
                {"type": "cylinder", "height": 15, "radius": 3, "translate": [15, 15, 0], "id": "hole"},
                {"type": "subtract", "a": "base", "b": "hole", "id": "result"},
            ]
        }
        spec_file = str(tmp_path / "spec.json")
        with open(spec_file, "w") as f:
            json.dump(spec, f)
        out = str(tmp_path / "csg.stl")
        r = _run(["csg", spec_file, "-o", out])
        assert os.path.exists(out)
        assert "Watertight: YES" in r.stdout

    def test_empty_spec_fails(self, tmp_path):
        spec_file = str(tmp_path / "empty.json")
        with open(spec_file, "w") as f:
            json.dump({"ops": []}, f)
        out = str(tmp_path / "empty.stl")
        r = _run(["csg", spec_file, "-o", out], expect_ok=False)
        assert r.returncode != 0


class TestInvalidInput:
    def test_missing_subcommand(self):
        r = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode != 0

    def test_box_missing_args(self):
        r = subprocess.run(
            [sys.executable, SCRIPT, "box", "10"],
            capture_output=True, text=True, timeout=10,
        )
        assert r.returncode != 0

    def test_nonexistent_spec_file(self, tmp_path):
        r = _run(["csg", str(tmp_path / "nope.json"), "-o", str(tmp_path / "x.stl")], expect_ok=False)
        assert r.returncode != 0
