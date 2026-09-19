"""Meshy provider against recorded responses: preview → refine → download, images, statuses."""

import base64
import json
from pathlib import Path

import pytest

from bambu_studio_ai.generation import scale
from bambu_studio_ai.generation.errors import InputError
from bambu_studio_ai.generation.inputs import load_image
from bambu_studio_ai.generation.ledger import FollowUpLedger
from bambu_studio_ai.generation.pipeline import Generator
from bambu_studio_ai.generation.providers.base import GenerationRequest, TaskRef, TaskState
from bambu_studio_ai.generation.providers.meshy import MeshyProvider, parse_task
from generation_fakes import FakeClock, FakeSession, client, fixture, image_bytes, make_glb

T2 = "https://api.meshy.ai/openapi/v2/text-to-3d"
I2 = "https://api.meshy.ai/openapi/v1/image-to-3d"
CONVERT = "https://api.meshy.ai/openapi/v1/convert"
PREVIEW = fixture("meshy/create_preview")[1]["result"]
REFINE = fixture("meshy/create_refine")[1]["result"]
IMAGE = fixture("meshy/create_image")[1]["result"]
CONVERTED = fixture("meshy/create_convert")[1]["result"]


def asset(task, ext):
    return f"https://assets.meshy.ai/abc/tasks/{task}/output/model.{ext}"


def generator(session, tmp_path):
    clock = FakeClock()
    return Generator(MeshyProvider("msy_secret", client(session)), output_dir=tmp_path / "models",
                     ledger=FollowUpLedger(tmp_path / "ledger.json"), sleep=clock.sleep, clock=clock)


def test_text_runs_preview_then_refine_and_keeps_the_textured_glb(tmp_path):
    model = make_glb(tmp_path / "src.glb", (1.5, 1.0, 2.0))
    session = (FakeSession()
               .on("POST", T2, "meshy/create_preview", "meshy/create_refine")
               .on("GET", f"{T2}/{PREVIEW}", "meshy/preview_pending", "meshy/preview_in_progress",
                   "meshy/preview_succeeded")
               .on("GET", f"{T2}/{REFINE}", "meshy/refine_succeeded")
               .on("GET", asset(REFINE, "glb"), model))
    gen = generator(session, tmp_path)

    ref = gen.submit(GenerationRequest(prompt="a fireplace mantel"))
    result = gen.complete(ref, output_format="glb", texture=True, height_mm=None, timeout_s=600)

    assert ref.token == f"meshy:text:{PREVIEW}"
    preview, refine = (call.json for call in session.posts())
    # The prompt goes out exactly as written: no rewriting, no art_style.
    assert preview == {"mode": "preview", "prompt": "a fireplace mantel", "ai_model": "latest"}
    assert refine == {"mode": "refine", "preview_task_id": PREVIEW}
    assert session.calls[0].kwargs["headers"] == {"Authorization": "Bearer msy_secret"}
    assert result.status == "succeeded"
    assert result.task_id == f"meshy:refine:{REFINE}"
    assert result.has_texture is True
    assert result.extents_mm == pytest.approx((1.5, 1.0, 2.0))
    assert Path(result.output_file).read_bytes() == model  # untouched without --height


