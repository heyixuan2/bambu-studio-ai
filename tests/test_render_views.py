"""Camera directions and framing shared by the Blender and software renderers."""

import math

import numpy as np
import pytest
import render_models

from bambu_studio_ai.render import views


def _project(points, direction, distance):
    """Where each point lands in the frame, in units of the half-frame (1.0 = edge)."""
    right, up, back = (np.array(axis) for axis in views.camera_basis(direction))
    depth = distance - points @ back
    return np.stack([points @ right, points @ up], axis=1) / depth[:, None] / views.TAN_HALF_FOV


@pytest.mark.parametrize("name", views.GRID_VIEWS)
def test_camera_basis_is_orthonormal(name):
    right, up, back = (np.array(v) for v in views.camera_basis(views.view_direction(name)))
    basis = np.stack([right, up, back])
    assert basis @ basis.T == pytest.approx(np.eye(3))
    assert np.linalg.det(basis) == pytest.approx(1.0)  # right-handed, like Blender's camera


def test_front_side_and_top_look_the_way_their_labels_say():
    right, up, _ = views.camera_basis(views.view_direction("front"))
    assert right == pytest.approx((1, 0, 0)) and up == pytest.approx((0, 0, 1))
    right, up, _ = views.camera_basis(views.view_direction("side"))
    assert right == pytest.approx((0, 1, 0)) and up == pytest.approx((0, 0, 1))
    # Top view: +Y points up the image, so the model's front is at the bottom.
    right, up, _ = views.camera_basis(views.view_direction("top"))
    assert right == pytest.approx((1, 0, 0)) and up == pytest.approx((0, 1, 0))


@pytest.mark.parametrize("name", views.GRID_VIEWS)
@pytest.mark.parametrize("extents", [(20, 20, 30), (60, 10, 2), (5, 80, 5)])
def test_fit_uses_the_frame_and_never_clips(name, extents):
    _, points = views.framing(render_models.box(extents).vertices)
    direction = views.view_direction(name)
    projected = np.abs(_project(points, direction, views.fit_distance(points, direction)))
    assert projected.max() == pytest.approx(views.FILL)


def test_turntable_directions_circle_the_model_from_above():
    directions = views.turntable_directions()
    assert len(directions) == views.TURNTABLE_FRAMES
    elevations = [math.degrees(math.asin(d[2])) for d in directions]
    assert min(elevations) >= 20 - 1e-9 and max(elevations) <= 36 + 1e-9
    assert directions[0] == pytest.approx(views.view_direction("perspective"), abs=0.08)
    azimuths = np.unwrap([math.atan2(d[1], d[0]) for d in directions])
    assert np.all(np.diff(azimuths) > 0)
    assert azimuths[-1] - azimuths[0] == pytest.approx(2 * math.pi * 35 / 36)


def test_turntable_distance_fits_every_frame():
    # Regression: the old turntable used 0.9x the still distance and clipped tall parts.
    _, points = views.framing(render_models.bracket().vertices)
    directions = views.turntable_directions()
    distance = views.shared_distance(points, directions)
    worst = max(np.abs(_project(points, d, distance)).max() for d in directions)
    assert worst == pytest.approx(views.FILL)
