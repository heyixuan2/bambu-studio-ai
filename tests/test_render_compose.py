"""Output assembly: background, labelled 2x2 grid, turntable GIF; and the software renderer."""

import numpy as np
import pytest
import render_models
from PIL import Image

from bambu_studio_ai.render import compose, meshes, software, views

SOLID = [(200, 0, 0), (0, 200, 0), (0, 0, 200), (200, 200, 0)]


def _tile(rgb, size=200):
    return Image.new("RGBA", (size, size), (*rgb, 255))


def _bright_columns(region):
    """Columns that contain label text (near-white pixels)."""
    pixels = np.asarray(region)
    return np.flatnonzero((pixels.min(axis=2) > 200).any(axis=0))


def test_flatten_puts_transparent_pixels_on_the_background():
    flat = compose.flatten(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))
    assert flat.mode == "RGB"
    assert flat.getpixel((5, 0)) == compose.BACKGROUND_TOP
    assert flat.getpixel((5, 9)) == compose.BACKGROUND_BOTTOM


def test_grid_is_in_reading_order():
    # Regression: the Blender-side stitch put side/top on the top row.
    sheet = compose.grid([(f"view {i}", _tile(rgb)) for i, rgb in enumerate(SOLID)])
    assert sheet.size == (400, 400)
    centres = [(100, 100), (300, 100), (100, 300), (300, 300)]
    assert [sheet.getpixel(c) for c in centres] == SOLID


def test_grid_labels_each_tile():
    names = ["Perspective", "Front", "Side (right)", "Top"]
    sheet = compose.grid([(name, _tile((0, 0, 0))) for name in names])
    widths = []
    for x, y in [(0, 0), (200, 0), (0, 200), (200, 200)]:
        label = _bright_columns(sheet.crop((x, y, x + 200, y + 40)))
        assert label.size > 0, f"no label in tile at {x},{y}"
        widths.append(label.max() - label.min())
        assert _bright_columns(sheet.crop((x, y + 100, x + 200, y + 200))).size == 0
    assert widths[0] > widths[1]  # "Perspective" is longer than "Front"


def test_grid_needs_four_tiles():
    with pytest.raises(ValueError, match="4 tiles"):
        compose.grid([("a", _tile((0, 0, 0)))])


def test_gif_keeps_every_frame_and_loops(tmp_path):
    frames = []
    for i in range(36):
        frame = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        frame.paste((255, 128, 0, 255), (i, 10, i + 20, 30))
        frames.append(frame)
    path = tmp_path / "turn.gif"
    compose.save_gif(frames, path)
    with Image.open(path) as gif:
        assert gif.format == "GIF"
        assert gif.n_frames == 36
        assert gif.info["duration"] == compose.GIF_FRAME_MS
        assert gif.info["loop"] == 0


def test_software_frames_are_transparent_around_the_model(tmp_path):
    model = meshes.load_model(render_models.write_stl(tmp_path / "box.stl"))
    (frame,) = software.render_frames(model, [views.view_direction("perspective")], 200, same_distance=False)
    alpha = np.asarray(frame)[:, :, 3]
    assert frame.size == (200, 200)
    assert alpha[0].max() == 0 and alpha[-1].max() == 0 and alpha[:, 0].max() == 0
    assert alpha[100, 100] == 255


def test_software_render_keeps_material_colours(tmp_path):
    model = meshes.load_model(render_models.write_two_color_glb(tmp_path / "two.glb"))
    (frame,) = software.render_frames(model, [views.view_direction("front")], 200, same_distance=False)
    pixels = np.asarray(frame)[:, :, :3].reshape(-1, 3).astype(int)
    reddish = (pixels[:, 0] > 2 * pixels[:, 1]) & (pixels[:, 0] > 100)
    greenish = (pixels[:, 1] > 2 * pixels[:, 0]) & (pixels[:, 1] > 100)
    assert reddish.sum() > 1000 and greenish.sum() > 1000


def test_software_render_samples_the_texture(tmp_path):
    model = meshes.load_model(render_models.write_textured_glb(tmp_path / "ball.glb"))
    (frame,) = software.render_frames(model, [views.view_direction("front")], 200, same_distance=False)
    pixels = np.asarray(frame)[:, :, :3].reshape(-1, 3).astype(int)
    assert ((pixels[:, 0] > 2 * pixels[:, 2]) & (pixels[:, 0] > 80)).sum() > 1000  # red squares
    assert ((pixels[:, 2] > 2 * pixels[:, 0]) & (pixels[:, 2] > 80)).sum() > 1000  # blue squares


def test_software_occlusion_hides_the_far_cube(tmp_path):
    # Seen from the side (+X), the green cube is in front and covers the red one.
    model = meshes.load_model(render_models.write_two_color_glb(tmp_path / "two.glb"))
    (frame,) = software.render_frames(model, [views.view_direction("side")], 200, same_distance=False)
    pixels = np.asarray(frame)[:, :, :3].reshape(-1, 3).astype(int)
    assert ((pixels[:, 0] > 2 * pixels[:, 1]) & (pixels[:, 0] > 100)).sum() == 0