def test_resuming_after_the_refine_started_does_not_pay_again(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    FollowUpLedger(ledger_path).record(f"meshy:text:{PREVIEW}>refine", f"meshy:refine:{REFINE}")
    session = (FakeSession()
               .on("GET", f"{T2}/{PREVIEW}", "meshy/preview_succeeded")
               .on("GET", f"{T2}/{REFINE}", "meshy/refine_succeeded")
               .on("GET", asset(REFINE, "glb"), make_glb(tmp_path / "src.glb")))
    result = generator(session, tmp_path).complete(
        TaskRef.parse(f"meshy:text:{PREVIEW}"), output_format="glb", texture=True, height_mm=None,
        timeout_s=60)
    assert result.status == "succeeded"
    assert session.posts() == []


def test_no_texture_skips_the_refine(tmp_path):
    session = (FakeSession().on("POST", T2, "meshy/create_preview")
               .on("GET", f"{T2}/{PREVIEW}", "meshy/preview_succeeded")
               .on("GET", asset(PREVIEW, "glb"), make_glb(tmp_path / "src.glb", textured=False)))
    gen = generator(session, tmp_path)
    ref = gen.submit(GenerationRequest(prompt="a hook", texture=False))
    result = gen.complete(ref, output_format="glb", texture=False, height_mm=None, timeout_s=60)
    assert ref.kind == "preview"
    assert len(session.posts()) == 1
    assert result.has_texture is False


def test_stl_comes_from_meshy_itself(tmp_path):
    source = tmp_path / "src.glb"
    make_glb(source, (10.0, 10.0, 4.0), textured=False)
    scale.convert_glb_locally(source, tmp_path / "src.stl", "stl")
    session = (FakeSession().on("GET", f"{T2}/{PREVIEW}", "meshy/preview_succeeded")
               .on("GET", asset(PREVIEW, "stl"), (tmp_path / "src.stl").read_bytes()))
    result = generator(session, tmp_path).complete(
        TaskRef.parse(f"meshy:preview:{PREVIEW}"), output_format="stl", texture=False,
        height_mm=None, timeout_s=60)
    assert result.output_format == "stl"
    assert result.output_file.endswith(f"meshy_{PREVIEW}.stl")
    assert result.extents_mm == pytest.approx((10.0, 10.0, 4.0))
    assert any("no colour" in warning for warning in result.warnings)
    assert not any("converted locally" in warning for warning in result.warnings)


def test_3mf_is_requested_at_submit_time(tmp_path):
    session = FakeSession().on("POST", T2, "meshy/create_preview")
    generator(session, tmp_path).submit(
        GenerationRequest(prompt="a vase", output_format="3mf", texture=False))
    assert session.posts()[0].json["target_formats"] == ["glb", "3mf"]


def test_missing_3mf_uses_meshy_convert_once(tmp_path):
    source = tmp_path / "src.glb"
    make_glb(source, textured=False)
    scale.convert_glb_locally(source, tmp_path / "src.3mf", "3mf")
    session = (FakeSession()
               .on("GET", f"{T2}/{PREVIEW}", "meshy/preview_succeeded")
               .on("POST", CONVERT, "meshy/create_convert")
               .on("GET", f"{CONVERT}/{CONVERTED}", "meshy/convert_succeeded")
               .on("GET", asset(CONVERTED, "3mf"), (tmp_path / "src.3mf").read_bytes()))
    result = generator(session, tmp_path).complete(
        TaskRef.parse(f"meshy:preview:{PREVIEW}"), output_format="3mf", texture=False,
        height_mm=None, timeout_s=60)
    assert session.posts()[0].json == {"input_task_id": PREVIEW, "target_formats": ["3mf"]}
    assert result.task_id == f"meshy:convert:{CONVERTED}"
    assert result.output_format == "3mf"


def test_local_image_is_sent_as_a_data_uri(tmp_path):
    png = image_bytes("PNG")
    (tmp_path / "cat.png").write_bytes(png)
    session = FakeSession().on("POST", I2, "meshy/create_image")
    ref = generator(session, tmp_path).submit(
        GenerationRequest(prompt="ignored", image=load_image(str(tmp_path / "cat.png"))))
    body = session.posts()[0].json
    prefix = "data:image/png;base64,"
    assert body["image_url"].startswith(prefix)
    assert base64.b64decode(body["image_url"][len(prefix):]) == png
    assert body["should_texture"] is True
    assert "prompt" not in body and "texture_prompt" not in body  # Meshy image-to-3D has no prompt
    assert ref.token == f"meshy:image:{IMAGE}"
    assert session.posts("/files") == []  # there is no Meshy upload endpoint


def test_image_url_is_passed_through(tmp_path):
    session = FakeSession().on("POST", I2, "meshy/create_image")
    generator(session, tmp_path).submit(
        GenerationRequest(prompt=None, image=load_image("https://example.com/cat.jpg")))
    assert session.posts()[0].json["image_url"] == "https://example.com/cat.jpg"


def test_webp_is_rejected_before_any_request(tmp_path):
    (tmp_path / "cat.webp").write_bytes(image_bytes("WEBP"))
    session = FakeSession()
    with pytest.raises(InputError, match="PNG or JPEG"):
        generator(session, tmp_path).submit(
            GenerationRequest(prompt=None, image=load_image(str(tmp_path / "cat.webp"))))
    assert session.calls == []


@pytest.mark.parametrize(("name", "state", "progress"), [
    ("meshy/preview_pending", TaskState.QUEUED, 0),
    ("meshy/preview_in_progress", TaskState.RUNNING, 55),
    ("meshy/preview_succeeded", TaskState.SUCCEEDED, 100),
    ("meshy/task_failed", TaskState.FAILED, 0),
    ("meshy/task_canceled", TaskState.CANCELLED, 0),
])
def test_every_meshy_status_is_normalised(name, state, progress):
    status = parse_task(fixture(name)[1])
    assert (status.state, status.progress) == (state, progress)
    assert status.state.terminal is (state not in (TaskState.QUEUED, TaskState.RUNNING))


def test_failure_reason_is_kept():
    status = parse_task(fixture("meshy/task_failed")[1])
    assert status.message == "The uploaded image is too complex for 3D generation."


def test_unrecognised_status_keeps_polling_but_says_so():
    status = parse_task({"status": "PAUSED", "progress": 10})
    assert status.state is TaskState.RUNNING
    assert "PAUSED" in status.message


def test_status_never_starts_the_refine(tmp_path):
    session = FakeSession().on("GET", f"{T2}/{PREVIEW}", "meshy/preview_succeeded")
    result = generator(session, tmp_path).status(TaskRef.parse(f"meshy:text:{PREVIEW}"))
    assert result.status == "succeeded"
    assert "`download` starts the Meshy texture step" in result.message
    assert session.posts() == []
    assert json.loads(json.dumps(result.to_dict()))["task_id"] == f"meshy:text:{PREVIEW}"
