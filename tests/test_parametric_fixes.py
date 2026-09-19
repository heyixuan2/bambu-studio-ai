"""Regression tests for parametric.py bugs found in the v2.0 audit."""

import json
import math
import os
import subprocess
import sys

import pytest

pytest.importorskip("manifold3d", reason="manifold3d not installed")
trimesh = pytest.importorskip("trimesh")

import parametric  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "parametric.py")


def _run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, encoding="utf-8", timeout=60)


def test_clockwise_polygon_extrudes_to_a_solid(tmp_path):
    out = tmp_path / "cw.stl"
    r = _run("extrude", "--polygon", json.dumps([[0, 0], [0, 10], [10, 10], [10, 0]]), "--height", "5",
             "-o", str(out))
    assert r.returncode == 0, r.stderr
    assert trimesh.load(out).volume == pytest.approx(500, rel=1e-6)


def test_empty_result_fails_and_writes_nothing(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"ops": [
        {"type": "cube", "id": "small", "size": [10, 10, 10]},
        {"type": "cube", "id": "big", "size": [20, 20, 20], "translate": [-5, -5, -5]},
        {"type": "subtract", "a": "small", "b": "big"},
    ]}))
    out = tmp_path / "empty.stl"
    r = _run("csg", str(spec), "-o", str(out))
    assert r.returncode != 0
    assert "empty" in (r.stdout + r.stderr).lower()
    assert not out.exists()


@pytest.mark.parametrize("n", [2, 3, 5, 6, 8])
def test_neighbouring_holes_are_spacing_apart(n):
    pts = parametric.hole_positions(100, 100, n, 20)
    assert len(pts) == n
    nearest = min(math.dist(a, b) for i, a in enumerate(pts) for b in pts[i + 1:])
    assert nearest == pytest.approx(20)
    cx = sum(x for x, _ in pts) / n
    cy = sum(y for _, y in pts) / n
    assert (cx, cy) == pytest.approx((50, 50))


def test_single_hole_is_centred():
    assert parametric.hole_positions(60, 40, 1, 25) == [(30, 20)]


def test_hole_outside_the_plate_is_an_error(tmp_path):
    r = _run("plate-with-holes", "--width", "30", "--depth", "30", "--thickness", "3", "--holes", "4",
             "--hole-diameter", "3.2", "--hole-spacing", "40", "-o", str(tmp_path / "p.stl"))
    assert r.returncode != 0
    assert "edge" in (r.stdout + r.stderr)


def test_lid_rim_plugs_into_the_opening(tmp_path):
    w, d, h, wall = 60, 40, 30, 2
    out = tmp_path / "case.stl"
    r = _run("enclosure", "--width", str(w), "--depth", str(d), "--height", str(h), "--wall", str(wall),
             "--lid", "-o", str(out))
    assert r.returncode == 0, r.stderr
    bodies = sorted(trimesh.load(out).split(only_watertight=False), key=lambda b: b.bounds[0][0])
    body, lid = bodies
    assert lid.bounds[0][2] == pytest.approx(0)  # printed on the plate
    # Cut through the rim, just above the lid plate: its footprint must fit the opening with a gap.
    rim = lid.section(plane_origin=[0, 0, wall + 1], plane_normal=[0, 0, 1])
    rim_w, rim_d = (rim.bounds[1] - rim.bounds[0])[:2]
    opening_w, opening_d = w - 2 * wall, d - 2 * wall
    assert opening_w - 0.6 < rim_w < opening_w
    assert opening_d - 0.6 < rim_d < opening_d
    # The rim is centred on the lid, so it lines up with the opening when flipped.
    lid_centre = (lid.bounds[0][:2] + lid.bounds[1][:2]) / 2
    rim_centre = (rim.bounds[0][:2] + rim.bounds[1][:2]) / 2
    assert rim_centre == pytest.approx(lid_centre)
