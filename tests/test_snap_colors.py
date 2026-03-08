"""Tests for vertex color snapping — ensure exact N colors in output."""

import os
import tempfile

import numpy as np
import pytest


def _make_test_obj(path, n_vertices=100, n_colors=3):
    """Write a minimal OBJ with vertex colors that have slight drifts."""
    rng = np.random.RandomState(42)
    targets = rng.rand(n_colors, 3)
    lines = []
    for i in range(n_vertices):
        cidx = i % n_colors
        drift = rng.uniform(-0.02, 0.02, 3)
        rgb = np.clip(targets[cidx] + drift, 0, 1)
        lines.append(f"v {i*0.1:.4f} 0.0000 0.0000 {rgb[0]:.4f} {rgb[1]:.4f} {rgb[2]:.4f}\n")
    lines.append("f 1 2 3\n")
    with open(path, "w") as f:
        f.writelines(lines)
    return targets


class TestSnapVertexColors:
    def test_snap_produces_exact_colors(self):
        from colorize.vertex_colors import snap_vertex_colors
        with tempfile.NamedTemporaryFile(suffix=".obj", mode="w", delete=False) as f:
            path = f.name
        try:
            targets = _make_test_obj(path, n_vertices=90, n_colors=3)
            selected = [
                {"rgb": targets[i], "lab": np.zeros(3)}
                for i in range(3)
            ]
            snap_vertex_colors(path, selected)

            # Read back and count unique color strings
            unique_colors = set()
            with open(path) as f:
                for line in f:
                    if line.startswith("v "):
                        parts = line.split()
                        if len(parts) >= 7:
                            color_str = " ".join(parts[4:7])
                            unique_colors.add(color_str)

            assert len(unique_colors) == 3, (
                f"Expected exactly 3 unique colors, got {len(unique_colors)}")
        finally:
            os.unlink(path)

    def test_snap_handles_empty_obj(self):
        from colorize.vertex_colors import snap_vertex_colors
        with tempfile.NamedTemporaryFile(suffix=".obj", mode="w", delete=False) as f:
            f.write("# empty OBJ\nf 1 2 3\n")
            path = f.name
        try:
            selected = [{"rgb": np.array([1, 0, 0]), "lab": np.zeros(3)}]
            snap_vertex_colors(path, selected)  # should not crash
        finally:
            os.unlink(path)
