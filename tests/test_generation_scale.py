"""Sizing in Bambu Studio's frame (Z up, millimetres), GLB rescaling and local conversion.

Bambu Studio 2.7.1 was checked directly: a GLB with raw extents 40 x 10 x 20 exported
through ``bambu-studio --export-stl`` came out 40 x 10 x 20 with Z on the bed, and a
root-node scale of 2 came out 80 x 20 x 40. These tests pin the same arithmetic.
"""

import pytest

from bambu_studio_ai.generation import glb, scale
from bambu_studio_ai.generation.errors import InputError
from generation_fakes import make_glb


def test_a_10mm_charm_stays_10mm_without_height(tmp_path):
    path = tmp_path / "charm.glb"
    original = make_glb(path, (8.0, 3.0, 10.0))
    assert scale.measure(path, "glb") == pytest.approx((8.0, 3.0, 10.0))
    assert path.read_bytes() == original  # measuring never rewrites the file


def test_height_sets_the_vertical_extent(tmp_path):
    path = tmp_path / "model.glb"
    make_glb(path, (2.0, 0.5, 1.0))
    assert scale.scale_to_height(path, "glb", 60.0) == pytest.approx((120.0, 30.0, 60.0))
    assert scale.measure(path, "glb") == pytest.approx((120.0, 30.0, 60.0))


def test_scaling_keeps_the_texture_byte_for_byte(tmp_path):
    path = tmp_path / "model.glb"
    make_glb(path, (2.0, 0.5, 1.0))
    before = glb.read_glb(path)
    image_view = before.document["bufferViews"][before.document["images"][0]["bufferView"]]
    start, length = image_view["byteOffset"], image_view["byteLength"]
    texture = bytes(before.binary[start:start + length])

    scale.scale_to_height(path, "glb", 60.0)

    after = glb.read_glb(path)
    assert bytes(after.binary[start:start + length]) == texture
    assert after.document["materials"] == before.document["materials"]
    assert scale.has_texture(path, "glb") is True
    accessor = after.document["accessors"][0]
    assert accessor["max"][2] - accessor["min"][2] == pytest.approx(60.0)


def test_node_transforms_are_applied_like_bambu_studio_does(tmp_path):
    # trimesh.load reports 40 x 10 x 20 for this file (it confuses a node named "world"
    # with its own base frame); Bambu Studio and this module both see 80 x 20 x 40.
    path = tmp_path / "scaled_root.glb"
    make_glb(path, (40.0, 10.0, 20.0), root_scale=2.0)
    assert scale.measure(path, "glb") == pytest.approx((80.0, 20.0, 40.0))
    assert scale.scale_to_height(path, "glb", 60.0) == pytest.approx((120.0, 30.0, 60.0))


def test_rotated_node_is_measured_in_world_space(tmp_path):
    path = tmp_path / "rotated.glb"
    make_glb(path, (40.0, 10.0, 20.0))
    model = glb.read_glb(path)
    half = 0.5 ** 0.5  # 90 degrees about X: Y becomes Z
    model.document["nodes"][0]["rotation"] = [half, 0.0, 0.0, half]
    glb.write_glb(path, model)
    assert scale.measure(path, "glb") == pytest.approx((40.0, 20.0, 10.0))


def test_stl_height(tmp_path):
    source, stl = tmp_path / "m.glb", tmp_path / "m.stl"
    make_glb(source, (2.0, 0.5, 1.0), textured=False)
    scale.convert_glb_locally(source, stl, "stl")
    assert scale.scale_to_height(stl, "stl", 60.0) == pytest.approx((120.0, 30.0, 60.0))
    assert scale.measure(stl, "stl") == pytest.approx((120.0, 30.0, 60.0))


@pytest.mark.parametrize("output_format", ["stl", "3mf", "obj"])
def test_local_conversion_keeps_size_and_drops_colour(tmp_path, output_format):
    source, target = tmp_path / "m.glb", tmp_path / f"m.{output_format}"
    make_glb(source, (12.0, 7.0, 5.0))
    scale.convert_glb_locally(source, target, output_format)
    assert scale.measure(target, output_format) == pytest.approx((12.0, 7.0, 5.0))
    assert scale.has_texture(target, output_format) is False
    assert not (tmp_path / "material.mtl").exists()  # no stray files in the output folder


@pytest.mark.parametrize(("extents", "height"), [((1.0, 1.0, 0.0), 10.0), ((1.0, 1.0, 1.0), 0.0)])
def test_impossible_heights_are_rejected(extents, height):
    with pytest.raises(InputError):
        scale.height_factor(extents, height)


def test_non_glb_bytes_are_rejected(tmp_path):
    path = tmp_path / "fake.glb"
    path.write_bytes(b"<html>not a model</html>")
    with pytest.raises(InputError, match="not a GLB"):
        scale.measure(path, "glb")


def test_provider_glb_is_stood_up_once(tmp_path):
    """glTF is Y-up; Bambu Studio reads Z as up, so a tall figure would import lying down."""
    from bambu_studio_ai.generation import glb

    path = tmp_path / "figure.glb"
    make_glb(path, (10.0, 40.0, 10.0))  # tall along glTF's Y (up)
    scale.stand_glb_upright(path)
    assert scale.measure(path, "glb") == pytest.approx((10.0, 10.0, 40.0))  # now tall along Z
    once = path.read_bytes()
    scale.stand_glb_upright(path)  # idempotent: a resumed download doesn't turn it again
    assert path.read_bytes() == once
    assert [n.get("name") for n in glb.read_glb(path).document["nodes"]].count(glb.UPRIGHT_NODE) == 1
    assert scale.scale_to_height(path, "glb", 80.0) == pytest.approx((20.0, 20.0, 80.0))
