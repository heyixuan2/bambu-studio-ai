"""Download a finished task's model from the per-format URLs its status lists."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bambu_studio_ai.generation.download import download_file, safe_filename
from bambu_studio_ai.generation.errors import ProviderError
from bambu_studio_ai.generation.providers.base import (
    OUTPUT_FORMATS,
    Fetched,
    OutputFormat,
    TaskState,
    TaskStatus,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from bambu_studio_ai.generation.http import HttpClient


def fetch_listed_output(
    http: HttpClient,
    poll: Callable[[], TaskStatus],
    *,
    wanted: OutputFormat,
    dest_dir: Path,
    stem: str,
) -> Fetched:
    """Download a finished task's model from the URLs its status lists.

    Takes ``wanted`` if listed, else the GLB, else any listed model format; the
    caller converts or warns when it did not get ``wanted``. Expired links are
    replaced by polling the task again.

    Raises:
        ProviderError: the task is not finished, lists no model, or the download failed.
    """
    status = poll()
    if status.state is not TaskState.SUCCEEDED:
        raise ProviderError("not_ready", f"the task is {status.state.value}, not finished")
    candidates: tuple[OutputFormat, ...] = (wanted, "glb", *OUTPUT_FORMATS)
    listed: list[OutputFormat] = [
        candidate for candidate in candidates if status.outputs.get(candidate)
    ]
    if not listed:
        raise ProviderError("no_output", "the finished task lists no downloadable model")
    chosen: OutputFormat = listed[0]
    first_url = [status.outputs[chosen]]

    def fresh_url() -> str:
        if first_url:
            return first_url.pop()
        url = poll().outputs.get(chosen)
        if not url:
            raise ProviderError("no_output", f"the task no longer lists a {chosen.upper()} file")
        return url

    dest = download_file(http, fresh_url, dest_dir / safe_filename(stem, chosen), expected=chosen)
    return Fetched(dest, chosen)
