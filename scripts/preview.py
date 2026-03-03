#!/usr/bin/env python3
"""
Model Preview Generator — Renders 3D model preview images for chat.

Uses matplotlib for quick previews (no extra deps).
Uses Blender for high-quality renders (if available).

Usage:
  python3 scripts/preview.py model.stl                    # Quick matplotlib preview
  python3 scripts/preview.py model.stl --hq               # High-quality Blender render
  python3 scripts/preview.py model.stl --output preview.png

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
    return None

def preview_matplotlib(model_path, output_path, title=None):
    """Quick preview using matplotlib (always available)."""
    import trimesh
    import numpy as np

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    except ImportError:
        print("❌ matplotlib not installed: pip3 install matplotlib")
        sys.exit(1)

    m = trimesh.load(model_path, force='mesh')
    verts, faces = np.array(m.vertices), np.array(m.faces)

    # Decimate for rendering performance
    max_render_faces = 50000
    if len(faces) > max_render_faces:
        idx = np.random.choice(len(faces), max_render_faces, replace=False)
        faces = faces[idx]

    fig = plt.figure(figsize=(10, 8), facecolor='#1e1e2e')
    ax = fig.add_subplot(111, projection='3d', facecolor='#1e1e2e')

    mesh_col = Poly3DCollection(verts[faces], alpha=0.9,
                                 edgecolor='none', facecolor='#5b9bd5',
                                 linewidths=0)
    ax.add_collection3d(mesh_col)

    mins, maxs = verts.min(axis=0), verts.max(axis=0)
    center = (mins + maxs) / 2
    r = (maxs - mins).max() / 2 * 1.2
    ax.set_xlim(center[0]-r, center[0]+r)
    ax.set_ylim(center[1]-r, center[1]+r)
    ax.set_zlim(center[2]-r, center[2]+r)

    ax.view_init(elev=25, azim=135)
    ax.set_axis_off()

    dims = m.bounding_box.extents
    if not title:
        name = os.path.splitext(os.path.basename(model_path))[0]
        # Warn if dimensions look like meters (all < 1)
    unit = "mm"
    if all(d < 1.0 for d in dims):
        unit = "m (run analyze.py to convert)"
    title = f"{name} — {dims[0]:.1f} × {dims[1]:.1f} × {dims[2]:.1f} {unit}"

    ax.set_title(title, color='white', fontsize=14, pad=20)

    # Add info text
    info = f"{len(m.faces):,} faces | {'watertight' if m.is_watertight else 'not watertight'}"
    fig.text(0.5, 0.02, info, ha='center', color='#888888', fontsize=10)

    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='#1e1e2e')
    plt.close()

    size = os.path.getsize(output_path)
    print(f"📸 Preview: {output_path} ({size//1024}KB)")
    return output_path

def preview_blender(model_path, output_path):
    """High-quality render using Blender (headless)."""
    blender = find_blender()
    if not blender:
        print("⚠️ Blender not found, falling back to matplotlib")
        return preview_matplotlib(model_path, output_path)

    # Pass paths via argv to avoid f-string injection issues
    import json as _json
    model_escaped = _json.dumps(model_path)
    output_escaped = _json.dumps(output_path)
    
    script = f'''
import bpy, os, sys, math, json

MODEL_PATH = {model_escaped}
OUTPUT_PATH = {output_escaped}

# Clear scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# Import model
ext = os.path.splitext(MODEL_PATH)[1].lower()
if ext == ".stl":
    bpy.ops.wm.stl_import(filepath=MODEL_PATH)
elif ext == ".obj":
    bpy.ops.wm.obj_import(filepath=MODEL_PATH)
elif ext in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=MODEL_PATH)

# Select all mesh objects
objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not objs:
    print("No mesh found")
    quit()

# Compute bounding box
import mathutils
mins = mathutils.Vector((1e9, 1e9, 1e9))
maxs = mathutils.Vector((-1e9, -1e9, -1e9))
for obj in objs:
    for v in obj.bound_box:
        world = obj.matrix_world @ mathutils.Vector(v)
        mins = mathutils.Vector((min(mins[i], world[i]) for i in range(3)))
        maxs = mathutils.Vector((max(maxs[i], world[i]) for i in range(3)))

center = (mins + maxs) / 2
size = max(maxs[i] - mins[i] for i in range(3))

# Add material (light blue)
for obj in objs:
    mat = bpy.data.materials.new("Preview")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.357, 0.608, 0.835, 1)
    bsdf.inputs["Roughness"].default_value = 0.4
    obj.data.materials.clear()
    obj.data.materials.append(mat)

# Camera
cam = bpy.data.cameras.new("Cam")
cam_obj = bpy.data.objects.new("Cam", cam)
bpy.context.scene.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj

dist = size * 2.5
cam_obj.location = (center.x + dist*0.6, center.y - dist*0.8, center.z + dist*0.5)
direction = center - cam_obj.location
rot = direction.to_track_quat('-Z', 'Y')
cam_obj.rotation_euler = rot.to_euler()

# Lighting
light = bpy.data.lights.new("Key", 'SUN')
light.energy = 3
light_obj = bpy.data.objects.new("Key", light)
bpy.context.scene.collection.objects.link(light_obj)
light_obj.rotation_euler = (math.radians(45), 0, math.radians(45))

fill = bpy.data.lights.new("Fill", 'SUN')
fill.energy = 1.5
fill_obj = bpy.data.objects.new("Fill", fill)
bpy.context.scene.collection.objects.link(fill_obj)
fill_obj.rotation_euler = (math.radians(60), 0, math.radians(-135))

# World background
bpy.context.scene.world = bpy.data.worlds.new("World")
bpy.context.scene.world.use_nodes = True
bg = bpy.context.scene.world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.12, 0.12, 0.18, 1)

# Render settings
try:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE_NEXT'
except TypeError:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE'
bpy.context.scene.render.resolution_x = 1200
bpy.context.scene.render.resolution_y = 900
bpy.context.scene.render.film_transparent = False
bpy.context.scene.render.filepath = OUTPUT_PATH
bpy.context.scene.render.image_settings.file_format = 'PNG'

bpy.ops.render.render(write_still=True)
print("RENDER_OK")
'''

    tmp_script = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
    tmp_script.write(script)
    tmp_script.close()

    try:
        result = subprocess.run(
            [blender, "--background", "--python", tmp_script.name],
            capture_output=True, text=True, timeout=60)

        if "RENDER_OK" in result.stdout and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            print(f"📸 Preview (HQ): {output_path} ({size//1024}KB)")
            return output_path
        else:
            print(f"⚠️ Blender render failed, falling back to matplotlib")
            stderr = result.stderr[-200:] if result.stderr else ""
            if stderr:
                print(f"   {stderr}")
            return preview_matplotlib(model_path, output_path)
    except subprocess.TimeoutExpired:
        print("⚠️ Blender timeout, falling back to matplotlib")
        return preview_matplotlib(model_path, output_path)
    finally:
        os.unlink(tmp_script.name)

def main():
    parser = argparse.ArgumentParser(description="3D Model Preview Generator")
    parser.add_argument("model", help="Model file (STL/OBJ/GLB)")
    parser.add_argument("--output", "-o", help="Output PNG path")
    parser.add_argument("--hq", action="store_true", help="High-quality Blender render")
    parser.add_argument("--title", help="Custom title text")
    args = parser.parse_args()

    if not os.path.exists(args.model):
        print(f"❌ File not found: {args.model}")
        sys.exit(1)

    if not args.output:
        base = os.path.splitext(args.model)[0]
        args.output = base + "_preview.png"

    args.output = os.path.abspath(args.output)

    if args.hq:
        preview_blender(args.model, args.output)
    else:
        preview_matplotlib(args.model, args.output, title=args.title)

if __name__ == "__main__":
    main()
