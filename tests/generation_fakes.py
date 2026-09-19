"""Test doubles for bambu_studio_ai.generation: replayed HTTP, fake clock, sample models.

Provider tests replay the recorded/documented responses in tests/fixtures/generation/
through the real HttpClient, so request building and response parsing are both tested
without the network.
"""

import io
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from requests.structures import CaseInsensitiveDict

from bambu_studio_ai.generation import glb
from bambu_studio_ai.generation.http import HttpClient
from bambu_studio_ai.generation.providers.base import Fetched, TaskRef, TaskState, TaskStatus

FIXTURES = Path(__file__).parent / "fixtures" / "generation"


def fixture(name):
    """(status, body) of tests/fixtures/generation/<name>.json."""
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return data["status"], data["body"]


def make_response(status=200, body=None, *, content=None, headers=None, url="https://example.test/"):
    """A real requests.Response carrying a JSON body or raw bytes."""
    response = requests.Response()
    response.status_code = status
    response.reason = "OK" if status < 400 else "Error"
    response._content = content if content is not None else json.dumps(body).encode()
    response._content_consumed = True
    default = {"Content-Type": "application/json"} if content is None else {}
    response.headers = CaseInsensitiveDict(headers if headers is not None else default)
    response.url = url
    response.encoding = "utf-8"
    return response


@dataclass
class Call:
    method: str
    url: str
    kwargs: dict

    @property
    def json(self):
        return self.kwargs.get("json")

    @property
    def form(self):
        """Multipart fields as {name: value-or-(filename, bytes, mime)}."""
        fields = {}
        for name, (filename, value, mime) in self.kwargs.get("files") or []:
            fields[name] = value if filename is None else (filename, value, mime)
        return fields


@dataclass
class FakeSession:
    """Stands in for requests.Session: replies are queued per (method, URL without query).

    A reply is a fixture name, a (status, body) tuple, raw bytes (a file download),
    a requests.Response, or an exception to raise. The last reply repeats.
    """

    routes: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def on(self, method, url, *replies):
        self.routes.setdefault((method, url), []).extend(replies)
        return self

    def request(self, method, url, **kwargs):
        self.calls.append(Call(method, url, kwargs))
        queue = self.routes.get((method, url)) or self.routes.get((method, url.split("?", 1)[0]))
        if not queue:
            raise AssertionError(f"unexpected request: {method} {url}")
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, requests.Response):
            return reply
        if isinstance(reply, bytes):
            return make_response(200, content=reply, headers={"Content-Length": str(len(reply))}, url=url)
        status, body = fixture(reply) if isinstance(reply, str) else reply
        return make_response(status, body, url=url)

    def posts(self, url_part=""):
        return [call for call in self.calls if call.method == "POST" and url_part in call.url]

    def gets(self, url_part=""):
        return [call for call in self.calls if call.method == "GET" and url_part in call.url]


def client(session):
    """An HttpClient over a FakeSession that never really sleeps."""
    return HttpClient(session, sleep=lambda _seconds: None)


class FakeClock:
    """monotonic() and sleep() that advance together, so waits take no real time."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def image_bytes(fmt="PNG", size=(300, 300)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 60, 40)).save(buffer, fmt)
    return buffer.getvalue()


def make_glb(path, extents=(20.0, 20.0, 10.0), *, textured=True, root_scale=None):
    """Write a box GLB with the given raw X, Y, Z extents; return its bytes."""
    half = np.array(extents, dtype=np.float32) / 2
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], dtype=np.float32)
    positions = (corners * half).astype("<f4")
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    indices = np.array(faces, dtype="<u2").ravel()
    png = image_bytes(size=(4, 4)) if textured else b""
    blobs = [positions.tobytes(), indices.tobytes(), png]
    views, binary = [], b""
    for blob in blobs:
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(blob)})
        binary += blob + b"\0" * (-len(blob) % 4)
    primitive = {"attributes": {"POSITION": 0}, "indices": 1}
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views[: 3 if textured else 2],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
             "min": (-half).tolist(), "max": half.tolist()},
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [primitive]}],
        "nodes": [{"mesh": 0, "name": "model"}],  # not "world": trimesh reserves that name for its root
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    if textured:
        primitive["material"] = 0
        document["images"] = [{"bufferView": 2, "mimeType": "image/png"}]
        document["textures"] = [{"source": 0}]
        document["materials"] = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]
    if root_scale:
        document["nodes"].append({"children": [0], "scale": [root_scale] * 3})
        document["scenes"] = [{"nodes": [1]}]
    glb.write_glb(Path(path), glb.Glb(document, bytearray(binary)))
    return Path(path).read_bytes()


class FakeProvider:
    """A provider that replays a list of statuses and 'downloads' a given GLB.

    Counts submissions so tests can prove that waiting never submits again.
    """

    name = "meshy"
    image_prompt_supported = False
    poll_interval_s = 5.0
    max_poll_interval_s = 5.0

    def __init__(self, states, model_bytes=b""):
        self.states = list(states)
        self.model_bytes = model_bytes
        self.submitted = []
        self.polls = 0

    def submit_text(self, request):
        self.submitted.append(request)
        return TaskRef("meshy", "image", (f"task-{len(self.submitted)}",))

    submit_image = submit_text

    def poll(self, ref):
        self.polls += 1
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return TaskStatus(TaskState(state), progress=50 if state == "running" else None)

    def follow_up(self, ref, status, output_format, *, texture):
        return None

    def start_follow_up(self, step):
        raise AssertionError("no follow-up expected")

    def fetch(self, ref, output_format, dest_dir):
        path = Path(dest_dir) / f"{ref.primary_id}.glb"
        path.write_bytes(self.model_bytes)
        return Fetched(path, "glb")


def assert_same_model_stood_up(path, original_bytes):
    """The downloaded GLB is the provider's model, only wrapped in the Y-up → Z-up root node."""
    from bambu_studio_ai.generation import glb

    got, before = glb.read_glb(Path(path)), glb.read_glb_bytes(original_bytes)
    assert bytes(got.binary) == bytes(before.binary)  # meshes and textures untouched
    names = [node.get("name") for node in got.document["nodes"]]
    assert names.count(glb.UPRIGHT_NODE) == 1
