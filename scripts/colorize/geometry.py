"""Geometry-based saliency detection: mesh curvature → protect eyes, buttons, etc."""

import os
import numpy as np


def curvature_mask_from_glb(glb_path, width, height, percentile=92):
    """Build a 2D mask from mesh curvature: convex regions (eyes, buttons) = True.
    Uses trimesh vertex_defects + UV rasterization. Returns (height, width) bool array.
    """
    try:
        import pygltflib
        import trimesh
    except ImportError:
        return None

    ext = os.path.splitext(glb_path)[1].lower()
    if ext not in (".glb", ".gltf"):
        return None

    try:
        glb = pygltflib.GLTF2().load(glb_path)
        blob = (glb.binary_blob() if hasattr(glb, "binary_blob")
                else getattr(glb, "_glb_data", None))
        if blob is None:
            return None
    except Exception:
        return None

    all_verts, all_faces, all_uvs = [], [], []
    offset = 0

    for mesh_obj in glb.meshes:
        for prim in mesh_obj.primitives:
            attrs = prim.attributes
            pos_idx = getattr(attrs, "POSITION", None)
            if pos_idx is None and isinstance(attrs, dict):
                pos_idx = attrs.get("POSITION")
            if pos_idx is None:
                continue
            acc = glb.accessors[pos_idx]
            bv = glb.bufferViews[acc.bufferView]
            start = (bv.byteOffset or 0) + (acc.byteOffset or 0)
            end = start + acc.count * 3 * 4
            verts = np.frombuffer(blob[start:end], dtype=np.float32).reshape(-1, 3)

            idx_val = prim.indices
            if idx_val is not None:
                idx_acc = glb.accessors[idx_val]
                idx_bv = glb.bufferViews[idx_acc.bufferView]
                comp_type = getattr(idx_acc, "componentType", 5123)
                dtype = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32}.get(
                    comp_type, np.uint16)
                idx_start = (idx_bv.byteOffset or 0) + (idx_acc.byteOffset or 0)
                idx_end = idx_start + idx_acc.count * dtype().itemsize
                idx_data = np.frombuffer(blob[idx_start:idx_end], dtype=dtype)
                faces = idx_data.reshape(-1, 3)
            else:
                faces = np.arange(len(verts), dtype=np.uint32).reshape(-1, 3)

            tex_idx = getattr(attrs, "TEXCOORD_0", None)
            if tex_idx is None:
                tex_idx = getattr(attrs, "texcoord_0", None)
            if tex_idx is None and isinstance(attrs, dict):
                tex_idx = attrs.get("TEXCOORD_0")
            if tex_idx is None:
                continue
            uv_acc = glb.accessors[tex_idx]
            uv_bv = glb.bufferViews[uv_acc.bufferView]
            uv_start = (uv_bv.byteOffset or 0) + (uv_acc.byteOffset or 0)
            uv_end = uv_start + uv_acc.count * 2 * 4
            uvs = np.frombuffer(blob[uv_start:uv_end], dtype=np.float32).reshape(-1, 2)

            all_verts.append(verts)
            all_faces.append(faces + offset)
            all_uvs.append(uvs)
            offset += len(verts)

    if not all_verts:
        return None

    verts = np.vstack(all_verts)
    faces = np.vstack(all_faces)
    uvs = np.vstack(all_uvs)

    try:
        tri_mesh = trimesh.Trimesh(vertices=verts, faces=faces)
        defects = trimesh.curvature.vertex_defects(tri_mesh)
    except Exception:
        return None

    face_curv = np.maximum.reduce([
        defects[faces[:, 0]], defects[faces[:, 1]], defects[faces[:, 2]],
    ])
    threshold = (np.percentile(face_curv[face_curv > 0], percentile)
                 if np.any(face_curv > 0) else 0.05)
    salient_faces = face_curv >= threshold

    curvature_map = np.zeros((height, width), dtype=np.float32)

    try:
        from skimage.draw import polygon as _skpoly
        _has_skimage = True
    except ImportError:
        _has_skimage = False

    salient_idx = np.where(salient_faces)[0]
    for i in salient_idx:
        fa = faces[i]
        u0, v0 = uvs[fa[0]]
        u1, v1 = uvs[fa[1]]
        u2, v2 = uvs[fa[2]]
        v0, v1, v2 = 1 - v0, 1 - v1, 1 - v2
        r0 = int(v0 * (height - 1)) % height
        c0 = int(u0 * (width - 1)) % width
        r1 = int(v1 * (height - 1)) % height
        c1 = int(u1 * (width - 1)) % width
        r2 = int(v2 * (height - 1)) % height
        c2 = int(u2 * (width - 1)) % width
        if _has_skimage:
            rr, cc = _skpoly([r0, r1, r2], [c0, c1, c2], shape=(height, width))
            curvature_map[rr, cc] = np.maximum(curvature_map[rr, cc], face_curv[i])
        else:
            r_min = max(0, min(r0, r1, r2))
            r_max = min(height - 1, max(r0, r1, r2))
            c_min = max(0, min(c0, c1, c2))
            c_max = min(width - 1, max(c0, c1, c2))
            for rr in range(r_min, r_max + 1):
                for cc in range(c_min, c_max + 1):
                    u_pt = cc / (width - 1) if width > 1 else 0.5
                    v_pt = rr / (height - 1) if height > 1 else 0.5
                    if _point_in_triangle(u_pt, v_pt, u0, v0, u1, v1, u2, v2):
                        curvature_map[rr, cc] = max(curvature_map[rr, cc], face_curv[i])

    return curvature_map > 0


def _point_in_triangle(px, py, x0, y0, x1, y1, x2, y2):
    """Barycentric test for point in triangle."""
    d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    if abs(d) < 1e-10:
        return False
    a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / d
    b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / d
    c = 1 - a - b
    return 0 <= a <= 1 and 0 <= b <= 1 and 0 <= c <= 1
