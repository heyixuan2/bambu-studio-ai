# pyright: basic, reportMissingImports=false
r"""Render preview frames of one model inside Blender. Run by ``render/blender.py``.

Blender runs this file with its own Python, where ``bpy`` exists::

    blender -b --factory-startup --python-exit-code 1 -P blender_scene.py -- \
        --model M --out-dir D --json-out J [--size 800] [--samples 48] [--cpu] \
        (--views perspective front side top | --turntable 36)

It writes one RGBA PNG per frame into ``--out-dir`` and a JSON report to
``--json-out``: dimensions, triangle count, material mode, device and frame paths, or
``{"ok": false, "error": ...}``. Lines on stdout that start with ``BSA_PROGRESS``
carry one JSON object each, so the host can report progress.

The model keeps the file's own axes with Z up, as Bambu Studio and ``analyze.py`` read
it: Blender's OBJ and glTF importers would otherwise turn Y-up files upright.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import numpy as np

if TYPE_CHECKING:
    from types import ModuleType

PROGRESS_PREFIX: Final = "BSA_PROGRESS "
VIEW_NAMES: Final = ("perspective", "front", "side", "top")
GPU_BACKENDS: Final = ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI")
PREVIEW_SRGB: Final = (91, 155, 213)  # meshes.PREVIEW_RGB, so every renderer agrees
_ROUGHNESS: Final = 0.6
_MODE_ORDER: Final = ("texture", "vertex", "material", "preview")
# Light directions in camera space (x right, y up, z towards the camera) and strengths.
_LIGHTS: Final = (
    ("Key", (-0.45, 0.65, 0.6), 2.8),
    ("Fill", (0.7, 0.1, 0.7), 1.2),
    ("Rim", (0.2, 0.8, -0.6), 1.5),
)
_WORLD_GREY: Final = 0.22
_WORLD_STRENGTH: Final = 0.9


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the arguments after Blender's ``--``."""
    parser = argparse.ArgumentParser(prog="blender_scene.py")
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--size", type=int, default=800)
    parser.add_argument("--samples", type=int, default=48)
    parser.add_argument("--cpu", action="store_true", help="don't try the GPU")
    frames = parser.add_mutually_exclusive_group(required=True)
    frames.add_argument("--views", nargs="+", choices=VIEW_NAMES)
    frames.add_argument("--turntable", type=int, metavar="FRAMES")
    return parser.parse_args(argv)


def script_args(argv: list[str]) -> list[str]:
    """Blender passes everything after ``--`` through to the script."""
    return argv[argv.index("--") + 1 :] if "--" in argv else []


def load_views() -> ModuleType:
    """Load the sibling ``views.py`` by path (the package isn't on Blender's sys.path)."""
    path = Path(__file__).with_name("views.py")
    spec = importlib.util.spec_from_file_location("bsa_render_views", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def progress(**fields: object) -> None:
    """Tell the host how far we are (one JSON object per line)."""
    print(PROGRESS_PREFIX + json.dumps(fields), flush=True)


def srgb_to_linear(channel: int) -> float:
    """Blender colour sockets take scene-linear values."""
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4  # noqa: PLR2004


def import_model(bpy: ModuleType, matrix: Any, path: Path) -> list[Any]:  # noqa: ANN401
    """Import ``path`` in the file's own axes and return its mesh objects."""
    suffix = path.suffix.lower()
    axes = {"forward_axis": "Y", "up_axis": "Z"}  # i.e. no axis conversion
    if suffix == ".stl":
        bpy.ops.wm.stl_import(filepath=str(path), **axes)
    elif suffix == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path), **axes)
    elif suffix == ".ply":
        bpy.ops.wm.ply_import(filepath=str(path), **axes)
    elif suffix in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
        # The glTF importer maps file (x, y, z) to Blender (x, -z, y); turn it back.
        undo = matrix.Rotation(-math.pi / 2, 4, "X")
        for obj in bpy.context.scene.objects:
            if obj.parent is None:
                obj.matrix_world = undo @ obj.matrix_world
    elif suffix == ".fbx":
        # FBX declares its own axes and units; the importer honours them.
        if hasattr(bpy.ops.wm, "fbx_import"):
            bpy.ops.wm.fbx_import(filepath=str(path))
        else:
            bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        raise ValueError(f"Blender can't import {suffix} files")
    bpy.context.view_layer.update()
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise ValueError(f"{path.name} contains no meshes")
    return meshes


