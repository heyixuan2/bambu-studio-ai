"""Waiting, resuming and task ids: a timeout must never submit or pay again."""

import pytest

from bambu_studio_ai.generation.errors import InputError, ProviderError
from bambu_studio_ai.generation.inputs import data_uri, is_url, load_image
from bambu_studio_ai.generation.ledger import FollowUpLedger
from bambu_studio_ai.generation.pipeline import Generator
from bambu_studio_ai.generation.providers.base import GenerationRequest, TaskRef, TaskState, TaskStatus
from bambu_studio_ai.generation.task import wait_for_task
from generation_fakes import FakeClock, FakeProvider, image_bytes, make_glb


def make_generator(provider, tmp_path, clock):
    return Generator(provider, output_dir=tmp_path / "models",
                     ledger=FollowUpLedger(tmp_path / "ledger.json"), sleep=clock.sleep, clock=clock)


def test_poll_timeout_returns_still_running_and_never_resubmits(tmp_path):
    clock = FakeClock()
    provider = FakeProvider(["running"])
    generator = make_generator(provider, tmp_path, clock)
    ref = generator.submit(GenerationRequest(prompt="a slow dragon"))

    result = generator.complete(ref, output_format="glb", texture=True, height_mm=None,
                                timeout_s=120, first_delay_s=5)

    assert result.status == "running"
    assert result.still_running
    assert result.task_id == ref.token
    assert result.output_file is None
    assert len(provider.submitted) == 1  # the one explicit submit, nothing more
    assert clock.now == pytest.approx(120)
    assert provider.polls >= 2


def test_finished_task_is_downloaded_and_measured(tmp_path):
    clock = FakeClock()
    provider = FakeProvider(["queued", "running", "succeeded"], make_glb(tmp_path / "m.glb", (2, 2, 1)))
    generator = make_generator(provider, tmp_path, clock)
    result = generator.complete(generator.submit(GenerationRequest(prompt="a box")),
                                output_format="glb", texture=True, height_mm=40, timeout_s=600)
    assert result.status == "succeeded"
    assert result.extents_mm == pytest.approx((40.0, 20.0, 40.0))  # raw 2×2×1 stood up (2×1×2), Z scaled to 40
    assert result.has_texture is True
    assert len(provider.submitted) == 1


@pytest.mark.parametrize("state", ["failed", "cancelled", "expired", "rejected"])
def test_terminal_failures_stop_waiting_without_resubmitting(tmp_path, state):
    provider = FakeProvider([state])
    generator = make_generator(provider, tmp_path, FakeClock())
    result = generator.complete(generator.submit(GenerationRequest(prompt="x")), output_format="glb",
                                texture=True, height_mm=None, timeout_s=600)
    assert result.status == state
    assert not result.still_running
    assert (len(provider.submitted), provider.polls) == (1, 1)


def test_temporary_poll_errors_are_waited_out():
    clock = FakeClock()
    replies = iter([ProviderError("http_503", "busy", retryable=True),
                    TaskStatus(TaskState.SUCCEEDED)])

    def poll():
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    outcome = wait_for_task(poll, timeout_s=60, interval_s=5, max_interval_s=5,
                            sleep=clock.sleep, clock=clock)
    assert outcome.status.state is TaskState.SUCCEEDED
    assert not outcome.timed_out


def test_permanent_poll_errors_are_raised():
    def poll():
        raise ProviderError("http_401", "bad key")

    with pytest.raises(ProviderError):
        wait_for_task(poll, timeout_s=60, interval_s=5, max_interval_s=5,
                      sleep=FakeClock().sleep, clock=FakeClock())


def test_polling_backs_off_to_the_limit():
    clock = FakeClock()
    outcome = wait_for_task(lambda: TaskStatus(TaskState.RUNNING), timeout_s=100, interval_s=5,
                            max_interval_s=12, sleep=clock.sleep, clock=clock)
    assert outcome.timed_out
    assert clock.slept[:4] == pytest.approx([5, 7.5, 11.25, 12])


@pytest.mark.parametrize("token", [
    "meshy:text:018a210d-8ba4-705c-b111-1f1776f7f578",
    "tripo:convert:task_01J8:stl",
    "rodin:task:123e4567-e89b:eyJhbGciOiJIUzI1NiJ9.eyJ0YXNrIjoiMTIzIn0.c2ln",
])
def test_task_tokens_round_trip(token):
    assert TaskRef.parse(token).token == token


def test_ids_with_unusual_characters_survive_a_round_trip():
    ref = TaskRef("rodin", "task", ("uuid", "key/with+odd:chars=="))
    assert ":" not in ref.token.split(":", 3)[3]
    assert TaskRef.parse(ref.token) == ref


@pytest.mark.parametrize("token", ["bogus", "meshy:text", "../x:y:z", "meshy:text:a/b"])
def test_malformed_tokens_are_rejected(token):
    with pytest.raises(InputError):
        TaskRef.parse(token)


def test_ledger_persists_and_finds_steps_started_from_a_task(tmp_path):
    path = tmp_path / "ledger.json"
    FollowUpLedger(path).record("meshy:text:abc>refine", "meshy:refine:def")
    reloaded = FollowUpLedger(path)
    assert reloaded.get("meshy:text:abc>refine") == "meshy:refine:def"
    assert reloaded.started_from("meshy:text:abc") == "meshy:refine:def"
    assert reloaded.started_from("meshy:text:other") is None


def test_corrupt_ledger_is_ignored(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json")
    assert FollowUpLedger(path).get("x") is None


def test_url_detection_is_not_fooled_by_file_names():
    assert is_url("https://example.com/a.png")
    assert not is_url("httpd_logo.png")
    assert not is_url("file:///etc/passwd")


def test_image_checks(tmp_path):
    (tmp_path / "a.png").write_bytes(image_bytes("PNG"))
    (tmp_path / "notes.txt").write_text("hello")
    image = load_image(str(tmp_path / "a.png"))
    assert image.mime == "image/png"
    assert data_uri(image).startswith("data:image/png;base64,iVBORw0KGgo")
    with pytest.raises(InputError, match="not a PNG"):
        load_image(str(tmp_path / "notes.txt"))
    with pytest.raises(InputError, match="not found"):
        load_image(str(tmp_path / "missing.png"))
