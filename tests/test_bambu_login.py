"""Unit tests for bambu.py Cloud login (CloudBackend).

The login flow is exercised without any real Bambu account: the
``bambulab`` cloud SDK is replaced with an in-memory fake, and the token
cache / verify-code files are redirected to a per-test tmp dir. This lets
us verify token caching, the email-verification-code flow, device
resolution, and the error paths deterministically.
"""

import json
import os
import sys
import time
import types

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

try:
    import bambu
except Exception as _e:  # pragma: no cover - env without cryptography/cffi
    bambu = None
    _import_err = _e

needs_bambu = pytest.mark.skipif(
    bambu is None, reason="bambu.py could not be imported in this environment"
)


def _install_fake_bambulab(monkeypatch):
    """Replace the ``bambulab`` SDK with a configurable in-memory fake.

    Returns a mutable ``state`` dict the test can both configure (login_fn,
    devices, reject_tokens, ...) and inspect (login_calls, client_tokens,
    get_devices_calls).
    """
    state = {
        "login_calls": [],
        "client_tokens": [],
        "get_devices_calls": 0,
        "login_fn": lambda email, password, verify_code: "fresh-token",
        "devices": [{"dev_id": "DEV123", "name": "Test P1S"}],
        "devices_raises": None,
        "reject_tokens": set(),
    }

    class BambuAuthenticator:
        def login(self, email, password, verify_code=None):
            state["login_calls"].append(
                {"email": email, "password": password, "verify_code": verify_code}
            )
            return state["login_fn"](email, password, verify_code)

    class BambuClient:
        def __init__(self, token=None):
            if token in state["reject_tokens"]:
                raise RuntimeError("invalid token")
            self.token = token
            state["client_tokens"].append(token)

        def get_devices(self):
            state["get_devices_calls"] += 1
            if state["devices_raises"] is not None:
                raise state["devices_raises"]
            return state["devices"]

    mod = types.ModuleType("bambulab")
    mod.BambuAuthenticator = BambuAuthenticator
    mod.BambuClient = BambuClient
    monkeypatch.setitem(sys.modules, "bambulab", mod)
    return state


def _cache_path(tmp_path):
    return os.path.join(str(tmp_path), ".token_cache.json")


def _write_cache(tmp_path, token="cached-token", age_seconds=0, email="a@b.com"):
    with open(_cache_path(tmp_path), "w") as f:
        json.dump(
            {"token": token, "timestamp": time.time() - age_seconds, "email": email}, f
        )


@pytest.fixture
def login_env(monkeypatch, tmp_path):
    """Redirect the token cache to tmp, clear login env vars, install fake SDK."""
    monkeypatch.setattr(bambu, "_skill_dir", str(tmp_path))
    for var in ("BAMBU_EMAIL", "BAMBU_PASSWORD", "BAMBU_VERIFY_CODE", "BAMBU_DEVICE_ID"):
        monkeypatch.delenv(var, raising=False)
    state = _install_fake_bambulab(monkeypatch)
    return state, tmp_path


def _creds(monkeypatch, email="user@example.com", password="secret"):
    monkeypatch.setenv("BAMBU_EMAIL", email)
    monkeypatch.setenv("BAMBU_PASSWORD", password)


@needs_bambu
class TestCredentials:
    def test_missing_credentials_exits(self, login_env, monkeypatch, capsys):
        with pytest.raises(SystemExit) as exc:
            bambu.CloudBackend()
        assert exc.value.code == 1
        assert "Missing cloud credentials" in capsys.readouterr().out

    def test_missing_password_only_exits(self, login_env, monkeypatch, capsys):
        monkeypatch.setenv("BAMBU_EMAIL", "user@example.com")
        with pytest.raises(SystemExit):
            bambu.CloudBackend()
        assert "BAMBU_PASSWORD" in capsys.readouterr().out


