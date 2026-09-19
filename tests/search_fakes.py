"""Replays recorded MakerWorld and Printables responses in place of the network.

The fixtures in tests/fixtures/search/ are real responses recorded on 2026-09-19 (the
MakerWorld one trimmed to the fields that matter; see each file's "_recorded" key).
"""

import json
from pathlib import Path

import requests

from bambu_studio_ai.search import transport

FIXTURES = Path(__file__).parent / "fixtures" / "search"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        if isinstance(self._body, str):
            raise requests.JSONDecodeError("Expecting value", self._body, 0)
        return self._body


class FakeSites:
    """Stands in for requests.get (MakerWorld) and requests.post (Printables).

    Set ``makerworld`` / ``printables`` to ``(status, body)`` or to an exception to raise.
    Every call is recorded in ``calls`` as (method, url, params_or_payload, headers, timeout).
    """

    def __init__(self):
        self.makerworld = (200, load("makerworld_phone_stand.json"))
        self.printables = (200, load("printables_phone_stand.json"))
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("GET", url, params, headers, timeout))
        return self._answer(self.makerworld)

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json.loads(data), headers, timeout))
        return self._answer(self.printables)

    def calls_to(self, method):
        return [call for call in self.calls if call[0] == method]

    @staticmethod
    def _answer(spec):
        if isinstance(spec, BaseException):
            raise spec
        status, body = spec
        return FakeResponse(status, body)


def install(monkeypatch):
    """Route the search transport's HTTP calls to a FakeSites and return it."""
    fake = FakeSites()
    monkeypatch.setattr(transport.requests, "get", fake.get)
    monkeypatch.setattr(transport.requests, "post", fake.post)
    return fake
