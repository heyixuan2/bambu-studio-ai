"""Smoke tests for doctor.py."""

import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "doctor.py")


class TestDoctor:
    def test_runs_without_crash(self):
        """doctor.py should run and return 0 or 1 (never crash)."""
        r = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode in (0, 1), f"Unexpected exit code {r.returncode}\nstderr: {r.stderr}"
        assert "Dependency Doctor" in r.stdout

    def test_checks_required_packages(self):
        r = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True, text=True, timeout=30,
        )
        assert "Required packages:" in r.stdout
        assert "trimesh" in r.stdout
        assert "numpy" in r.stdout

    def test_checks_optional_packages(self):
        r = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True, text=True, timeout=30,
        )
        assert "Optional packages:" in r.stdout
        assert "manifold3d" in r.stdout

    def test_checks_system_tools(self):
        r = subprocess.run(
            [sys.executable, SCRIPT],
            capture_output=True, text=True, timeout=30,
        )
        assert "System tools:" in r.stdout
        assert "ffmpeg" in r.stdout

    def test_main_returns_int(self):
        """Test main() directly returns 0 or 1."""
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
        from doctor import main
        result = main()
        assert result in (0, 1)
