#!/usr/bin/env python3
"""
Model Preview Generator — Renders 3D model preview images via Blender.

Auto-loads PBR materials/textures from GLB. Supports STL, OBJ, GLB/GLTF, FBX.
Uses TRACK_TO constraint for auto-aiming and model dimensions for camera distance.

Requires: Blender 4.0+ (brew install --cask blender)

Usage:
  python3 scripts/preview.py model.glb                      # Perspective render
  python3 scripts/preview.py model.stl --output preview.png  # Custom output
  python3 scripts/preview.py model.obj --views all           # Front + side + top + perspective
"""

import os, sys, subprocess, argparse, tempfile, json

BLENDER_PATHS = [
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "blender",
]


def find_blender():
    for p in BLENDER_PATHS:
        if os.path.exists(p):
            return p
        result = subprocess.run(["which", p], capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout.strip()
    return None


def preview(model_path, output_path, views="perspective"):
    """Render model preview using Blender.
    
    Args:
        model_path: Input model file
        output_path: Output PNG path
        views: 'perspective' (single), 'front', 'side', 'top', or 'all' (4 views)
    
    Returns: output path on success, None on failure
    """
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

# Clear scene completely
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Import model (GLB auto-loads PBR materials + textures)
ext = os.path.splitext(MODEL_PATH)[1].lower()
if ext == ".stl":
    bpy.ops.wm.stl_import(filepath=MODEL_PATH)
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath=MODEL_PATH)
elif ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=MODEL_PATH)
elif ext == ".fbx":
    bpy.ops.import_scene.fbx(filepath=MODEL_PATH)
else:
    print(f"ERROR: Unsupported format: {{ext}}")
    sys.exit(1)

# Get all mesh objects
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not objs:
    print("ERROR: No mesh found")
    sys.exit(1)

# Join if multiple
bpy.context.view_layer.objects.active = objs[0]
for o in objs:
    o.select_set(True)
if len(objs) > 1:
    bpy.ops.object.join()
obj = bpy.context.active_object

# Compute model size from dimensions (accounts for transforms)
bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
dims = obj.dimensions
size = max(dims)
center = mathutils.Vector(obj.bound_box[0]) + (mathutils.Vector(obj.bound_box[6]) - mathutils.Vector(obj.bound_box[0])) / 2
center = obj.matrix_world @ center

# Auto-scale meters to mm (GLB typically uses meters)
if size < 10:
    obj.scale *= 1000
    bpy.ops.object.transform_apply(scale=True)
    dims = obj.dimensions
    size = max(dims)
    center = mathutils.Vector(obj.bound_box[0]) + (mathutils.Vector(obj.bound_box[6]) - mathutils.Vector(obj.bound_box[0])) / 2
    center = obj.matrix_world @ center
    unit = "mm (scaled from meters)"
else:
    unit = "mm"

print(f"MODEL_INFO: {{dims.x:.1f}} x {{dims.y:.1f}} x {{dims.z:.1f}} {{unit}} | {{len(obj.data.polygons):,}} faces")

# Check if model has textures (GLB PBR auto-loaded)
has_texture = False
for mat in obj.data.materials:
    if mat and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image:
                has_texture = True
                break
    if has_texture:
        break

if not has_texture:
    # No texture — apply clean preview material
    mat = bpy.data.materials.new("Preview")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.357, 0.608, 0.835, 1)
    bsdf.inputs["Roughness"].default_value = 0.4
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    print("No texture found — using preview material")
else:
    print("PBR texture loaded from model")

# Create empty at model center (for camera tracking)
empty = bpy.data.objects.new("Target", None)
bpy.context.scene.collection.objects.link(empty)
empty.location = center

# Camera — distance based on model size
cam_data = bpy.data.cameras.new("Cam")
cam_obj = bpy.data.objects.new("Cam", cam_data)
bpy.context.scene.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj
cam_data.lens = 50

# TRACK_TO constraint — camera always aims at model center
track = cam_obj.constraints.new(type='TRACK_TO')
track.target = empty
track.track_axis = 'TRACK_NEGATIVE_Z'
track.up_axis = 'UP_Y'

# Lighting — key (SUN) + fill (AREA)
key_data = bpy.data.lights.new("Key", 'SUN')
key_data.energy = 3.0
key_data.angle = math.radians(5)
key_obj = bpy.data.objects.new("Key", key_data)
bpy.context.scene.collection.objects.link(key_obj)
key_obj.rotation_euler = (math.radians(50), 0, math.radians(40))

fill_data = bpy.data.lights.new("Fill", 'AREA')
fill_data.energy = max(20.0, min(200.0, 50.0 * size))  # Scale with model size
fill_data.size = size * 2
fill_obj = bpy.data.objects.new("Fill", fill_data)
bpy.context.scene.collection.objects.link(fill_obj)
fill_obj.location = (center.x - size*2, center.y + size*2, center.z + size)
fill_track = fill_obj.constraints.new(type='TRACK_TO')
fill_track.target = empty
fill_track.track_axis = 'TRACK_NEGATIVE_Z'
fill_track.up_axis = 'UP_Y'

