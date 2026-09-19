"""The one place the search adapters talk to the network.

Every request names the skill and its repository in the User-Agent, so the sites can
see who is calling and how to reach the maintainer. Transport problems of any kind
(DNS, TLS, timeouts, HTTP errors, a body that isn't JSON) become :class:`SiteError`
with a short reason an agent can repeat to the user.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from http import HTTPStatus

import requests

USER_AGENT = "bambu-studio-ai (+https://github.com/heyixuan2/bambu-studio-ai)"
_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
_POST_HEADERS = {**_HEADERS, "Content-Type": "application/json"}


class SiteError(RuntimeError):
    """A model site could not be searched; the message says why in a few words."""


def get_json(url: str, *, params: Mapping[str, str | int], timeout: float) -> object:
    """GET ``url`` with query ``params`` and return the decoded JSON body.

    Raises:
        SiteError: the request failed, timed out, or did not return JSON.
    """
    try:
        response = requests.get(url, params=dict(params), headers=_HEADERS, timeout=timeout)
    except requests.RequestException as exc:
        raise SiteError(_describe(exc, timeout)) from exc
    return _decode(response)


def post_json(url: str, *, payload: Mapping[str, object], timeout: float) -> object:
    """POST ``payload`` as JSON to ``url`` and return the decoded JSON body.

    A 400 answer with a JSON body is returned rather than raised: GraphQL servers
    report query errors that way, and the caller can then say what went wrong.

    Raises:
        SiteError: the request failed, timed out, or did not return JSON.
    """
    try:
        response = requests.post(
            url, data=json.dumps(payload), headers=_POST_HEADERS, timeout=timeout
        )
    except requests.RequestException as exc:
        raise SiteError(_describe(exc, timeout)) from exc
    return _decode(response, accept_bad_request=True)


def _decode(response: requests.Response, *, accept_bad_request: bool = False) -> object:
    status = response.status_code
    tolerated = accept_bad_request and status == HTTPStatus.BAD_REQUEST
    if status >= HTTPStatus.BAD_REQUEST and not tolerated:
        raise SiteError(f"HTTP {status}")
    try:
        document: object = response.json()
    except ValueError as exc:
        raise SiteError(f"HTTP {status}, response was not JSON") from exc
    return document


def _describe(exc: requests.RequestException, timeout: float) -> str:
    if isinstance(exc, requests.Timeout):
        return f"no answer within {timeout:g} s"
    if isinstance(exc, requests.ConnectionError):
        return "could not connect (offline, DNS or TLS problem)"
    return f"request failed: {type(exc).__name__}"
