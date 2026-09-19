"""Tripo v3 provider against recorded responses: submit, upload, poll, convert, download."""

from pathlib import Path

import pytest

from bambu_studio_ai.generation import scale
from bambu_studio_ai.generation.errors import ProviderError
from bambu_studio_ai.generation.inputs import load_image
from bambu_studio_ai.generation.ledger import FollowUpLedger
from bambu_studio_ai.generation.pipeline import Generator
from bambu_studio_ai.generation.providers.base import GenerationRequest, TaskRef, TaskState
from bambu_studio_ai.generation.providers.tripo import TripoProvider, parse_task
from generation_fakes import FakeClock, FakeSession, client, fixture, image_bytes, make_glb

V3 = "https://openapi.tripo3d.ai/v3"
TASK = fixture("tripo/create_task")[1]["data"]["task_id"]
CONV = fixture("tripo/create_convert")[1]["data"]["task_id"]
GLB_URL = f"https://cdn.tripo3d.ai/output/{TASK}/model_pbr.glb"
STL_URL = f"https://cdn.tripo3d.ai/output/{CONV}/model.stl"


def generator(session, tmp_path):
    clock = FakeClock()
    return Generator(TripoProvider("tsk_secret", client(session)), output_dir=tmp_path / "models",
                     ledger=FollowUpLedger(tmp_path / "ledger.json"), sleep=clock.sleep, clock=clock)


def test_text_to_model_uses_v3_and_the_current_model(tmp_path):
    model = make_glb(tmp_path / "src.glb", (0.8, 0.6, 1.0))
    session = (FakeSession()
               .on("POST", f"{V3}/generation/text-to-model", "tripo/create_task")
               .on("GET", f"{V3}/tasks/{TASK}", "tripo/task_queued", "tripo/task_running",
                   "tripo/task_success")
               .on("GET", GLB_URL, model))
    gen = generator(session, tmp_path)
    ref = gen.submit(GenerationRequest(prompt="a campfire ring"))
    result = gen.complete(ref, output_format="glb", texture=True, height_mm=None, timeout_s=300)

    body = session.posts()[0].json
    assert body == {"prompt": "a campfire ring", "model": "v3.1-20260211"}
    assert "type" not in body  # the v2 'type' field is gone in v3
    assert session.calls[0].kwargs["headers"] == {"Authorization": "Bearer tsk_secret"}
    assert ref.token == f"tripo:task:{TASK}"
    assert result.status == "succeeded"
    assert Path(result.output_file).read_bytes() == model
    assert result.has_texture is True


def test_no_texture_turns_off_texture_and_pbr(tmp_path):
    session = FakeSession().on("POST", f"{V3}/generation/text-to-model", "tripo/create_task")
    generator(session, tmp_path).submit(
        GenerationRequest(prompt="a hook", texture=False, model="v3.0-20250812"))
    assert session.posts()[0].json == {
        "prompt": "a hook", "model": "v3.0-20250812", "texture": False, "pbr": False}


def test_local_image_is_uploaded_then_referenced_by_token(tmp_path):
    (tmp_path / "toy.jpg").write_bytes(image_bytes("JPEG"))
    session = (FakeSession().on("POST", f"{V3}/files", "tripo/upload")
               .on("POST", f"{V3}/generation/image-to-model", "tripo/create_task"))
    generator(session, tmp_path).submit(
        GenerationRequest(prompt="unused", image=load_image(str(tmp_path / "toy.jpg"))))
    upload, create = session.posts()
    filename, data, mime = upload.form["file"]
    assert (filename, mime) == ("toy.jpg", "image/jpeg")
    assert data == (tmp_path / "toy.jpg").read_bytes()
    assert create.json == {"input": "file_01J8ZKQ4UPLOAD", "model": "v3.1-20260211"}