def world_vertices(meshes: list[Any]) -> np.ndarray:
    """Every vertex of every mesh object in world coordinates, as an ``(n, 3)`` array."""
    chunks = []
    for obj in meshes:
        coords = np.empty(len(obj.data.vertices) * 3)
        obj.data.vertices.foreach_get("co", coords)
        matrix = np.array(obj.matrix_world)
        chunks.append(coords.reshape(-1, 3) @ matrix[:3, :3].T + matrix[:3, 3])
    return np.vstack(chunks)


def triangle_count(meshes: list[Any]) -> int:
    """Triangles after triangulation, to match trimesh's face count."""
    total = 0
    for obj in meshes:
        obj.data.calc_loop_triangles()
        total += len(obj.data.loop_triangles)
    return total


def _node_tree(owner: Any) -> Any:  # noqa: ANN401
    """The node tree of a material or world, created on Blender versions before 5.0."""
    if getattr(owner, "node_tree", None) is None:
        owner.use_nodes = True
    return owner.node_tree


def _principled(material: Any) -> Any:  # noqa: ANN401
    return next(n for n in _node_tree(material).nodes if n.type == "BSDF_PRINCIPLED")


def _uses_node(material: Any, node_types: tuple[str, ...]) -> bool:  # noqa: ANN401
    tree = material.node_tree
    return tree is not None and any(n.type in node_types for n in tree.nodes)


def _assign(obj: Any, material: Any) -> None:  # noqa: ANN401
    obj.data.materials.clear()
    obj.data.materials.append(material)


def setup_materials(bpy: ModuleType, meshes: list[Any]) -> str:
    """Keep the file's materials; add one only where the file has none.

    Returns the most specific mode used: ``texture`` (image textures), ``vertex``
    (colour attributes), ``material`` (the file's own colours) or ``preview``.
    """
    modes = set()
    preview = None
    for obj in meshes:
        mesh = obj.data
        materials = [m for m in mesh.materials if m is not None]
        attribute = mesh.color_attributes[0].name if len(mesh.color_attributes) else None
        if any(_uses_node(m, ("TEX_IMAGE",)) for m in materials):
            modes.add("texture")
        elif attribute and any(_uses_node(m, ("VERTEX_COLOR", "ATTRIBUTE")) for m in materials):
            modes.add("vertex")
        elif attribute:
            material = bpy.data.materials.new("Vertex colours")
            bsdf = _principled(material)
            node = material.node_tree.nodes.new("ShaderNodeVertexColor")
            node.layer_name = attribute
            material.node_tree.links.new(node.outputs["Color"], bsdf.inputs["Base Color"])
            bsdf.inputs["Roughness"].default_value = _ROUGHNESS
            _assign(obj, material)
            modes.add("vertex")
        elif materials:
            modes.add("material")
        else:
            if preview is None:
                preview = bpy.data.materials.new("Preview")
                bsdf = _principled(preview)
                bsdf.inputs["Base Color"].default_value = (
                    *(srgb_to_linear(c) for c in PREVIEW_SRGB),
                    1.0,
                )
                bsdf.inputs["Roughness"].default_value = _ROUGHNESS
            _assign(obj, preview)
            modes.add("preview")
    return next(mode for mode in _MODE_ORDER if mode in modes)


def setup_device(bpy: ModuleType, scene: Any, *, cpu_only: bool) -> str:  # noqa: ANN401
    """Render on the first GPU backend that has a device; otherwise on the CPU.

    Setting ``compute_device_type`` alone leaves the device list empty and Cycles
    silently stays on the CPU: the devices have to be listed and enabled.
    """
    scene.cycles.device = "CPU"
    if cpu_only:
        return "CPU"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for backend in GPU_BACKENDS:
        try:
            prefs.compute_device_type = backend
        except TypeError:  # not compiled into this Blender / not on this OS
            continue
        prefs.get_devices()
        if not any(d.type == backend for d in prefs.get_devices_for_type(backend)):
            continue
        for device in prefs.devices:
            device.use = device.type == backend
        scene.cycles.device = "GPU"
        return backend
    prefs.compute_device_type = "NONE"
    return "CPU"


