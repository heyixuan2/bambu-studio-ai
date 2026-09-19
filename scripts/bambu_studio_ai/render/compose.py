"""Turn rendered frames into the file the user sees: a PNG, a labelled grid or a GIF.

Every renderer hands over RGBA frames on a transparent background; the background,
labels and GIF encoding happen here, once, so all renderers produce the same kind of
picture.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

BACKGROUND_TOP: Final = (60, 62, 66)
BACKGROUND_BOTTOM: Final = (24, 25, 27)
LABEL_TEXT: Final = (240, 240, 240)
LABEL_BOX: Final = (0, 0, 0, 150)
GIF_FRAME_MS: Final = 120
_LABEL_FRACTION: Final = 0.045  # label height relative to the tile


def background(size: tuple[int, int]) -> Image.Image:
    """A dark vertical gradient: light and dark models both stand out against it."""
    width, height = size
    column = Image.new("RGB", (1, height))
    for row in range(height):
        t = row / max(height - 1, 1)
        column.putpixel(
            (0, row),
            tuple(
                round(a + (b - a) * t)
                for a, b in zip(BACKGROUND_TOP, BACKGROUND_BOTTOM, strict=True)
            ),
        )
    return column.resize((width, height))


def flatten(frame: Image.Image) -> Image.Image:
    """The frame composited onto the background, as RGB."""
    rgba = frame.convert("RGBA")
    canvas = background(rgba.size).convert("RGBA")
    canvas.alpha_composite(rgba)
    return canvas.convert("RGB")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 has one fixed-size bitmap font
        return ImageFont.load_default()


def label(tile: Image.Image, text: str) -> Image.Image:
    """Write ``text`` in a small dark box in the tile's top-left corner."""
    tile = tile.convert("RGBA")
    font_size = max(12, round(tile.height * _LABEL_FRACTION))
    font = _font(font_size)
    overlay = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    pen = ImageDraw.Draw(overlay)
    margin = font_size // 2
    left, top, right, bottom = pen.textbbox((margin * 2, margin * 2), text, font=font)
    pen.rounded_rectangle(
        (left - margin, top - margin, right + margin, bottom + margin),
        radius=margin,
        fill=LABEL_BOX,
    )
    pen.text((margin * 2, margin * 2), text, font=font, fill=LABEL_TEXT)
    tile.alpha_composite(overlay)
    return tile.convert("RGB")


def grid(tiles: Sequence[tuple[str, Image.Image]]) -> Image.Image:
    """A 2x2 grid in reading order: first two tiles on top, the next two below."""
    if len(tiles) != 4:  # noqa: PLR2004
        raise ValueError(f"a grid needs 4 tiles, got {len(tiles)}")
    width, height = tiles[0][1].size
    sheet = Image.new("RGB", (width * 2, height * 2))
    for index, (text, tile) in enumerate(tiles):
        sheet.paste(label(flatten(tile), text), ((index % 2) * width, (index // 2) * height))
    return sheet


def save_png(frame: Image.Image, path: Path) -> None:
    """Save a single frame on the background."""
    flatten(frame).save(path, format="PNG", optimize=True)


def save_gif(frames: Sequence[Image.Image], path: Path, frame_ms: int = GIF_FRAME_MS) -> None:
    """Save an endlessly looping GIF with one shared palette (so colours don't flicker)."""
    if not frames:
        raise ValueError("a GIF needs at least one frame")
    flat = [flatten(frame) for frame in frames]
    # Build the palette from a sample of frames so every angle's colours are in it.
    sample = flat[:: max(1, len(flat) // 6)]
    strip = Image.new("RGB", (flat[0].width, flat[0].height * len(sample)))
    for index, frame in enumerate(sample):
        strip.paste(frame, (0, index * frame.height))
    palette = strip.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    indexed = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in flat]
    indexed[0].save(
        path,
        format="GIF",
        save_all=True,
        append_images=indexed[1:],
        duration=frame_ms,
        loop=0,
        disposal=1,
    )
