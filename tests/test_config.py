"""Config location, legacy fallback, and configure.py behaviour."""

import json
import os
import stat
import subprocess
import sys

import pytest

import common

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("BAMBU_STUDIO_AI_HOME", str(h))
    monkeypatch.setenv("BAMBU_OUTPUT_DIR", str(tmp_path / "out"))
    for k in common.ENV_TO_CONFIG:
        monkeypatch.delenv(k, raising=False)
    return h


def _configure(*args, stdin=None):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "configure.py"), *args],
                          input=stdin, capture_output=True, text=True, env=os.environ.copy())


def test_home_dir_env_override(home):
    assert common.home_dir() == str(home)


def test_output_dir_env_override(home, tmp_path):
    assert common.output_dir("models") == str(tmp_path / "out" / "models")
    assert os.path.isdir(tmp_path / "out" / "models")


def test_legacy_file_used_only_when_new_missing(home, tmp_path, monkeypatch):
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "config.json").write_text('{"model": "A1"}')
    monkeypatch.setattr(common, "SKILL_DIR", str(skill))
    assert common.user_file("config.json") == str(skill / "config.json")
    assert common.load_config()["model"] == "A1"

    home.mkdir()
    (home / "config.json").write_text('{"model": "P1S"}')
    assert common.user_file("config.json") == str(home / "config.json")
    assert common.load_config()["model"] == "P1S"


def test_configure_set_and_secret(home):
    r = _configure("set", "model", "a1 mini", "mode", "LOCAL", "printer_ip", "10.0.0.5")
    assert r.returncode == 0, r.stdout + r.stderr
    cfg = json.loads((home / "config.json").read_text())
    assert cfg == {"model": "A1 Mini", "mode": "local", "printer_ip": "10.0.0.5"}

    r = _configure("secret", "access_code", stdin="12345678\n")
    assert r.returncode == 0, r.stdout + r.stderr
    sec_path = home / ".secrets.json"
    assert json.loads(sec_path.read_text()) == {"access_code": "12345678"}
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(sec_path).st_mode) == 0o600

    shown = _configure("show").stdout
    assert "12345678" not in shown
    assert "5678" in shown


def test_configure_rejects_bad_values(home):
    assert _configure("set", "model", "Z9").returncode != 0
    assert _configure("set", "access_code", "x").returncode != 0
    assert not (home / "config.json").exists()


def test_bambu_reads_connection_from_config(home):
    """Regression: v1.x LocalBackend ignored config.json and only read env vars."""
    _configure("set", "mode", "local", "printer_ip", "10.0.0.5", "serial", "SERIAL1")
    _configure("secret", "access_code", stdin="abcd")
    code = (
        "import bambu; "
        "print(bambu._get_config('BAMBU_IP'), bambu._get_config('BAMBU_SERIAL'), "
        "bambu._get_config('BAMBU_ACCESS_CODE'))"
    )
    r = subprocess.run([sys.executable, "-c", code], cwd=SCRIPTS, capture_output=True, text=True,
                       env=os.environ.copy())
    assert r.stdout.strip() == "10.0.0.5 SERIAL1 abcd", r.stdout + r.stderr


def test_env_overrides_config(home, monkeypatch):
    _configure("set", "printer_ip", "10.0.0.5")
    monkeypatch.setenv("BAMBU_IP", "10.9.9.9")
    r = subprocess.run([sys.executable, "-c", "import bambu; print(bambu._get_config('BAMBU_IP'))"],
                       cwd=SCRIPTS, capture_output=True, text=True, env=os.environ.copy())
    assert r.stdout.strip() == "10.9.9.9"
