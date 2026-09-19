#!/usr/bin/env python3
"""
Render a preview of a 3D model: one PNG, a labelled 2x2 grid, or a 360° turntable GIF.

Uses the best renderer installed: Blender (materials, textures, GPU), else Bambu
Studio's own thumbnail (perspective view only, flat filament colour), else a built-in
software renderer that needs only the Python requirements. The model is shown in the
file's own axes with Z up, the way Bambu Studio and analyze.py read it.

Usage:
  python3 scripts/preview.py model.3mf                              # perspective PNG
  python3 scripts/preview.py model.stl --views all                  # perspective, front / side, top
  python3 scripts/preview.py model.glb --views turntable --height 60   # 360° GIF + size check
  python3 scripts/preview.py model.stl --json                       # one JSON object on stdout

Exit codes: 0 ok · 1 rendering failed · 2 bad arguments or unreadable model ·
3 no renderer available (missing Python requirements, or FBX without Blender).
"""

import argparse
import json
import logging
import sys
from pathlib import Path

from common import find_blender, use_utf8_stdio

try:
    from bambu_studio_ai import render
except ImportError as missing:  # numpy, Pillow or trimesh not installed
    render = None
    IMPORT_ERROR = missing

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_DEPENDENCY = 0, 1, 2, 3

MODES = ("perspective", "front", "side", "top", "all", "turntable")
RENDERER_CHOICES = ("auto", "blender", "bambu-studio", "software")

EPILOG = """\
Renderers (--renderer auto tries them in this order):
  blender       Cycles render with the file's materials and textures, on the GPU when
                one is available. The first GPU render on a machine compiles Cycles'
                GPU kernels once (about 2 minutes; measured 105 s on an Apple M2 Max),
                then they are cached. Use --cpu to skip that.
  bambu-studio  Bambu Studio's own plate thumbnail: 0.4 s, flat filament colour,
                perspective view only. Skipped for models that carry colour.
  software      Built-in renderer (numpy + Pillow): every view, colours and textures,
                flat shading. Always available.
"""


def build_parser():
    parser = argparse.ArgumentParser(
        description="Render a PNG, a 2x2 grid or a turntable GIF of a 3D model.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("model", help="model file: STL, OBJ, PLY, 3MF, GLB/GLTF, OFF (FBX needs Blender)")
    parser.add_argument("-o", "--output",
                        help="output file (default: <model>_preview.png, or .gif for a turntable)")
    parser.add_argument("-v", "--views", default="perspective", choices=MODES,
                        help="perspective (default), front, side, top; 'all' = 2x2 grid "
                             "(perspective, front / side, top); 'turntable' = 360° GIF")
    parser.add_argument("--height", type=float, default=0,
                        help="expected height in mm: warns when the model's Z size is more than 10%% off")
    parser.add_argument("--renderer", default="auto", choices=RENDERER_CHOICES,
                        help="force one renderer instead of the best available (default: auto)")
    parser.add_argument("--cpu", action="store_true",
                        help="Blender: render on the CPU instead of the GPU")
    parser.add_argument("--timeout", type=float, metavar="SECONDS",
                        help="Blender time limit (default: 200 s for one view, 260 s for all, 900 s for a turntable)")
    parser.add_argument("--json", action="store_true", help="print one JSON object on stdout")
    return parser


def fail(message, code, *, as_json, kind):
    """Report an error on stderr (and as JSON on stdout with --json); return the exit code."""
    if as_json:
        print(json.dumps({"error": {"type": kind, "message": message}}))
    print(f"❌ {message}", file=sys.stderr)
    return code


def default_output(model, views):
    suffix = ".gif" if views == "turntable" else ".png"
    return model.with_name(model.stem + "_preview" + suffix)


def format_result(result):
    data = result.to_dict()
    renderer = {"blender": "Blender", "bambu-studio": "Bambu Studio", "software": "software renderer"}
    device = f", {data['device']}" if data["device"] and data["device"] != "CPU" else ""
    views = ", ".join(data["views"])
    x, y, z = data["dimensions_mm"]
    lines = [
        f"📸 {views} rendered with {renderer[data['renderer']]}{device} in {data['seconds']:.1f} s",
        f"Size: {x:.1f} × {y:.1f} × {z:.1f} mm (X × Y × Z, as Bambu Studio reads the file) · "
        f"{data['faces']:,} triangles · colour: {data['material']}",
    ]
    check = data["height_check"]
    if check and check["ok"]:
        lines.append(f"✅ Height {check['actual_mm']:.1f} mm matches the target {check['expected_mm']:g} mm")
    elif check:
        lines.append(f"⚠️ Height {check['actual_mm']:.1f} mm is {check['diff_pct']:.0f}% off the target "
                     f"{check['expected_mm']:g} mm")
    lines += [f"⚠️ {warning}" for warning in data["warnings"]]
    lines.append(f"➡️ Use this file: {data['output_file']}")
    return "\n".join(lines)


def main(argv=None):
    args = build_parser().parse_args(argv)
    as_json = args.json
    if render is None:
        return fail(f"missing Python package ({IMPORT_ERROR.name}): "
                    "python3 -m pip install -r requirements.txt",
                    EXIT_DEPENDENCY, as_json=as_json, kind="dependency")
    # Progress goes to stderr, so --json keeps stdout to the one result document.
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)
    logging.getLogger("bambu_studio_ai").setLevel(logging.INFO)

    model = Path(args.model).expanduser().resolve()
    output = Path(args.output).expanduser().resolve() if args.output else default_output(model, args.views)
    request = render.PreviewRequest(
        model=model,
        output=output,
        mode=args.views,
        expected_height_mm=args.height or None,
        renderer=args.renderer,
        timeout_s=args.timeout,
        cpu_only=args.cpu,
    )
    tools = render.Tools(blender=find_blender(), bambu_studio=_tuple_or_none(render.find_bambu_studio_cli()))
    try:
        result = render.render_preview(request, tools)
    except (render.ModelError, render.RequestError) as exc:
        return fail(str(exc), EXIT_USAGE, as_json=as_json, kind="bad_request")
    except render.RendererMissingError as exc:
        return fail(str(exc), EXIT_DEPENDENCY, as_json=as_json, kind="dependency")
    except render.RenderFailedError as exc:
        return fail(str(exc), EXIT_FAILED, as_json=as_json, kind="render_failed")
    if as_json:
        print(json.dumps(result.to_dict()))
    else:
        print(format_result(result))
    return EXIT_OK


def _tuple_or_none(command):
    return tuple(command) if command else None


if __name__ == "__main__":
    use_utf8_stdio()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⏹️ Cancelled.", file=sys.stderr)
        sys.exit(130)
