"""Smoke tests for preview.py CLI — help, missing file."""

import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "preview.py")


def _run(args, expect_ok=True):
    r = subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True, text=True, timeout=15,
    )
    if expect_ok:
        assert r.returncode == 0, f"Exit {r.returncode}\nstderr: {r.stderr}\nstdout: {r.stdout}"
    return r


class TestHelp:
    def test_help(self):
        r = _run(["--help"])
        assert "preview" in r.stdout.lower() or "model" in r.stdout.lower()


class TestMissingFile:
    def test_nonexistent_file_exits_nonzero(self):
        r = _run(["/tmp/definitely_not_a_real_model_42.stl"], expect_ok=False)
        assert r.returncode != 0
        combined = r.stdout + r.stderr
        assert "not found" in combined.lower() or "error" in combined.lower() or "no such" in combined.lower()
