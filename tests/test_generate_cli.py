"""generate.py: CLI contract (exit codes, --json purity, removed flags, key lookup)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import generate
from generation_fakes import FakeProvider, image_bytes, make_glb

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPTS / "generate.py"), *args],
                          capture_output=True, encoding="utf-8", timeout=30, env=os.environ.copy())


@pytest.mark.parametrize("args", [["--help"], ["text", "--help"], ["image", "--help"],
                                  ["status", "--help"], ["download", "--help"]])
def test_help(args):
    result = _run(*args)
    assert result.returncode == 0
    assert "usage:" in result.stdout


def test_no_subcommand_is_a_usage_error():
    assert _run().returncode == 2


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """Route generate.py to a FakeProvider (states set per test) with a key configured."""
    provider = FakeProvider(["succeeded"], make_glb(tmp_path / "model.glb", (20.0, 10.0, 30.0)))
    provider.poll_interval_s = provider.max_poll_interval_s = 0.01
    monkeypatch.setenv("BAMBU_3D_API_KEY", "msy_do_not_print_me")
    monkeypatch.setattr(generate, "create_provider", lambda name, settings: provider)
    return provider


def _json(capsys):
    captured = capsys.readouterr()
    return json.loads(captured.out), captured  # json.loads fails if stdout holds anything else


def test_submit_json_is_one_document_and_names_the_resume_command(fake, capsys):
    assert generate.main(["text", "a fireplace mantel", "--json"]) == generate.EXIT_OK
    data, captured = _json(capsys)
    assert data["task_id"] == "meshy:image:task-1"
    assert data["status"] == "submitted"
    assert data["next_command"] == "python3 scripts/generate.py download meshy:image:task-1"
    assert "Submitted to meshy" in captured.err
    assert fake.submitted[0].prompt == "a fireplace mantel"  # sent unchanged
    assert "msy_do_not_print_me" not in captured.out + captured.err


def test_wait_json_reports_the_file(fake, capsys):
    assert generate.main(["text", "a box", "--wait", "--height", "60", "--json"]) == 0
    data, captured = _json(capsys)
    assert data["status"] == "succeeded"
    assert data["provider"] == "meshy"
    assert Path(data["output_file"]).is_file()
    assert data["extents_mm"] == [40.0, 20.0, 60.0]
    assert data["has_texture"] is True
    assert data["format"] == "glb"
    assert f"➡️ Use this file: {data['output_file']}" in captured.err


def test_human_output_ends_with_the_file_to_use(fake, capsys):
    assert generate.main(["text", "a box", "--wait"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1].startswith("➡️ Use this file: ")
    assert out[-1].endswith(".glb")


def test_timeout_is_not_a_failure_and_never_resubmits(fake, capsys):
    fake.states = ["running"]
    code = generate.main(["text", "a slow dragon", "--wait", "--timeout", "0.05",
                          "--format", "stl", "--height", "60", "--json"])
    data, captured = _json(capsys)
    assert code == generate.EXIT_OK
    assert data["status"] == "running"
    assert data["output_file"] is None
    assert data["next_command"] == ("python3 scripts/generate.py download meshy:image:task-1 "
                                    "--format stl --height 60")
    assert "nothing was resubmitted" in captured.err
    assert len(fake.submitted) == 1


def test_failed_task_exits_1(fake, capsys):
    fake.states = ["failed"]
    assert generate.main(["download", "meshy:image:task-1", "--json"]) == generate.EXIT_FAILED
    assert _json(capsys)[0]["status"] == "failed"
    assert fake.submitted == []  # download never submits


def test_status_json(fake, capsys):
    fake.states = ["running"]
    assert generate.main(["status", "meshy:image:task-1", "--json"]) == 0
    data, _ = _json(capsys)
    assert (data["status"], data["progress"]) == ("running", 50)


def test_image_prompt_that_the_provider_ignores_is_flagged(fake, capsys, tmp_path):
    (tmp_path / "cat.png").write_bytes(image_bytes())
    assert generate.main(["image", str(tmp_path / "cat.png"), "--prompt", "blue", "--json"]) == 0
    data, captured = _json(capsys)
    assert data["prompt_used"] is False
    assert "--prompt was not sent" in captured.err


def test_missing_key_is_exit_2_before_any_request(monkeypatch, capsys):
    monkeypatch.setattr(generate, "create_provider", lambda *a: pytest.fail("provider built"))
    assert generate.main(["text", "a cat", "--json"]) == generate.EXIT_CONFIG
    data, captured = _json(capsys)
    assert data["error"]["type"] == "not_configured"
    assert "configure.py secret meshy_api_key" in captured.err


def test_missing_image_is_exit_2(fake, capsys):
    assert generate.main(["image", "no-such-photo.png", "--json"]) == generate.EXIT_CONFIG
    assert _json(capsys)[0]["error"]["type"] == "bad_input"
    assert fake.submitted == []


@pytest.mark.parametrize("args", [["--raw"], ["--auto-retry", "2"], ["--style", "sculpture"],
                                  ["--no-bg-remove"], ["--auto-retry=1"]])
def test_removed_flags_explain_and_exit_2(args, capsys):
    assert generate.main(["text", "a cat", *args]) == generate.EXIT_CONFIG
    assert "was removed" in capsys.readouterr().err


@pytest.mark.parametrize("name", ["printpal", "3daistudio"])
def test_removed_providers_explain_and_exit_2(name, monkeypatch, capsys):
    monkeypatch.setenv("BAMBU_3D_PROVIDER", name)
    monkeypatch.setenv("BAMBU_3D_API_KEY", "k")
    assert generate.main(["text", "a cat"]) == generate.EXIT_CONFIG
    assert "was removed" in capsys.readouterr().err


def test_bad_task_id_is_exit_2(capsys):
    assert generate.main(["status", "018a210d-8ba4", "--json"]) == generate.EXIT_CONFIG
    assert _json(capsys)[0]["error"]["type"] == "bad_input"


def test_key_lookup_order(monkeypatch):
    config = {"tripo_api_key": "tripo-key", "3d_api_key": "shared-key"}
    assert generate.api_key("tripo", config) == "tripo-key"
    assert generate.api_key("meshy", config) == "shared-key"
    monkeypatch.setenv("BAMBU_3D_API_KEY", "env-key")
    assert generate.api_key("tripo", config) == "env-key"


def test_configure_offers_only_supported_providers():
    result = subprocess.run([sys.executable, str(SCRIPTS / "configure.py"), "set", "3d_provider", "printpal"],
                            capture_output=True, encoding="utf-8", timeout=30, env=os.environ.copy())
    assert result.returncode == 2
    assert "meshy, tripo, rodin" in result.stdout + result.stderr
