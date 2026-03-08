#!/usr/bin/env python3
"""
CLI entry point for the colorize package.

Usage:
  python3 scripts/colorize model.glb --height 80
  python3 scripts/colorize model.glb --height 80 --max_colors 4
  python3 scripts/colorize model.glb --colors "#FFFF00,#000000,#FF0000,#FFFFFF" --height 80
  python3 scripts/colorize model.glb --height 80 --bambu-map
  python3 scripts/colorize model.glb --height 80 --no-geometry-protect
"""

import os
import sys
import argparse

# Ensure scripts/ is in path for `from common import ...`
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from colorize import colorize


def main():
    parser = argparse.ArgumentParser(
        description="🎨 Multi-color converter v4 for Bambu Lab AMS (GLB → vertex-color OBJ)",
        epilog="Pipeline: Extract texture → Pixel classify → Greedy select → "
               "CIELAB assign → Vertex color → OBJ",
    )
    parser.add_argument("input", help="Input model (GLB/GLTF/OBJ/FBX/STL)")
    parser.add_argument("--output", "-o", help="Output OBJ path")
    parser.add_argument("--min-pct", type=float, default=1.0,
                        help="Min %% for color families / sub-clusters to keep "
                             "(default 1.0, set 0 to keep nearly everything)")
    parser.add_argument("--max_colors", "-n", type=int, default=8, choices=range(1, 9),
                        help="Maximum colors (1-8, default 8)")
    parser.add_argument("--height", type=float, default=0, help="Target height mm (0=keep)")
    parser.add_argument("--subdivide", type=int, default=1, choices=[0, 1, 2, 3],
                        help="Subdivision (0=raw, 1=default, 2-3=high)")
    parser.add_argument("--colors", "-c",
                        help="Manual hex colors (legacy, comma-separated)")
    parser.add_argument("--no-merge", action="store_true",
                        help="Disable family mutual exclusion "
                             "(all 12 families independent)")
    parser.add_argument("--method", choices=["hybrid", "kmeans"], default="hybrid",
                        help="Color selection: hybrid (HSV+k-means) or kmeans")
    parser.add_argument("--island-size", type=int, default=1000,
                        help="Island cleanup threshold in pixels (0=disabled)")
    parser.add_argument("--smooth", type=int, default=5,
                        help="Majority vote smoothing passes (0=disabled)")
    parser.add_argument("--bambu-map", action="store_true",
                        help="Output _color_map.txt with suggested Bambu filaments")
    parser.add_argument("--no-geometry-protect", action="store_true",
                        help="Disable curvature-based protection for eyes/buttons")

    args = parser.parse_args()

    if not args.output:
        args.output = os.path.splitext(args.input)[0] + "_multicolor.obj"

    result = colorize(
        args.input, args.output,
        max_colors=args.max_colors,
        height=args.height,
        subdivide=args.subdivide,
        colors=args.colors,
        min_pct=getattr(args, "min_pct", 1.0) / 100,
        no_merge=getattr(args, "no_merge", False),
        island_size=getattr(args, "island_size", 1000),
        smooth=getattr(args, "smooth", 5),
        method=getattr(args, "method", "hybrid"),
        bambu_map=getattr(args, "bambu_map", False),
        geometry_protect=not getattr(args, "no_geometry_protect", False),
    )
    if result is None:
        sys.exit(1)


if __name__ == "__main__":
    main()