def test_image_url_goes_straight_into_input(tmp_path):
    session = FakeSession().on("POST", f"{V3}/generation/image-to-model", "tripo/create_task")
    generator(session, tmp_path).submit(
        GenerationRequest(prompt=None, image=load_image("https://example.com/toy.png")))
    assert [call.url for call in session.posts()] == [f"{V3}/generation/image-to-model"]
    assert session.posts()[0].json["input"] == "https://example.com/toy.png"


@pytest.mark.parametrize(("name", "state"), [
    ("tripo/task_queued", TaskState.QUEUED),
    ("tripo/task_running", TaskState.RUNNING),
    ("tripo/task_success", TaskState.SUCCEEDED),
    ("tripo/task_failed", TaskState.FAILED),
    ("tripo/task_cancelled", TaskState.CANCELLED),
    ("tripo/task_banned", TaskState.REJECTED),
    ("tripo/task_expired", TaskState.EXPIRED),
    ("tripo/task_unknown", TaskState.FAILED),
])
def test_every_tripo_status_is_normalised(name, state):
    status = parse_task(fixture(name)[1]["data"])
    assert status.state is state
    if state not in (TaskState.QUEUED, TaskState.RUNNING, TaskState.SUCCEEDED):
        assert status.message  # the user is told why


def test_failed_task_reports_tripo_error():
    status = parse_task(fixture("tripo/task_failed")[1]["data"])
    assert status.message == "Model too complex (error 2018)"


def test_success_lists_the_glb_url():
    status = parse_task(fixture("tripo/task_success")[1]["data"])
    assert status.outputs["glb"].startswith(GLB_URL)
    assert status.progress == 100


def test_stl_is_made_by_tripo_convert(tmp_path):
    source = tmp_path / "src.glb"
    make_glb(source, (30.0, 20.0, 10.0), textured=False)
    scale.convert_glb_locally(source, tmp_path / "src.stl", "stl")
    session = (FakeSession()
               .on("GET", f"{V3}/tasks/{TASK}", "tripo/task_success")
               .on("POST", f"{V3}/models/convert", "tripo/create_convert")
               .on("GET", f"{V3}/tasks/{CONV}", "tripo/task_running", "tripo/convert_success")
               .on("GET", STL_URL, (tmp_path / "src.stl").read_bytes()))
    result = generator(session, tmp_path).complete(
        TaskRef.parse(f"tripo:task:{TASK}"), output_format="stl", texture=False, height_mm=None,
        timeout_s=300)
    assert session.posts()[0].json == {"input": TASK, "format": "STL"}
    assert result.task_id == f"tripo:convert:{CONV}:stl"
    assert result.output_format == "stl"
    assert result.extents_mm == pytest.approx((30.0, 20.0, 10.0))


def test_expired_download_link_is_refreshed_from_the_task(tmp_path):
    model = make_glb(tmp_path / "src.glb")
    session = (FakeSession()
               .on("GET", f"{V3}/tasks/{TASK}", "tripo/task_success")
               .on("GET", GLB_URL, (403, {"message": "Request has expired"}), model))
    result = generator(session, tmp_path).complete(
        TaskRef.parse(f"tripo:task:{TASK}"), output_format="glb", texture=True, height_mm=None,
        timeout_s=60)
    assert result.status == "succeeded"
    assert len(session.gets("/tasks/")) == 3  # wait, first download listing, refresh after 403


def test_insufficient_credits_is_reported_and_not_retried(tmp_path):
    session = FakeSession().on("POST", f"{V3}/generation/text-to-model", "tripo/error_2010")
    with pytest.raises(ProviderError) as error:
        generator(session, tmp_path).submit(GenerationRequest(prompt="a cat"))
    assert error.value.code == "2010"
    assert "top up" in error.value.message
    assert len(session.calls) == 1


def test_error_envelope_inside_http_200_is_an_error(tmp_path):
    session = FakeSession().on("POST", f"{V3}/generation/text-to-model",
                               (200, {"code": 2002, "message": "Unsupported parameter"}))
    with pytest.raises(ProviderError, match="Unsupported parameter"):
        generator(session, tmp_path).submit(GenerationRequest(prompt="a cat"))