rim_data = bpy.data.lights.new("Rim", 'SUN')
rim_data.energy = 1.0
rim_obj = bpy.data.objects.new("Rim", rim_data)
bpy.context.scene.collection.objects.link(rim_obj)
rim_obj.rotation_euler = (math.radians(10), 0, math.radians(180))

# World background
world = bpy.data.worlds.new("World")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.118, 0.118, 0.176, 1)

# Render engine — try EEVEE variants (name changed across Blender versions)
for engine in ['BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE']:
    try:
        bpy.context.scene.render.engine = engine
        print(f"Render engine: {{engine}}")
        break
    except TypeError:
        continue

bpy.context.scene.render.image_settings.file_format = 'PNG'
bpy.context.scene.render.film_transparent = False

# Camera distance based on model size
dist = size * 3

# View positions (relative to center)
view_configs = {{
    "perspective": (center.x + dist*0.6, center.y - dist*0.8, center.z + dist*0.4),
    "front": (center.x, center.y - dist, center.z + size*0.3),
    "side": (center.x + dist, center.y, center.z + size*0.3),
    "top": (center.x + 0.001, center.y + 0.001, center.z + dist),
}}

if VIEWS == "all":
    bpy.context.scene.render.resolution_x = 600
    bpy.context.scene.render.resolution_y = 600
    
    import tempfile as _tf
    view_imgs = []
    for vname in ["perspective", "front", "side", "top"]:
        cam_obj.location = mathutils.Vector(view_configs[vname])
        bpy.context.view_layer.update()
        tmp = os.path.join(_tf.gettempdir(), f"preview_{{vname}}.png")
        bpy.context.scene.render.filepath = tmp
        bpy.ops.render.render(write_still=True)
        view_imgs.append(tmp)
        print(f"  Rendered {{vname}}")
    
    # Composite 2x2 grid
    try:
        from PIL import Image
        imgs = [Image.open(p) for p in view_imgs]
        grid = Image.new('RGB', (1200, 1200))
        grid.paste(imgs[0], (0, 0))
        grid.paste(imgs[1], (600, 0))
        grid.paste(imgs[2], (0, 600))
        grid.paste(imgs[3], (600, 600))
        grid.save(OUTPUT_PATH)
        print("RENDER_OK_ALL")
    except ImportError:
        # No PIL in Blender Python — save perspective only
        import shutil
        shutil.copy(view_imgs[0], OUTPUT_PATH)
        print("WARNING: PIL not available in Blender — saved perspective view only (install Pillow for 2x2 grid)")
        print("RENDER_OK_SINGLE")
else:
    bpy.context.scene.render.resolution_x = 1200
    bpy.context.scene.render.resolution_y = 900
    
    loc = view_configs.get(VIEWS, view_configs["perspective"])
    cam_obj.location = mathutils.Vector(loc)
    bpy.context.view_layer.update()
    bpy.context.scene.render.filepath = OUTPUT_PATH
    bpy.ops.render.render(write_still=True)
    print("RENDER_OK")
'''

    script_file = os.path.join(tempfile.gettempdir(), "bambu_preview.py")
    with open(script_file, "w") as f:
        f.write(script)

    print(f"📸 Rendering preview ({views})...")
    try:
        result = subprocess.run(
            [blender, "--background", "--python", script_file],
            capture_output=True, text=True, timeout=120
        )

        rendered = False
        for line in result.stdout.split('\n'):
            if "RENDER_OK" in line:
                rendered = True
            if "MODEL_INFO:" in line:
                print(f"   {line.split('MODEL_INFO: ')[1]}")
            if "PBR texture" in line or "No texture" in line or "preview material" in line:
                print(f"   {line.strip()}")

        if rendered and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"   ✅ {output_path} ({size//1024}KB)")
            return output_path
        else:
            print("   ❌ Render failed")
            if result.stderr:
                for line in result.stderr.split('\n')[-3:]:
                    if line.strip():
                        print(f"   {line.strip()}")
            return None

    except subprocess.TimeoutExpired:
        print("   ❌ Render timeout (120s)")
        return None
    finally:
        if os.path.exists(script_file):
            os.unlink(script_file)


def main():
    parser = argparse.ArgumentParser(
        description="📸 3D Model Preview Generator (Blender)",
        epilog="Requires: Blender 4.0+ (brew install --cask blender)"
    )
    parser.add_argument("model", help="Model file (STL/OBJ/GLB/GLTF/FBX)")
    parser.add_argument("--output", "-o", help="Output PNG path")
    parser.add_argument("--views", "-v", default="perspective",
                        choices=["perspective", "front", "side", "top", "all"],
                        help="View angle (default: perspective, 'all' = 2x2 grid)")
    args = parser.parse_args()

    if not os.path.exists(args.model):
        print(f"❌ File not found: {args.model}")
        sys.exit(1)

    if not args.output:
        args.output = os.path.splitext(args.model)[0] + "_preview.png"

    result = preview(args.model, os.path.abspath(args.output), views=args.views)
    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
