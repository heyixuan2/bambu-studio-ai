"""Image inputs for image-to-3D: a public http(s) URL or a local PNG/JPEG/WebP file.

The image is checked here, before any provider is contacted, so a wrong path or an
unsupported file fails immediately instead of after an upload.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import requests

from bambu_studio_ai.generation.errors import InputError, ProviderError

if TYPE_CHECKING:
    from bambu_studio_ai.generation.http import HttpClient

#: Meshy and Tripo both cap input images at 20 MB.
MAX_IMAGE_BYTES = 20 * 1024 * 1024
_IMAGE_FETCH_TIMEOUT: tuple[float, float] = (10.0, 30.0)
_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


@dataclass(frozen=True)
class ImageInput:
    """An input image: either a URL the provider fetches itself, or the file's bytes."""

    name: str
    url: str | None = None
    data: bytes | None = None
    mime: str | None = None
    """``image/png``, ``image/jpeg`` or ``image/webp`` when ``data`` is set."""

    @property
    def is_url(self) -> bool:
        """Whether the provider is given a URL rather than bytes."""
        return self.url is not None


def is_url(value: str) -> bool:
    """Whether ``value`` is an http(s) URL (a local file named ``httpd.png`` is not)."""
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def load_image(value: str) -> ImageInput:
    """Validate an image path or URL given on the command line.

    Raises:
        InputError: missing file, unsupported type, or larger than 20 MB.
    """
    if is_url(value):
        return ImageInput(name=PurePosixPath(urlparse(value).path).name or "image", url=value)
    path = Path(value).expanduser()
    if not path.is_file():
        raise InputError(f"image not found: {path}")
    size = path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise InputError(f"image is {size // 1024 // 1024} MB; providers accept up to 20 MB")
    data = path.read_bytes()
    mime = image_mime(data)
    if mime is None:
        raise InputError(f"{path.name} is not a PNG, JPEG or WebP image")
    return ImageInput(name=path.name, data=data, mime=mime)


def image_mime(data: bytes) -> str | None:
    """The MIME type of PNG, JPEG or WebP bytes, from their signature."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def data_uri(image: ImageInput) -> str:
    """``data:<mime>;base64,…`` for providers that take inline images (Meshy)."""
    if image.data is None or image.mime is None:
        raise InputError("a data URI needs the image bytes, not a URL")
    return f"data:{image.mime};base64,{base64.b64encode(image.data).decode('ascii')}"


def upload_name(image: ImageInput) -> str:
    """A file name whose extension matches the actual image type."""
    stem = Path(image.name).stem or "image"
    return f"{stem}.{_EXTENSIONS.get(image.mime or '', 'png')}"


def fetch_image(http: HttpClient, image: ImageInput) -> ImageInput:
    """Download a URL image into memory, for providers that only accept uploads (Rodin).

    Raises:
        ProviderError: the URL could not be fetched.
        InputError: it is not a supported image or is too large.
    """
    if image.url is None:
        return image
    response = http.open_stream(image.url, timeout=_IMAGE_FETCH_TIMEOUT)
    try:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise InputError("the image URL points to a file larger than 20 MB")
            chunks.append(chunk)
    except requests.RequestException as exc:
        raise ProviderError("network", f"could not download the image: {exc}") from exc
    finally:
        response.close()
    data = b"".join(chunks)
    mime = image_mime(data)
    if mime is None:
        raise InputError(f"{image.url} did not return a PNG, JPEG or WebP image")
    return ImageInput(name=image.name, data=data, mime=mime)
