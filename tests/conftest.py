"""Shared fixtures for bambu-studio-ai tests."""

import os
import sys

import pytest

# Add scripts/ to path so tests can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))


@pytest.fixture(autouse=True)
def isolated_user_state(tmp_path_factory, monkeypatch):
    """Point config, secrets and output at a temp dir for every test.

    Without this a test could read the developer's real API keys from
    ~/.bambu-studio-ai/ and spend credits, or write into their output folder.
    Subprocesses inherit the patched environment.
    """
    base = tmp_path_factory.mktemp("bambu-state")
    for key in list(os.environ):
        if key.startswith("BAMBU_") or key.endswith("_API_KEY"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("BAMBU_STUDIO_AI_HOME", str(base / "home"))
    monkeypatch.setenv("BAMBU_OUTPUT_DIR", str(base / "output"))
