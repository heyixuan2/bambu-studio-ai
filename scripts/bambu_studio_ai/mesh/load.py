"""Read and write mesh files, and name the files derived from them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import trimesh

from bambu_studio_ai.mesh import _backend

#: Formats that derived files keep. Bambu Studio imports all four and trimesh writes them.
KEEP_FORMAT_SUFFIXES = frozenset({".stl", ".obj", ".glb", ".3mf"})
#: Format for derived files when the input's format is not in ``KEEP_FORMAT_SUFFIXES``.
FALLBACK_SUFFIX = ".stl"

# 3MF is the only common format whose unit declaration can be trusted: glTF is metres by
# specification, but trimesh reports "meters" for every GLB, including millimetre ones.
_DECLARED_UNIT_SUFFIXES = frozenset({".3mf"})


class MeshLoadError(Exception):
    """The file is missing, unreadable or holds no triangles."""


class MeshSaveError(Exception):
    """A derived mesh could not be written."""


@dataclass(frozen=True)
class LoadedMesh:
    """A mesh and what its file says about units."""

    mesh: trimesh.Trimesh
    declared_unit: str | None
    """Unit named inside the file (3MF only), e.g. ``"millimeter"``; ``None`` if unknown."""


def load_mesh(path: Path) -> LoadedMesh:
    """Read a mesh file, flattening scenes into one mesh.

    Raises:
        MeshLoadError: the file is missing, unreadable or empty.
        ImportError: a reader dependency is missing (networkx is needed for 3MF).
    """
    if not path.is_file():
        raise MeshLoadError(f"file not found: {path}")
    try:
        geometry = _backend.load(path)
    except ImportError:
        raise
    except Exception as exc:
        # trimesh raises many unrelated types for corrupt or unsupported files.
        raise MeshLoadError(f"could not read {path.name}: {exc}") from exc
    if not isinstance(geometry, trimesh.Trimesh) or len(geometry.faces) == 0:
        raise MeshLoadError(f"{path.name} contains no triangles")
    declared = None
    if path.suffix.lower() in _DECLARED_UNIT_SUFFIXES and geometry.units:
        declared = str(geometry.units)
    return LoadedMesh(mesh=geometry, declared_unit=declared)


def derived_path(source: Path, suffix: str) -> Path:
    """Name for a file derived from ``source``, e.g. ``part_scaled.3mf``.

    The format is kept when it is one of ``KEEP_FORMAT_SUFFIXES``; anything else
    becomes STL. Chaining steps chains suffixes: ``part_scaled_oriented.3mf``.
    """
    extension = source.suffix if source.suffix.lower() in KEEP_FORMAT_SUFFIXES else FALLBACK_SUFFIX
    return source.with_name(f"{source.stem}{suffix}{extension}")


def save_mesh(mesh: trimesh.Trimesh, path: Path) -> None:
    """Write ``mesh`` to ``path`` in the format its suffix names.

    Raises:
        MeshSaveError: the file could not be written.
        ImportError: a writer dependency is missing (networkx is needed for 3MF).
    """
    try:
        _backend.export(mesh, path)
    except ImportError:
        raise
    except Exception as exc:
        raise MeshSaveError(f"could not write {path}: {exc}") from exc
