"""A small ``requests.Session`` wrapper with the rules every provider call must follow.

- Every request has a timeout.
- Errors carry the vendor's own code and message (``ProviderError``), never just
  "402 Client Error".
- Only GET requests are retried, and only on 5xx or a dropped connection. A POST may
  have started a paid task even when its response was lost, and a 4xx will fail the
  same way again, so neither is ever repeated automatically.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

import requests

from bambu_studio_ai.generation.errors import ProviderError

#: (connect, read) seconds. Generation endpoints answer quickly; the work runs server-side.
DEFAULT_TIMEOUT: tuple[float, float] = (10.0, 60.0)
_MAX_RETRY_AFTER_S = 30.0
_SERVER_ERROR = 500
_TOO_MANY_REQUESTS = 429
_CLIENT_ERROR = 400


class HttpClient:
    """JSON-over-HTTP calls with timeouts, vendor error bodies and safe retries."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        retries: int = 2,
        backoff_s: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create a client.

        Args:
            session: Injected for tests; a new ``requests.Session`` otherwise.
            timeout: Default (connect, read) timeout for every request.
            retries: Extra attempts for a GET after a 5xx or connection error.
            backoff_s: First retry delay; doubles on each further retry.
            sleep: Injected for tests.
        """
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff_s = backoff_s
        self.sleep = sleep

    def get_json(self, url: str, *, headers: Mapping[str, str] | None = None) -> Any:  # noqa: ANN401  (vendor JSON)
        """GET a JSON document, retrying transient failures."""
        return _json_body(self.send("GET", url, headers=headers))

    def post_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        json: object = None,
        data: Mapping[str, str] | None = None,
        files: Sequence[tuple[str, tuple[str | None, bytes | str, str | None]]] | None = None,
    ) -> Any:  # noqa: ANN401  (vendor JSON)
        """POST (JSON body, or multipart when ``files`` is given) and parse the JSON reply.

        Never retried: a lost response to a generation request may still have spent credits.
        """
        response = self.send("POST", url, headers=headers, json=json, data=data, files=files)
        return _json_body(response)

    def open_stream(
        self, url: str, *, timeout: tuple[float, float] | None = None
    ) -> requests.Response:
        """Start a streamed GET (for downloads); the caller must close the response."""
        return self.send("GET", url, stream=True, timeout=timeout)

    def send(
        self,
        method: str,
        url: str,
        *,
        stream: bool = False,
        timeout: tuple[float, float] | None = None,
        **kwargs: Any,  # noqa: ANN401  (passed straight to requests)
    ) -> requests.Response:
        """Send one request; raise ``ProviderError`` for network errors and HTTP >= 400."""
        retries_left = self.retries if method == "GET" else 0
        delay = self.backoff_s
        while True:
            try:
                response = self.session.request(
                    method, url, stream=stream, timeout=timeout or self.timeout, **kwargs
                )
            except requests.RequestException as exc:
                error = ProviderError("network", _network_message(exc), retryable=True)
            else:
                if response.status_code < _CLIENT_ERROR:
                    return response
                error = error_from_response(response)
                response.close()
            # 4xx (including 429) is never repeated here; the poll loop decides whether to
            # ask again later.
            server_side = error.http_status is None or error.http_status >= _SERVER_ERROR
            if retries_left <= 0 or not server_side:
                raise error
            retries_left -= 1
            self.sleep(min(delay, _MAX_RETRY_AFTER_S))
            delay *= 2


def error_from_response(response: requests.Response) -> ProviderError:
    """Build a ``ProviderError`` from a failed response, preferring the vendor's body.

    Understands the three error shapes in use: Meshy ``{"message"}``, Tripo
    ``{"code", "message", "suggestion"}`` and Rodin ``{"error", "message"}``.
    """
    status = response.status_code
    retryable = status >= _SERVER_ERROR or status == _TOO_MANY_REQUESTS
    code = f"http_{status}"
    message = (response.reason or "error").strip()
    try:
        body: object = response.json()
    except ValueError:
        text = response.text.strip()
        if text:
            message = text[:200]
    else:
        if isinstance(body, dict):
            fields = cast("dict[str, object]", body)
            vendor_code = fields.get("error") or fields.get("code")
            if isinstance(vendor_code, (str, int)) and str(vendor_code):
                code = str(vendor_code)
            vendor_message = fields.get("message")
            if isinstance(vendor_message, str) and vendor_message:
                message = vendor_message
            suggestion = fields.get("suggestion")
            if isinstance(suggestion, str) and suggestion:
                message = f"{message}. {suggestion}"
    return ProviderError(code, f"HTTP {status}: {message}", retryable=retryable, http_status=status)


def _json_body(response: requests.Response) -> Any:  # noqa: ANN401  (vendor JSON)
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(
            "bad_response",
            f"expected JSON from {response.url.split('?', 1)[0]}, got {response.text[:120]!r}",
            retryable=True,
            http_status=response.status_code,
        ) from exc


def _network_message(exc: requests.RequestException) -> str:
    kind = "timed out" if isinstance(exc, requests.Timeout) else "connection failed"
    url = str(exc.request.url) if exc.request is not None and exc.request.url else ""
    where = f" ({url.split('?', 1)[0]})" if url else ""
    return f"network request {kind}{where}: {type(exc).__name__}"