def setup_scene(
    bpy: ModuleType, mathutils: ModuleType, args: argparse.Namespace
) -> tuple[Any, Any, str]:
    """Render settings, world light and a camera with lights that move with it."""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = args.samples
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_x = scene.render.resolution_y = args.size
    scene.render.resolution_percentage = 100
    scene.render.use_persistent_data = True  # only the camera moves between frames
    try:
        scene.view_settings.view_transform = "Standard"  # true colours for filament matching
    except TypeError:
        progress(stage="warning", message="view transform 'Standard' not available")
    device = setup_device(bpy, scene, cpu_only=args.cpu)

    world = bpy.data.worlds.new("Preview world")
    scene.world = world
    background = next(n for n in _node_tree(world).nodes if n.type == "BACKGROUND")
    background.inputs["Color"].default_value = (_WORLD_GREY, _WORLD_GREY, _WORLD_GREY, 1.0)
    background.inputs["Strength"].default_value = _WORLD_STRENGTH

    camera_data = bpy.data.cameras.new("Preview camera")
    camera = bpy.data.objects.new("Preview camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    for name, direction, energy in _LIGHTS:
        sun = bpy.data.lights.new(name, "SUN")
        sun.energy = energy
        sun.angle = math.radians(8)
        light = bpy.data.objects.new(name, sun)
        scene.collection.objects.link(light)
        # Parented with an identity camera transform, so the offset is purely local:
        # the lights turn with the camera and every view is lit the same way.
        light.parent = camera
        light.rotation_euler = mathutils.Vector(direction).to_track_quat("Z", "Y").to_euler()
    return scene, camera, device


def place_camera(  # noqa: PLR0913
    camera: Any,  # noqa: ANN401
    views: ModuleType,
    mathutils: ModuleType,
    *,
    centre: np.ndarray,
    direction: tuple[float, float, float],
    distance: float,
    radius: float,
) -> None:
    """Put the camera ``distance`` from ``centre`` along ``direction``, looking back at it."""
    right, up, back = views.camera_basis(direction)
    eye = centre + np.array(back) * distance
    camera.matrix_world = mathutils.Matrix(
        [
            (right[0], up[0], back[0], eye[0]),
            (right[1], up[1], back[1], eye[1]),
            (right[2], up[2], back[2], eye[2]),
            (0.0, 0.0, 0.0, 1.0),
        ]
    )
    camera.data.lens = views.LENS_MM
    camera.data.sensor_width = views.SENSOR_MM
    camera.data.sensor_fit = "AUTO"
    camera.data.clip_start = distance * 0.005
    camera.data.clip_end = distance + 4 * radius


def render(args: argparse.Namespace) -> dict[str, Any]:
    """Import, set up and render every frame; return the report for the host."""
    import bpy  # noqa: PLC0415  (only exists inside Blender)
    import mathutils  # noqa: PLC0415

    views = load_views()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    meshes = import_model(bpy, mathutils.Matrix, args.model)
    vertices = world_vertices(meshes)
    material = setup_materials(bpy, meshes)
    scene, camera, device = setup_scene(bpy, mathutils, args)
    progress(stage="device", device=device)

    centre, relative = views.framing(vertices)
    radius = float(np.sqrt((relative**2).sum(axis=1)).max())
    if args.turntable:
        names = [f"frame_{i:03d}" for i in range(args.turntable)]
        directions = views.turntable_directions(args.turntable)
        common = views.shared_distance(relative, directions)
    else:
        names = list(args.views)
        directions = [views.view_direction(name) for name in names]
        common = None
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, (name, direction) in enumerate(zip(names, directions, strict=True)):
        distance = common if common is not None else views.fit_distance(relative, direction)
        place_camera(
            camera,
            views,
            mathutils,
            centre=centre,
            direction=direction,
            distance=distance,
            radius=radius,
        )
        path = args.out_dir / f"{index:03d}_{name}.png"
        scene.render.filepath = str(path)
        started = time.monotonic()
        bpy.ops.render.render(write_still=True)
        progress(
            stage="frame",
            index=index + 1,
            total=len(names),
            seconds=round(time.monotonic() - started, 2),
        )
        frames.append({"name": name, "path": str(path)})
    extents = vertices.max(axis=0) - vertices.min(axis=0)
    return {
        "blender_version": bpy.app.version_string,
        "device": device,
        "material": material,
        "dimensions": [float(v) for v in extents],
        "faces": triangle_count(meshes),
        "frame_dir": str(args.out_dir),
        "frames": frames,
    }


def main(argv: list[str]) -> int:
    """Render and always leave a JSON report behind, even when something fails."""
    args = parse_args(script_args(argv))
    report: dict[str, Any] = {"ok": False}
    try:
        report.update(render(args))
        report["ok"] = True
    except Exception as exc:  # noqa: BLE001  (Blender only logs exceptions; the host needs them)
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    args.json_out.write_text(json.dumps(report), encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
