"""Turn colour samples into one filament per triangle, and tidy the result on the mesh.

Everything here works on the mesh's own adjacency (triangles that share an edge), never
on the texture image, so there is no texture-space cleanup whose cost grows with the
image size and no UV seam that neighbours can't see across.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import trimesh
from numpy.typing import NDArray

from bambu_studio_ai.color.lab import FloatArray

WELD_TOLERANCE_MM = 1e-5
UNLABELLED = -1
AGREEING_NEIGHBOURS = 2
"""Neighbours that must share a colour before smoothing gives it to a triangle."""
_MAX_FILL_ROUNDS = 10_000


@dataclass(frozen=True)
class WeldedMesh:
    """A mesh whose duplicate vertices (UV seams) are joined and zero-area triangles dropped."""

    vertices: FloatArray
    faces: NDArray[np.int64]
    source_face: NDArray[np.int64]
    """For each kept triangle, its index in the unwelded mesh."""


def weld(vertices: FloatArray, faces: NDArray[np.int64]) -> WeldedMesh:
    """Join vertices at the same position; drop triangles that collapse to a line."""
    keys = np.round(vertices / WELD_TOLERANCE_MM).astype(np.int64)
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    welded = np.reshape(inverse, -1)[faces]
    keep = (
        (welded[:, 0] != welded[:, 1])
        & (welded[:, 1] != welded[:, 2])
        & (welded[:, 0] != welded[:, 2])
    )
    return WeldedMesh(
        vertices=vertices[first],
        faces=welded[keep].astype(np.int64),
        source_face=np.flatnonzero(keep).astype(np.int64),
    )


def face_adjacency(faces: NDArray[np.int64]) -> NDArray[np.int64]:
    """``(E, 2)`` pairs of triangles that share an edge."""
    # trimesh.graph is untyped; the result is an (E, 2) integer array.
    pairs = cast("object", trimesh.graph.face_adjacency(faces=faces))  # pyright: ignore[reportUnknownMemberType]
    return np.reshape(np.asarray(pairs, dtype=np.int64), (-1, 2))


def vote_faces(
    sample_face: NDArray[np.int64],
    sample_label: NDArray[np.int64],
    weight: FloatArray,
    face_count: int,
    colour_count: int,
) -> NDArray[np.int64]:
    """Label each triangle with the colour covering most of it; ``-1`` if nothing is visible."""
    flat = np.bincount(sample_face * colour_count + sample_label, weight, face_count * colour_count)
    votes = np.reshape(flat, (face_count, colour_count))
    labels = np.argmax(votes, axis=1).astype(np.int64)
    labels[votes.sum(axis=1) <= 0] = UNLABELLED
    return labels


def fill_unlabelled(
    labels: NDArray[np.int64], pairs: NDArray[np.int64], colour_count: int
) -> NDArray[np.int64]:
    """Give triangles with no visible colour the majority colour of their labelled neighbours.

    Grows inwards one ring per round; triangles in a region with no labelled triangle at
    all (a fully transparent shell) get the most common colour of the model.
    """
    labels = np.copy(labels)
    for _ in range(_MAX_FILL_ROUNDS):
        missing = labels == UNLABELLED
        if not missing.any():
            return labels
        votes = _neighbour_votes(labels, pairs, colour_count)
        reachable = missing & (votes.sum(axis=1) > 0)
        if not reachable.any():
            break
        labels[reachable] = np.argmax(votes[reachable], axis=1)
    known = labels[labels != UNLABELLED]
    fallback = int(np.bincount(known).argmax()) if len(known) else 0
    labels[labels == UNLABELLED] = fallback
    return labels


def smooth(
    labels: NDArray[np.int64], pairs: NDArray[np.int64], colour_count: int, passes: int
) -> NDArray[np.int64]:
    """Remove speckle: a triangle takes the colour that at least two of its neighbours share.

    A strip one triangle wide survives (each of its triangles has two neighbours of its
    own colour), and a colour is never smoothed away entirely: if a pass would remove the
    last triangle of a colour, that colour's triangles keep their original label.
    """
    original = labels
    for _ in range(passes):
        votes = _neighbour_votes(labels, pairs, colour_count)
        best = np.argmax(votes, axis=1)
        best_count = votes.max(axis=1)
        own_count = votes[np.arange(len(labels)), labels]
        switch = (best_count >= AGREEING_NEIGHBOURS) & (best_count > own_count)
        labels = np.where(switch, best, labels).astype(np.int64)
    lost = np.setdiff1d(np.unique(original), np.unique(labels))
    if len(lost):
        restore = np.isin(original, lost)
        labels = np.where(restore, original, labels).astype(np.int64)
    return labels


def _neighbour_votes(
    labels: NDArray[np.int64], pairs: NDArray[np.int64], colour_count: int
) -> FloatArray:
    """``(F, K)`` count of each face's labelled neighbours per colour."""
    face_count = len(labels)
    first, second = pairs[:, 0], pairs[:, 1]
    index: list[NDArray[np.int64]] = []
    for face, neighbour in ((first, second), (second, first)):
        known = labels[neighbour] != UNLABELLED
        index.append(face[known] * colour_count + labels[neighbour[known]])
    flat = np.bincount(np.concatenate(index), minlength=face_count * colour_count)
    return np.reshape(flat, (face_count, colour_count)).astype(np.float64)