@needs_bambu
class TestFreshLogin:
    def test_fresh_login_success(self, login_env, monkeypatch, capsys):
        state, tmp_path = login_env
        _creds(monkeypatch)
        backend = bambu.CloudBackend()

        # Authenticator was called once, without a verify code.
        assert len(state["login_calls"]) == 1
        assert state["login_calls"][0]["email"] == "user@example.com"
        assert state["login_calls"][0]["verify_code"] is None
        # Client built with the freshly issued token; device resolved.
        assert backend.client.token == "fresh-token"
        assert backend.device_id == "DEV123"
        assert "Using printer" in capsys.readouterr().out

    def test_token_cache_written_with_600_perms(self, login_env, monkeypatch):
        state, tmp_path = login_env
        _creds(monkeypatch)
        bambu.CloudBackend()

        path = _cache_path(tmp_path)
        assert os.path.exists(path)
        with open(path) as f:
            cached = json.load(f)
        assert cached["token"] == "fresh-token"
        assert cached["email"] == "user@example.com"
        assert oct(os.stat(path).st_mode & 0o777) == "0o600"

    def test_device_id_from_env_skips_device_lookup(self, login_env, monkeypatch):
        state, tmp_path = login_env
        _creds(monkeypatch)
        monkeypatch.setenv("BAMBU_DEVICE_ID", "MYDEV999")
        backend = bambu.CloudBackend()

        assert backend.device_id == "MYDEV999"
        assert state["get_devices_calls"] == 0

    def test_no_devices_found_exits(self, login_env, monkeypatch, capsys):
        state, tmp_path = login_env
        _creds(monkeypatch)
        state["devices"] = []
        with pytest.raises(SystemExit) as exc:
            bambu.CloudBackend()
        assert exc.value.code == 1
        assert "No printers found" in capsys.readouterr().out


@needs_bambu
class TestTokenCache:
    def test_valid_cached_token_reused_without_reauth(self, login_env, monkeypatch, capsys):
        state, tmp_path = login_env
        _creds(monkeypatch)
        _write_cache(tmp_path, token="cached-token", age_seconds=0)

        backend = bambu.CloudBackend()

        # No re-authentication happened.
        assert state["login_calls"] == []
        assert backend.client.token == "cached-token"
        # Regression: device must still be resolved on the cached-token path.
        assert backend.device_id == "DEV123"
        assert "Using cached login token" in capsys.readouterr().out

    def test_expired_cached_token_triggers_reauth(self, login_env, monkeypatch, capsys):
        state, tmp_path = login_env
        _creds(monkeypatch)
        _write_cache(
            tmp_path, token="old-token", age_seconds=bambu.TOKEN_TTL_SECONDS + 100
        )

        backend = bambu.CloudBackend()

        assert len(state["login_calls"]) == 1
        assert backend.client.token == "fresh-token"
        assert "expired" in capsys.readouterr().out.lower()

    def test_invalid_cached_token_falls_back_to_reauth(self, login_env, monkeypatch, capsys):
        state, tmp_path = login_env
        _creds(monkeypatch)
        _write_cache(tmp_path, token="cached-token", age_seconds=0)
        # Reject the cached token at client construction -> forces re-auth.
        state["reject_tokens"] = {"cached-token"}

        backend = bambu.CloudBackend()

        assert len(state["login_calls"]) == 1
        assert backend.client.token == "fresh-token"
        assert "re-authenticating" in capsys.readouterr().out.lower()


@needs_bambu
class TestVerificationCode:
    @staticmethod
    def _needs_code_login(email, password, verify_code):
        if not verify_code:
            raise RuntimeError("Please enter the verification code from your email")
        return "verified-token"

    def test_verify_code_required_without_code_exits(self, login_env, monkeypatch, capsys):
        state, tmp_path = login_env
        _creds(monkeypatch)
        state["login_fn"] = self._needs_code_login

        with pytest.raises(SystemExit) as exc:
            bambu.CloudBackend()
        assert exc.value.code == 1
        assert "Verification code required" in capsys.readouterr().out

    def test_verify_code_from_env(self, login_env, monkeypatch):
        state, tmp_path = login_env
        _creds(monkeypatch)
        state["login_fn"] = self._needs_code_login
        monkeypatch.setenv("BAMBU_VERIFY_CODE", "123456")

        backend = bambu.CloudBackend()

        assert len(state["login_calls"]) == 2
        assert state["login_calls"][0]["verify_code"] is None
        assert state["login_calls"][1]["verify_code"] == "123456"
        assert backend.client.token == "verified-token"

    def test_verify_code_from_file_is_one_time(self, login_env, monkeypatch, tmp_path):
        state, tmp_path = login_env
        _creds(monkeypatch)
        state["login_fn"] = self._needs_code_login
        verify_file = os.path.join(str(tmp_path), ".verify_code")
        with open(verify_file, "w") as f:
            f.write("654321\n")

        backend = bambu.CloudBackend()

        assert state["login_calls"][1]["verify_code"] == "654321"
        assert backend.client.token == "verified-token"
        # Consumed after use so a stale code is not reused.
        assert not os.path.exists(verify_file)


@needs_bambu
class TestLoginFailure:
    def test_bad_credentials_exits(self, login_env, monkeypatch, capsys):
        state, tmp_path = login_env
        _creds(monkeypatch)

        def _bad(email, password, verify_code):
            raise RuntimeError("Invalid username or password")

        state["login_fn"] = _bad
        with pytest.raises(SystemExit) as exc:
            bambu.CloudBackend()
        assert exc.value.code == 1
        assert "Cloud login failed" in capsys.readouterr().out
