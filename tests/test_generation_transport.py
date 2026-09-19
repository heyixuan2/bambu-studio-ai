"""HttpClient retry/timeout/error rules and safe downloads (bambu_studio_ai.generation)."""

import pytest
import requests

from bambu_studio_ai.generation.download import download_file, safe_filename, sniff_problem
from bambu_studio_ai.generation.errors import ProviderError
from generation_fakes import FakeSession, client, make_glb, make_response

URL = "https://api.example.test/v1/thing"
FILE_URL = "https://cdn.example.test/model.glb"


def test_every_request_has_a_timeout():
    session = FakeSession().on("GET", URL, (200, {"ok": 1})).on("POST", URL, (200, {"ok": 2}))
    http = client(session)
    http.get_json(URL)
    http.post_json(URL, json={})
    assert all(call.kwargs["timeout"] for call in session.calls)


def test_get_is_retried_after_a_server_error():
    session = FakeSession().on("GET", URL, (503, {"message": "busy"}), (200, {"ok": True}))
    assert client(session).get_json(URL) == {"ok": True}
    assert len(session.calls) == 2


def test_get_is_retried_after_a_dropped_connection():
    session = FakeSession().on("GET", URL, requests.ConnectionError("reset"), (200, {"ok": True}))
    assert client(session).get_json(URL) == {"ok": True}


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429])
def test_4xx_is_never_retried(status):
    session = FakeSession().on("GET", URL, (status, {"message": "nope"}), (200, {"ok": True}))
    with pytest.raises(ProviderError) as error:
        client(session).get_json(URL)
    assert len(session.calls) == 1
    assert error.value.http_status == status


def test_post_is_never_retried_even_on_a_server_error():
    # A lost reply to a generation request may still have spent credits.
    session = FakeSession().on("POST", URL, (500, {"message": "oops"}), (200, {"result": "x"}))
    with pytest.raises(ProviderError) as error:
        client(session).post_json(URL, json={"prompt": "a cat"})
    assert len(session.calls) == 1
    assert error.value.retryable


def test_gives_up_after_the_retry_budget():
    session = FakeSession().on("GET", URL, (502, {"message": "bad gateway"}))
    with pytest.raises(ProviderError) as error:
        client(session).get_json(URL)
    assert len(session.calls) == 3
    assert error.value.code == "http_502"


@pytest.mark.parametrize(("name", "code", "text"), [
    ("meshy/error_401", "http_401", "Missing API key"),
    ("meshy/error_402", "http_402", "Insufficient funds"),
    ("tripo/error_2010", "2010", "Insufficient credits. Please top up your account"),
    ("tripo/error_401", "2", "Authentication required"),
    ("rodin/error_401", "UNAUTHORIZED", "Active API key is required."),
])
def test_vendor_error_bodies_are_surfaced(name, code, text):
    session = FakeSession().on("POST", URL, name)
    with pytest.raises(ProviderError) as error:
        client(session).post_json(URL, json={})
    assert error.value.code == code
    assert text in error.value.message
    assert not error.value.retryable


def test_download_writes_the_file_atomically(tmp_path):
    model = make_glb(tmp_path / "source.glb")
    session = FakeSession().on("GET", FILE_URL, model)
    dest = download_file(client(session), lambda: FILE_URL, tmp_path / "out" / "m.glb", expected="glb")
    assert dest.read_bytes() == model
    assert not list((tmp_path / "out").glob("*.tmp"))
    assert "Authorization" not in (session.calls[0].kwargs.get("headers") or {})


def test_expired_link_is_replaced_with_a_fresh_one(tmp_path):
    model = make_glb(tmp_path / "source.glb")
    fresh = "https://cdn.example.test/model.glb?sig=new"
    session = FakeSession().on("GET", FILE_URL, (403, {"message": "expired"})).on("GET", fresh, model)
    urls = iter([FILE_URL, fresh])
    dest = download_file(client(session), lambda: next(urls), tmp_path / "m.glb", expected="glb")
    assert dest.read_bytes() == model
    assert [call.url for call in session.calls] == [FILE_URL, fresh]


def test_truncated_download_leaves_nothing_behind(tmp_path):
    short = make_glb(tmp_path / "source.glb")[:100]
    response = make_response(200, content=short, headers={"Content-Length": "5000"})
    session = FakeSession().on("GET", FILE_URL, response)
    with pytest.raises(ProviderError) as error:
        download_file(client(session), lambda: FILE_URL, tmp_path / "m.glb", expected="glb")
    assert error.value.code == "truncated"
    assert list(tmp_path.glob("m.glb*")) == []


def test_html_error_page_is_not_saved_as_a_model(tmp_path):
    page = b"<html><body>AccessDenied</body></html>"
    session = FakeSession().on("GET", FILE_URL, page)
    with pytest.raises(ProviderError) as error:
        download_file(client(session), lambda: FILE_URL, tmp_path / "m.glb", expected="glb")
    assert error.value.code == "not_a_model"
    assert not (tmp_path / "m.glb").exists()


def test_sniffing_recognises_each_format(tmp_path):
    ascii_stl = tmp_path / "a.stl"
    ascii_stl.write_text("solid x\nfacet normal 0 0 1\nendsolid x\n")
    obj = tmp_path / "a.obj"
    obj.write_text("# made by a provider\nmtllib model.mtl\nv 0 0 0\n")
    zip_like = tmp_path / "a.3mf"
    zip_like.write_bytes(b"PK\x03\x04rest")
    assert sniff_problem(ascii_stl, "stl") is None
    assert sniff_problem(obj, "obj") is None
    assert sniff_problem(zip_like, "3mf") is None
    assert sniff_problem(zip_like, "glb") is not None


@pytest.mark.parametrize(("stem", "expected"), [
    ("../../etc/passwd", "etc_passwd.glb"),
    ("meshy_018a210d-8ba4", "meshy_018a210d-8ba4.glb"),
    ("a/b\\c:d", "a_b_c_d.glb"),
    ("", "model.glb"),
])
def test_file_names_cannot_escape_the_output_folder(stem, expected):
    assert safe_filename(stem, "glb") == expected
