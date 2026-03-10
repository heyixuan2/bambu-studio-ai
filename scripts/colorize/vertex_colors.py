"""Blender vertex color application and OBJ post-processing (snap colors)."""

import os
import json
import subprocess
import tempfile

import numpy as np


def apply_vertex_colors(glb_path, quantized_npy_path, output_path, blender_path,
                        height_mm=0, subdivide=1):
    """Load GLB in Blender, sample quantized texture to vertex colors, export OBJ."""

    glb_esc = json.dumps(glb_path)
    npy_esc = json.dumps(quantized_npy_path)
    out_esc = json.dumps(output_path)

    script = f'''
import bpy
import numpy as np
import os

bpy.ops.wm.read_factory_settings(use_empty=True)

ext = os.path.splitext({glb_esc})[1].lower()
if ext in ['.glb', '.gltf']:
    bpy.ops.import_scene.gltf(filepath={glb_esc})
elif ext == '.obj':
    bpy.ops.wm.obj_import(filepath={glb_esc})
elif ext == '.fbx':
    bpy.ops.import_scene.fbx(filepath={glb_esc})
elif ext == '.stl':
    bpy.ops.wm.stl_import(filepath={glb_esc})

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise RuntimeError("No mesh found in model")
bpy.context.view_layer.objects.active = meshes[0]
for o in meshes:
    o.select_set(True)
if len(meshes) > 1:
    bpy.ops.object.join()

obj = bpy.context.active_object

# Detect units and scale to target height
height_mm = {height_mm}
bbox = [obj.matrix_world @ v.co for v in obj.data.vertices]
z_min = min(v.z for v in bbox)
z_max = max(v.z for v in bbox)
x_min = min(v.x for v in bbox)
x_max = max(v.x for v in bbox)
y_min = min(v.y for v in bbox)
y_max = max(v.y for v in bbox)
max_dim_raw = max(x_max - x_min, y_max - y_min, z_max - z_min)

# glTF spec says meters, but many AI generators output normalized ~1-2 unit models.
# Heuristic: if max_dim < 0.5 → very likely meters; < 10 → likely meters or normalized.
unit_scale = 1.0
if max_dim_raw < 0.5:
    unit_scale = 1000.0
    print(f"Detected meters (max_dim={{max_dim_raw:.4f}}), converting to mm")
elif max_dim_raw < 10:
    unit_scale = 1000.0
    print(f"Likely meters/normalized (max_dim={{max_dim_raw:.2f}}), converting to mm")

if unit_scale != 1.0:
    obj.scale *= unit_scale
    bpy.ops.object.transform_apply(scale=True)

if height_mm > 0:
    bbox = [obj.matrix_world @ v.co for v in obj.data.vertices]
    z_min = min(v.z for v in bbox)
    z_max = max(v.z for v in bbox)
    current_h = z_max - z_min
    if current_h > 0.01:
        scale = height_mm / current_h
        obj.scale *= scale
        bpy.ops.object.transform_apply(scale=True)
        bbox2 = [obj.matrix_world @ v.co for v in obj.data.vertices]
        z_min2 = min(v.z for v in bbox2)
        obj.location.z -= z_min2
        print(f"Scaled to target height: {{height_mm}}mm")

# Subdivide for vertex color resolution
subdivide = {subdivide}
if subdivide > 0:
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    for _ in range(subdivide):
        bpy.ops.mesh.subdivide(number_cuts=1)
    bpy.ops.object.mode_set(mode='OBJECT')

# Mesh repair BEFORE vertex colors — bmesh round-trip can destroy color attributes
import bmesh
bpy.ops.object.mode_set(mode='OBJECT')
bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)
for v in [v for v in bm.verts if not v.link_faces]:
    bm.verts.remove(v)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
nm_edges = sum(1 for e in bm.edges if not e.is_manifold)
print(f"Mesh repair: {{nm_edges}} non-manifold edges remaining")
bm.to_mesh(obj.data)
bm.free()
obj.data.update()

mesh = obj.data
print(f"Mesh: {{len(mesh.polygons):,}} faces, {{len(mesh.vertices):,}} verts (post-repair)")

# Load quantized texture (uint8 sRGB, Y-flipped for UV)
tex_srgb = np.load({npy_esc})
th, tw = tex_srgb.shape[:2]
tex_f = tex_srgb.astype(np.float32) / 255.0

# BYTE_COLOR in Blender 4.x stores values in sRGB space internally,
# so we pass sRGB floats directly — no manual sRGB→linear conversion.

if "Col" not in mesh.color_attributes:
    mesh.color_attributes.new(name="Col", type='BYTE_COLOR', domain='CORNER')
mesh.color_attributes.active_color = mesh.color_attributes["Col"]
cl = mesh.color_attributes["Col"]
if not mesh.uv_layers.active:
    print("ERROR: No UV mapping found. Colorize requires a textured model (GLB/GLTF).")
    import sys; sys.exit(1)
uv = mesh.uv_layers.active.data

print("Writing vertex colors (vectorized)...")
n_loops = len(uv)
uv_arr = np.empty(n_loops * 2, dtype=np.float32)
uv[0].id_data.uv_layers.active.data.foreach_get("uv", uv_arr)
uv_arr = uv_arr.reshape(-1, 2)
px = (uv_arr[:, 0] * tw).astype(np.int32) % tw
py = (uv_arr[:, 1] * th).astype(np.int32) % th
sampled = tex_f[py, px]  # (n_loops, 3) — sRGB float [0,1]
colors_flat = np.empty(n_loops * 4, dtype=np.float32)
colors_flat[0::4] = sampled[:, 0]
colors_flat[1::4] = sampled[:, 1]
colors_flat[2::4] = sampled[:, 2]
colors_flat[3::4] = 1.0
cl.data.foreach_set("color", colors_flat)
mesh.update()
print(f"  Done: {{n_loops:,}} loop colors set")

# Post-color sanity check: if no explicit height was given, auto-scale outliers
bbox_post = [obj.matrix_world @ v.co for v in obj.data.vertices]
xs = [v.x for v in bbox_post]
ys = [v.y for v in bbox_post]
zs = [v.z for v in bbox_post]
dims_post = (max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
max_dim = max(dims_post)
print(f"Final dims: {{dims_post[0]:.1f}} x {{dims_post[1]:.1f}} x {{dims_post[2]:.1f}} mm (max={{max_dim:.1f}})")

if height_mm == 0 and (max_dim > 200 or max_dim < 10):
    target = 80.0
    scale_factor = target / max_dim
    obj.scale *= scale_factor
    bpy.ops.object.transform_apply(scale=True)
    print(f"Auto-scaled: {{max_dim:.1f}} → {{target:.0f}}mm")

# Export OBJ with vertex colors
bpy.ops.wm.obj_export(
    filepath={out_esc},
    export_selected_objects=True,
    export_colors=True,
    export_materials=False,
    export_uv=False
)
size_mb = os.path.getsize({out_esc}) / 1024 / 1024
print(f"Done: {{size_mb:.1f}}MB")
'''

    script_file = os.path.join(tempfile.gettempdir(), "bambu_vertex_color.py")
    with open(script_file, "w") as f:
        f.write(script)

    print(f"   Blender: subdivide={subdivide}, vertex colors...")
    result = subprocess.run([blender_path, "--background", "--python", script_file],
                           capture_output=True, text=True, timeout=1800)

    for line in result.stdout.split('\n'):
        line = line.strip()
        if line and any(k in line for k in ['Mesh:', 'Writing', 'Converted', 'Done:', '/', 'ERROR', 'repair', 'manifold']):
            print(f"   {line}")

    if result.returncode != 0:
        print(f"\n⚠️ Blender error:")
        for line in result.stderr.split('\n')[-5:]:
            if line.strip():
                print(f"   {line.strip()}")
        return None

    if os.path.exists(output_path):
        return output_path
    return None


