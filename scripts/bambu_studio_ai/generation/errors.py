"""Exceptions raised by the generation package.

Library code raises these instead of printing or exiting; the CLI maps them to exit codes.
"""

from __future__ import annotations


class GenerationError(Exception):
    """Base class for every error raised by ``bambu_studio_ai.generation``."""


class ProviderError(GenerationError):
    """A provider (or its file host) rejected a request or could not be reached.

    Attributes:
        code: The vendor's error code (``"API_INSUFFICIENT_FUNDS"``, ``"2010"``), or
            ``"http_<status>"`` / ``"network"`` when the vendor gave none.
        message: Human-readable reason, taken from the vendor's error body when present.
        retryable: Whether sending the same request later could succeed (5xx, 429,
            connection errors). 4xx rejections are never retryable.
        http_status: The HTTP status code, when there was a response.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        http_status: int | None = None,
    ) -> None:
        """Create the error; ``str()`` gives ``"<message> (<code>)"``."""
        super().__init__(f"{message} ({code})")
        self.code = code
        self.message = message
        self.retryable = retryable
        self.http_status = http_status


class InputError(GenerationError, ValueError):
    """A user-supplied value (image, task id, option) is unusable."""


class DependencyError(GenerationError):
    """An optional Python package needed for this step is not installed."""
