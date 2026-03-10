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