def snap_vertex_colors(obj_path, selected_colors):
    """Post-process OBJ to snap vertex colors to EXACT selected sRGB values.

    For each vertex, find nearest target color (RGB Euclidean distance), then
    write the EXACT same string for every vertex of that color, guaranteeing
    Bambu Studio sees exactly N unique colors.
    """
    sel_rgb = np.array([sc["rgb"] for sc in selected_colors], dtype=np.float64)
    color_strings = []
    for rgb in sel_rgb:
        color_strings.append("%.6f %.6f %.6f" % (rgb[0], rgb[1], rgb[2]))

    with open(obj_path) as f:
        lines = f.readlines()

    v_indices = []
    v_xyz_strs = []
    v_rgb = []
    for i, line in enumerate(lines):
        if line.startswith('v '):
            parts = line.split()
            if len(parts) >= 7:
                v_indices.append(i)
                v_xyz_strs.append(" ".join(parts[1:4]))
                v_rgb.append([float(parts[4]), float(parts[5]), float(parts[6])])

    if not v_indices:
        return

    rgb_arr = np.array(v_rgb, dtype=np.float64)

    sel_linear = np.where(sel_rgb <= 0.04045, sel_rgb / 12.92,
                          ((sel_rgb + 0.055) / 1.055) ** 2.4)

    dists_srgb = np.sum(
        (rgb_arr[:, np.newaxis, :] - sel_rgb[np.newaxis, :, :]) ** 2, axis=2)
    dists_lin = np.sum(
        (rgb_arr[:, np.newaxis, :] - sel_linear[np.newaxis, :, :]) ** 2, axis=2)
    dists = np.minimum(dists_srgb, dists_lin)

    nearest_idx = np.argmin(dists, axis=1)
    snapped = 0
    for j, vi in enumerate(v_indices):
        cidx = nearest_idx[j]
        lines[vi] = "v %s %s\n" % (v_xyz_strs[j], color_strings[cidx])
        snapped += 1

    with open(obj_path, 'w') as f:
        f.writelines(lines)

    unique_colors = len(set(nearest_idx))
    print(f"   Snapped {snapped:,} vertices → {unique_colors} exact colors "
          f"(of {len(sel_rgb)} targets)")
