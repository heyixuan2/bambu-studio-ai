"""Hyper3D Rodin provider against recorded responses: multipart submit, jobs, file list."""

from pathlib import Path

import pytest

from bambu_studio_ai.generation.errors import ProviderError
from bambu_studio_ai.generation.inputs import load_image
from bambu_studio_ai.generation.ledger import FollowUpLedger
from bambu_studio_ai.generation.pipeline import Generator
from bambu_studio_ai.generation.providers import ProviderSettings, create_provider
from bambu_studio_ai.generation.providers.base import GenerationRequest, TaskRef, TaskState
from bambu_studio_ai.generation.providers.rodin import RodinProvider, parse_file_list, parse_status
from generation_fakes import assert_same_model_stood_up, FakeClock, FakeSession, client, fixture, image_bytes, make_glb

API = "https://api.hyper3d.com/api/v2"
SUBMIT = fixture("rodin/submit")[1]
UUID, KEY = SUBMIT["uuid"], SUBMIT["jobs"]["subscription_key"]
GLB_URL = "https://file.hyper3d.ai/abc/base_basic_pbr.glb"


def generator(session, tmp_path, provider=None):
    clock = FakeClock()
    provider = provider or RodinProvider("rodin_secret", client(session))
    return Generator(provider, output_dir=tmp_path / "models",
                     ledger=FollowUpLedger(tmp_path / "ledger.json"), sleep=clock.sleep, clock=clock)


def test_text_submits_gen_2_5_explicitly_and_resumes_from_one_token(tmp_path):
    model = make_glb(tmp_path / "src.glb")
    session = (FakeSession().on("POST", f"{API}/rodin", "rodin/submit")
               .on("POST", f"{API}/status", "rodin/status_waiting", "rodin/status_generating",
                   "rodin/status_done")
               .on("POST", f"{API}/download", "rodin/download")
               .on("GET", GLB_URL, model))
    gen = generator(session, tmp_path)
    ref = gen.submit(GenerationRequest(prompt="a treasure chest"))
    assert session.posts("/rodin")[0].form == {
        "prompt": "a treasure chest", "tier": "Gen-2.5-Medium", "geometry_file_format": "glb",
        "material": "PBR"}
    # uuid (downloads) and subscription key (status) both live in the printed id.
    assert TaskRef.parse(ref.token).ids == (UUID, KEY)

    result = gen.complete(TaskRef.parse(ref.token), output_format="glb", texture=True,
                          height_mm=None, timeout_s=600)
    status_calls = session.posts("/status")
    assert all(call.json == {"subscription_key": KEY} for call in status_calls)
    assert session.posts("/download")[0].json == {"task_uuid": UUID}
    assert result.status == "succeeded"
    assert_same_model_stood_up(result.output_file, model)


def test_configured_tier_and_stl_output(tmp_path):
    session = FakeSession().on("POST", f"{API}/rodin", "rodin/submit")
    provider = create_provider("rodin", ProviderSettings(
        api_key="k", http=client(session), options={"rodin_tier": "Gen-2.5-High"}))
    generator(session, tmp_path, provider).submit(
        GenerationRequest(prompt="a bracket", output_format="stl", texture=False))
    form = session.posts()[0].form
    assert (form["tier"], form["geometry_file_format"], form["material"]) == (
        "Gen-2.5-High", "stl", "None")


def test_rejection_inside_http_201_is_an_error(tmp_path):
    session = FakeSession().on("POST", f"{API}/rodin", "rodin/submit_insufficient_funds")
    with pytest.raises(ProviderError) as error:
        generator(session, tmp_path).submit(GenerationRequest(prompt="a cat"))
    assert error.value.code == "API_INSUFFICIENT_FUNDS"


def test_image_url_is_fetched_and_uploaded_with_its_real_type(tmp_path):
    png = image_bytes("PNG")
    session = (FakeSession().on("GET", "https://example.com/photo", png)
               .on("POST", f"{API}/rodin", "rodin/submit"))
    generator(session, tmp_path).submit(GenerationRequest(
        prompt="symmetric, sharp", image=load_image("https://example.com/photo")))
    form = session.posts()[0].form
    assert form["images"] == ("photo.png", png, "image/png")
    assert form["prompt"] == "symmetric, sharp"  # Rodin uses the prompt for images


@pytest.mark.parametrize(("name", "state", "progress"), [
    ("rodin/status_waiting", TaskState.QUEUED, 0),
    ("rodin/status_generating", TaskState.RUNNING, 50),
    ("rodin/status_done", TaskState.SUCCEEDED, 100),
    ("rodin/status_failed", TaskState.FAILED, None),
    ("rodin/status_no_such_task", TaskState.EXPIRED, None),
])
def test_every_rodin_job_state_is_normalised(name, state, progress):
    status = parse_status(fixture(name)[1])
    assert (status.state, status.progress) == (state, progress)


def test_queue_position_is_reported():
    assert parse_status(fixture("rodin/status_waiting")[1]).message == "3 jobs ahead in the queue"


def test_download_picks_the_model_not_a_texture_or_preview():
    outputs = parse_file_list(fixture("rodin/download")[1])
    assert outputs == {"glb": "https://file.hyper3d.ai/abc/base_basic_pbr.glb?sig=1"}


def test_malformed_task_id_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="rodin:task:<uuid>:<subscription key>"):
        generator(FakeSession(), tmp_path).status(TaskRef.parse(f"rodin:task:{UUID}"))
