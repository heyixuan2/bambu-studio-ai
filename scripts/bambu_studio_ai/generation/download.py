"""Download a finished model safely.

Streams to ``<name>.tmp`` and renames only once the file is complete and looks like the
format we asked for, so an interrupted download or an HTML error page never ends up
where the next step would open it. Provider download links are signed and short-lived
(Tripo's last minutes), so an expired link is replaced with a fresh one from the
provider instead of being retried as-is.
"""

from __future__ import annotations

import re
import struct
from collections.abc import Callable
from typing import TYPE_CHECKING

import requests

from bambu_studio_ai.generation.errors import ProviderError

if TYPE_CHECKING:
    from pathlib import Path

    from bambu_studio_ai.generation.http import HttpClient
    from bambu_studio_ai.generation.providers.base import OutputFormat

#: Larger than any model a provider returns today (Rodin's 10M-face tier is ~0.5 GB).
MAX_MODEL_BYTES = 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT: tuple[float, float] = (10.0, 120.0)
_CHUNK = 1024 * 256
_URL_REFRESHES = 2
# Signed URLs that have expired answer 403 (S3/OSS style), 404 or 410.
_EXPIRED_URL_STATUSES = frozenset({403, 404, 410})
_STL_HEADER = 84
_STL_TRIANGLE = 50


def safe_filename(stem: str, suffix: str) -> str:
    """A file name built only from letters, digits, ``_`` and ``-`` (no path separators)."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")[:80] or "model"
    return f"{cleaned}.{suffix}"


def download_file(
    http: HttpClient,
    fresh_url: Callable[[], str],
    dest: Path,
    *,
    expected: OutputFormat,
    max_bytes: int = MAX_MODEL_BYTES,
) -> Path:
    """Download a model to ``dest``.

    Args:
        http: The client to use (no auth header is sent to file hosts).
        fresh_url: Returns a current download URL; called again when a URL has expired.
        dest: Final path. Written as ``dest.tmp`` first, then renamed.
        expected: The format the file must be; anything else is rejected.
        max_bytes: Abort if the file is larger than this.

    Raises:
        ProviderError: the download failed or the file is not a ``expected`` model.
    """
    url = fresh_url()
    # Start again with a new URL after an expired link (403/404/410) or a broken transfer.
    refreshes_left = _URL_REFRESHES
    while True:
        try:
            _stream_to_file(http, url, dest, expected=expected, max_bytes=max_bytes)
        except ProviderError as exc:
            again = exc.retryable or exc.http_status in _EXPIRED_URL_STATUSES
            if not again or refreshes_left <= 0:
                raise
            refreshes_left -= 1
            url = fresh_url()
            continue
        return dest


def _stream_to_file(
    http: HttpClient, url: str, dest: Path, *, expected: OutputFormat, max_bytes: int
) -> None:
    tmp = dest.with_name(dest.name + ".tmp")
    dest.parent.mkdir(parents=True, exist_ok=True)
    response = http.open_stream(url, timeout=DOWNLOAD_TIMEOUT)
    try:
        declared = int(response.headers.get("Content-Length") or 0)
        if declared > max_bytes:
            raise ProviderError("too_large", f"model is {declared} bytes (limit {max_bytes})")
        written = _write_chunks(response, tmp, max_bytes)
        # With gzip transfer encoding Content-Length counts compressed bytes.
        compressed = response.headers.get("Content-Encoding", "identity") != "identity"
        if declared and not compressed and written != declared:
            raise ProviderError(
                "truncated", f"download stopped at {written} of {declared} bytes", retryable=True
            )
        problem = sniff_problem(tmp, expected)
        if problem:
            raise ProviderError("not_a_model", problem)
        tmp.replace(dest)
    finally:
        response.close()
        tmp.unlink(missing_ok=True)


def _write_chunks(response: requests.Response, tmp: Path, max_bytes: int) -> int:
    written = 0
    try:
        with tmp.open("wb") as out:
            for chunk in response.iter_content(_CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    raise ProviderError("too_large", f"model exceeds {max_bytes} bytes")
                out.write(chunk)
    except requests.RequestException as exc:
        raise ProviderError(
            "network", f"download interrupted: {type(exc).__name__}", retryable=True
        ) from exc
    return written


def sniff_problem(path: Path, expected: OutputFormat) -> str | None:
    """Why ``path`` is not a ``expected`` file, or ``None`` when it looks right."""
    with path.open("rb") as handle:
        head = handle.read(1024)
    size = path.stat().st_size
    if not head:
        return "the download is empty"
    if head.lstrip()[:1] in (b"<", b"{"):
        return f"expected {expected.upper()} but got an HTML/JSON document: {head[:80]!r}"
    if expected == "glb":
        ok = head[:4] == b"glTF"
    elif expected == "3mf":
        ok = head[:2] == b"PK"
    elif expected == "stl":
        ok = _looks_like_stl(head, size)
    else:
        ok = _looks_like_obj(head)
    return None if ok else f"the download is not a {expected.upper()} file (starts {head[:16]!r})"


def _looks_like_stl(head: bytes, size: int) -> bool:
    if len(head) >= _STL_HEADER:
        (triangles,) = struct.unpack_from("<I", head, 80)
        if size == _STL_HEADER + _STL_TRIANGLE * triangles:
            return True
    return head.lstrip().lower().startswith(b"solid")


def _looks_like_obj(head: bytes) -> bool:
    for raw_line in head.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(b"#"):
            continue
        return line.split()[0] in {b"v", b"vn", b"vt", b"f", b"o", b"g", b"mtllib", b"usemtl", b"s"}
    return False
