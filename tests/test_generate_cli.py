"""Smoke tests for generate.py CLI — help, invalid input, missing API key."""

import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "generate.py")

_has_requests = True
try:
    import requests
except ImportError:
    _has_requests = False

needs_requests = pytest.mark.skipif(not _has_requests, reason="requests not installed")


def _run(args, env_override=None, expect_ok=True):
    env = os.environ.copy()
    env.pop("BAMBU_3D_API_KEY", None)
    env.pop("MESHY_API_KEY", None)
    if env_override:
        env.update(env_override)
    r = subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True, text=True, timeout=15, env=env,
    )
    if expect_ok:
        assert r.returncode == 0, f"Exit {r.returncode}\nstderr: {r.stderr}\nstdout: {r.stdout}"
    return r


@needs_requests
class TestHelp:
    def test_main_help(self):
        r = _run(["--help"])
        assert "3D" in r.stdout or "generate" in r.stdout.lower()

    def test_text_help(self):
        r = _run(["text", "--help"])
        assert "prompt" in r.stdout.lower() or "text" in r.stdout.lower()

    def test_image_help(self):
        r = _run(["image", "--help"])
        assert "image" in r.stdout.lower()


@needs_requests
class TestNoCommand:
    def test_no_subcommand_exits_nonzero(self):
        r = _run([], expect_ok=False)
        assert r.returncode != 0


@needs_requests
class TestMissingAPIKey:
    def test_text_no_key(self):
        r = _run(
            ["text", "a box", "--wait"],
            env_override={"BAMBU_3D_PROVIDER": "meshy"},
            expect_ok=False,
        )
        assert r.returncode != 0
        combined = r.stdout + r.stderr
        assert "api" in combined.lower() or "key" in combined.lower() or "error" in combined.lower()
