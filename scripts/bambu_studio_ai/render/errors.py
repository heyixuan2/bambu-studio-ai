"""Exceptions raised by the preview renderers.

Each maps to one CLI exit code, so the command line can tell a bad request (2) from a
missing tool (3) and from a render that ran and failed (1).
"""

from __future__ import annotations


class PreviewError(Exception):
    """Base class for preview failures."""


class ModelError(PreviewError):
    """The model file is missing, unsupported or has no triangles (a bad request)."""


class RequestError(PreviewError):
    """The options don't make sense together, e.g. a renderer that can't draw that view."""


class RendererMissingError(PreviewError):
    """No renderer that can handle this request is installed."""


class BackendError(PreviewError):
    """One renderer ran and failed; the next one in the chain may still succeed."""


class RenderFailedError(PreviewError):
    """Every renderer that was tried failed."""

    def __init__(self, failures: list[tuple[str, str]]) -> None:
        """Keep each renderer's failure so the message can show all of them."""
        self.failures = failures
        detail = "; ".join(f"{name}: {reason}" for name, reason in failures)
        super().__init__(f"rendering failed ({detail})")
