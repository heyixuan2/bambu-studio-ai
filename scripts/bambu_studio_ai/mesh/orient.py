"""Choose a print orientation and put the model on the plate.

A model that already rests on a large flat base (a cup, a phone stand, a bracket) is left
the way it was designed and only dropped onto the plate. Anything else is turned onto a
stable resting pose with a large flat base, preferring the widest footprint for its
height. Overhangs are not weighed yet: choosing by support cost is a planned improvement.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from bambu_studio_ai.mesh import _backend
from bambu_studio_ai.mesh._backend import FloatArray
from bambu_studio_ai.mesh.checks import contact_mask

#: Keep the current orientation when its flat contact with the plate is at least this
#: share of the largest contact any resting pose offers.
KEEP_BASE_SHARE = 0.5
#: Resting poses considered, most probable first.
MAX_POSES = 20
_MIN_HEIGHT_MM = 1e-3


@dataclass(frozen=True)
class OrientResult:
    """What ``orient_for_printing`` did and why."""

    rotated: bool
    moved: bool
    """Whether the mesh changed at all (rotation or dropping onto the plate)."""
    reason: str
    contact_before_mm2: float
    contact_after_mm2: float

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict."""
        return {
            "rotated": self.rotated,
            "moved": self.moved,
            "reason": self.reason,
            "contact_before_mm2": self.contact_before_mm2,
            "contact_after_mm2": self.contact_after_mm2,
        }


def orient_for_printing(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, OrientResult]:
    """Return an oriented copy of ``mesh`` resting on z = 0, and what was done."""
    identity = np.eye(4)
    before = _contact_area(mesh, identity)
    try:
        poses, probabilities = _backend.stable_poses(mesh, _centre(mesh))
    except (ValueError, RuntimeError) as exc:
        # qhull cannot build a hull for flat or degenerate meshes.
        return _placed(mesh, identity, before, f"kept: no resting poses could be computed ({exc})")
    poses, probabilities = poses[:MAX_POSES], probabilities[:MAX_POSES]
    contacts = [_contact_area(mesh, pose) for pose in poses]
    largest = max(contacts, default=0.0)
    if before > 0 and before >= KEEP_BASE_SHARE * largest:
        reason = f"kept: already rests on a flat base ({before:.0f} mm2 on the plate)"
        return _placed(mesh, identity, before, reason)
    # Among the poses with a large flat base (all of them if none has one), take the one
    # that is most likely to stay put and has the widest footprint for its height.
    scores = [
        probability * _footprint_per_height(mesh, pose)
        if contact >= KEEP_BASE_SHARE * largest
        else -1.0
        for pose, probability, contact in zip(poses, probabilities, contacts, strict=True)
    ]
    if not scores:
        return _placed(mesh, identity, before, "kept: no resting poses found")
    best = int(np.argmax(scores))
    reason = (
        f"turned onto a flat base ({contacts[best]:.0f} mm2 on the plate, was {before:.0f} mm2)"
    )
    return _placed(mesh, poses[best], before, reason)


def _placed(
    mesh: trimesh.Trimesh, transform: FloatArray, before: float, reason: str
) -> tuple[trimesh.Trimesh, OrientResult]:
    """Apply ``transform``, drop the result onto z = 0 and describe it."""
    rotated = not np.allclose(transform[:3, :3], np.eye(3))
    work = mesh.copy()
    if rotated:
        _backend.apply_transform(work, transform)
    drop = -float(work.bounds[0][2])
    if drop:
        work.apply_translation([0.0, 0.0, drop])
    after = _contact_area(work, np.eye(4))
    result = OrientResult(
        rotated=rotated,
        moved=rotated or bool(drop),
        reason=reason,
        contact_before_mm2=round(before, 1),
        contact_after_mm2=round(after, 1),
    )
    return work, result


def _contact_area(mesh: trimesh.Trimesh, transform: FloatArray) -> float:
    """Flat area on the plate if ``mesh`` were placed with ``transform``."""
    rotation = transform[:3, :3]
    normal_z = np.asarray(mesh.face_normals, dtype=np.float64) @ rotation[2]
    vertex_z = np.asarray(mesh.vertices, dtype=np.float64) @ rotation[2]
    face_top = vertex_z[np.asarray(mesh.faces)].max(axis=1)
    mask = contact_mask(normal_z, face_top, float(vertex_z.min()))
    return float(np.asarray(mesh.area_faces, dtype=np.float64)[mask].sum())


def _footprint_per_height(mesh: trimesh.Trimesh, transform: FloatArray) -> float:
    """X/Y bounding-box area over height, for ``mesh`` placed with ``transform``."""
    placed = np.asarray(mesh.vertices, dtype=np.float64) @ np.transpose(transform[:3, :3])
    size = np.ptp(placed, axis=0)
    return float(size[0] * size[1] / max(float(size[2]), _MIN_HEIGHT_MM))


def _centre(mesh: trimesh.Trimesh) -> FloatArray:
    """Centre of mass for closed meshes; the surface centroid when the volume is undefined."""
    if mesh.is_watertight and float(mesh.volume) > 0:
        return np.asarray(mesh.center_mass, dtype=np.float64)
    return np.asarray(mesh.centroid, dtype=np.float64)
