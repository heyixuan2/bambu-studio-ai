#!/usr/bin/env python3
"""
Model Preview Generator — Renders 3D model preview images via Blender Cycles.

Auto-loads PBR materials/textures from GLB. Supports STL, OBJ, GLB/GLTF.
Uses Cycles for accurate PBR texture rendering in headless mode.

Requires: Blender 4.0+ (brew install --cask blender)

Usage:
  python3 scripts/preview.py model.glb                      # Perspective render
  python3 scripts/preview.py model.stl --output preview.png  # Custom output
  python3 scripts/preview.py model.obj --views all           # Front + side + top + perspective
"""

import os, sys, subprocess, argparse, tempfile, json

from common import find_blender


def preview(model_path, output_path, views="perspective"):
    """Render model preview using Blender Cycles."""
    blender = find_blender()
    if not blender:
        print("❌ Blender not found. Install: brew install --cask blender")
        return None

    if not os.path.exists(model_path):
        print(f"❌ File not found: {model_path}")
        return None

    model_repr = json.dumps(os.path.abspath(model_path))
    output_repr = json.dumps(os.path.abspath(output_path))
    views_repr = json.dumps(views)

    script = f'''
import bpy, os, sys, math, mathutils

MODEL_PATH = {model_repr}
OUTPUT_PATH = {output_repr}
VIEWS = {views_repr}

bpy.ops.wm.read_factory_settings(use_empty=True)

ext = os.path.splitext(MODEL_PATH)[1].lower()
if ext == ".stl":
    bpy.ops.wm.stl_import(filepath=MODEL_PATH)
elif ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=MODEL_PATH)
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath=MODEL_PATH)
elif ext == ".fbx":
    bpy.ops.import_scene.fbx(filepath=MODEL_PATH)
else:
    print(f"Unsupported: {{ext}}")
    sys.exit(1)

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    print("No meshes found!")
    sys.exit(1)

# Compute bounds from world-space vertices
all_coords = []
for obj in meshes:
    for v in obj.data.vertices:
        co = obj.matrix_world @ v.co
        all_coords.append((co.x, co.y, co.z))

xs, ys, zs = zip(*all_coords)
dims = (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
center = mathutils.Vector(((min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2))
size = max(dims)

if size < 1.0:
    scale_factor = 1000.0
    for obj in meshes:
        obj.scale *= scale_factor
    bpy.context.view_layer.update()
    all_coords = []
    for obj in meshes:
        for v in obj.data.vertices:
            co = obj.matrix_world @ v.co
            all_coords.append((co.x, co.y, co.z))
    xs, ys, zs = zip(*all_coords)
    dims = (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
    center = mathutils.Vector(((min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2))
    size = max(dims)
    print(f"MODEL_INFO: {{dims[0]:.1f}} x {{dims[1]:.1f}} x {{dims[2]:.1f}} mm (scaled from meters) | {{sum(len(o.data.polygons) for o in meshes):,}} faces")
else:
    print(f"MODEL_INFO: {{dims[0]:.1f}} x {{dims[1]:.1f}} x {{dims[2]:.1f}} mm | {{sum(len(o.data.polygons) for o in meshes):,}} faces")

# Detect material type: PBR texture > vertex colors > default
has_texture = False
has_vertex_colors = False

for obj in meshes:
    for mat in (obj.data.materials or []):
        if mat and mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image:
                    has_texture = True
                    break
        if has_texture: break
    if has_texture: break

if not has_texture:
    _vc_name = None
    for obj in meshes:
        if obj.data.color_attributes:
            has_vertex_colors = True
            _vc_name = obj.data.color_attributes[0].name
            break

if has_texture:
    print("PBR texture loaded from model")
elif has_vertex_colors:
    # Vertex color material: Attribute node → Base Color
    mat = bpy.data.materials.new("VertexColor")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.4
    attr_node = nodes.new("ShaderNodeAttribute")
    attr_node.attribute_name = _vc_name
    attr_node.attribute_type = 'GEOMETRY'
    links.new(attr_node.outputs["Color"], bsdf.inputs["Base Color"])
    for obj in meshes:
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    print("Vertex colors detected — using vertex color material")
else:
    # Default single-color preview
    mat = bpy.data.materials.new("Preview")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.357, 0.608, 0.835, 1)
    bsdf.inputs["Roughness"].default_value = 0.4
    for obj in meshes:
        obj.data.materials.clear()
        obj.data.materials.append(mat)
    print("No texture found — using preview material")

cam = bpy.data.cameras.new("Cam")
cam.clip_end = size * 20
cam_obj = bpy.data.objects.new("Cam", cam)
bpy.context.scene.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj

dist = size * 2.2
view_configs = {{
    "perspective": (center.x + dist*0.7, center.y - dist*0.9, center.z + dist*0.5),
    "front": (center.x, center.y - dist*1.5, center.z + size*0.1),
    "side": (center.x + dist*1.5, center.y, center.z + size*0.1),
    "top": (center.x, center.y, center.z + dist*1.5),
}}

key = bpy.data.lights.new("Key", 'SUN')
key.energy = 5.0
key_obj = bpy.data.objects.new("Key", key)
key_obj.rotation_euler = (math.radians(45), 0, math.radians(-30))
bpy.context.scene.collection.objects.link(key_obj)

fill = bpy.data.lights.new("Fill", 'SUN')
fill.energy = 2.0
fill_obj = bpy.data.objects.new("Fill", fill)
fill_obj.rotation_euler = (math.radians(60), 0, math.radians(150))
bpy.context.scene.collection.objects.link(fill_obj)

rim = bpy.data.lights.new("Rim", 'SUN')
rim.energy = 1.5
rim_obj = bpy.data.objects.new("Rim", rim)
rim_obj.rotation_euler = (math.radians(20), 0, math.radians(90))
bpy.context.scene.collection.objects.link(rim_obj)

world = bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.12, 0.12, 0.15, 1)

bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.cycles.samples = 48
bpy.context.scene.cycles.device = 'CPU'
try:
    prefs = bpy.context.preferences.addons.get('cycles')
    if prefs:
        for gpu_type in ['METAL', 'CUDA', 'OPTIX', 'HIP']:
            try:
                prefs.preferences.compute_device_type = gpu_type
                bpy.context.scene.cycles.device = 'GPU'
                break
            except Exception:
                continue
except Exception:
    pass

bpy.context.scene.render.image_settings.file_format = 'PNG'
bpy.context.scene.render.film_transparent = False
bpy.context.scene.view_settings.view_transform = 'Filmic'

def aim_camera(location):
    cam_obj.location = location
    direction = center - cam_obj.location
    cam_obj.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

if VIEWS == "all":
    import tempfile as _tf
    bpy.context.scene.render.resolution_x = 600
    bpy.context.scene.render.resolution_y = 600
    view_imgs = []
    for vname in ["perspective", "front", "side", "top"]:
        aim_camera(view_configs[vname])
        tmp = os.path.join(_tf.gettempdir(), f"preview_{{vname}}.png")
        bpy.context.scene.render.filepath = tmp
        bpy.ops.render.render(write_still=True)
        view_imgs.append(tmp)
    try:
        import numpy as np
        from PIL import Image
        imgs = [np.array(Image.open(p)) for p in view_imgs]
        top_row = np.concatenate([imgs[0], imgs[1]], axis=1)
        bot_row = np.concatenate([imgs[2], imgs[3]], axis=1)
        grid = np.concatenate([top_row, bot_row], axis=0)
        Image.fromarray(grid).save(OUTPUT_PATH)
    except ImportError:
        import shutil
        shutil.copy(view_imgs[0], OUTPUT_PATH)
    for p in view_imgs:
        try:
            os.unlink(p)
        except OSError:
            pass  # ignore unlink failures (file may already be gone)
else:
    bpy.context.scene.render.resolution_x = 800
    bpy.context.scene.render.resolution_y = 800
    aim_camera(view_configs.get(VIEWS, view_configs["perspective"]))
    bpy.context.scene.render.filepath = OUTPUT_PATH
    bpy.ops.render.render(write_still=True)

print("RENDER_OK")
'''

    TURNTABLE_SCRIPT = """
# --- Turntable GIF rendering ---
import tempfile as _tf
_turntable_dir = _tf.mkdtemp(prefix="turntable_")
_num_frames = 36
bpy.context.scene.render.resolution_x = 600
bpy.context.scene.render.resolution_y = 600

aim_camera(view_configs["perspective"])
_base_angle = math.atan2(cam_obj.location.y - center.y, cam_obj.location.x - center.x)

for _i in range(_num_frames):
    _angle = _base_angle + (2 * math.pi * _i / _num_frames)
    # Elevation oscillates: high(70deg) → below(-20deg), covers top/front/bottom
    _elev = math.radians(25 + 45 * math.sin(2 * math.pi * _i / _num_frames))
    _r = dist * 0.9
    _cx = center.x + _r * math.cos(_elev) * math.cos(_angle)
    _cy = center.y + _r * math.cos(_elev) * math.sin(_angle)
    _cz = center.z + _r * math.sin(_elev)
    aim_camera((_cx, _cy, _cz))
    _frame_path = os.path.join(_turntable_dir, "frame_%03d.png" % _i)
    bpy.context.scene.render.filepath = _frame_path
    bpy.ops.render.render(write_still=True)

# Assemble GIF
try:
    from PIL import Image
    _frames = []
    for _i in range(_num_frames):
        _fp = os.path.join(_turntable_dir, "frame_%03d.png" % _i)
        _frames.append(Image.open(_fp).copy())
    _frames[0].save(OUTPUT_PATH, save_all=True, append_images=_frames[1:],
                     duration=120, loop=0, optimize=True)
    print("TURNTABLE_OK")
except ImportError:
    import shutil
    shutil.copy(os.path.join(_turntable_dir, "frame_000.png"), OUTPUT_PATH)
    print("TURNTABLE_FALLBACK_PNG")

import shutil as _shutil
_shutil.rmtree(_turntable_dir, ignore_errors=True)
"""

    # Inject turntable rendering if requested
    if views == "turntable":
        script = script.replace('print("RENDER_OK")', TURNTABLE_SCRIPT)

    script_file = os.path.join(tempfile.gettempdir(), "bambu_preview.py")
    with open(script_file, "w") as f:
        f.write(script)

    print(f"📸 Rendering preview ({views})...")
    try:
        result = subprocess.run(
            [blender, "--background", "--python", script_file],
            capture_output=True, text=True, timeout=300
        )

        rendered = False
        for line in result.stdout.split('\n'):
            if "RENDER_OK" in line or "TURNTABLE_OK" in line:
                rendered = True
            if "TURNTABLE_FALLBACK_PNG" in line:
                rendered = True
                print("   ⚠️ PIL not available — saved single frame PNG instead of GIF")
            if "MODEL_INFO:" in line:
                print(f"   {line.split('MODEL_INFO: ')[1]}")
            if "PBR texture" in line or "No texture" in line or "preview material" in line or "Vertex colors" in line:
                print(f"   {line.strip()}")

        if rendered and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"   ✅ {output_path} ({size//1024}KB)")
            return output_path
        else:
            print("   ❌ Render failed")
            if result.stderr:
                for line in result.stderr.split('\n')[-5:]:
                    if line.strip():
                        print(f"   {line.strip()}")
            return None

    except subprocess.TimeoutExpired:
        print("   ❌ Render timeout (300s)")
        return None
    finally:
        if os.path.exists(script_file):
            os.unlink(script_file)


def main():
    parser = argparse.ArgumentParser(
        description="📸 3D Model Preview Generator (Blender Cycles)",
        epilog="Requires: Blender 4.0+ (brew install --cask blender)"
    )
    parser.add_argument("model", help="Model file (STL/OBJ/GLB/GLTF/FBX)")
    parser.add_argument("--output", "-o", help="Output PNG path")
    parser.add_argument("--views", "-v", default="perspective",
                        choices=["perspective", "front", "side", "top", "all", "turntable"],
                        help="View angle (default: perspective, 'all' = 2x2 grid, 'turntable' = 360° GIF)")
    args = parser.parse_args()

    if not os.path.exists(args.model):
        print(f"❌ File not found: {args.model}")
        sys.exit(1)

    if not args.output:
        ext = ".gif" if args.views == "turntable" else ".png"
        args.output = os.path.splitext(args.model)[0] + "_preview" + ext

    result = preview(args.model, os.path.abspath(args.output), views=args.views)
    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
