# Multi-Color (AMS) Workflow

Turns a textured AI model (GLB) into a vertex-color OBJ that Bambu Studio maps to AMS filament
slots. Up to 8 colors. Needs Blender 4+.

## Steps

1. **Size only.** Ask how big it should be. Don't ask the user to pick colors: they come from
   the AI texture. If the user volunteers constraints ("only 3 colors"), use them as colorize
   options.
2. **Generate** (text or image). The provider returns a textured GLB, scaled to the target height:
   ```
   python3 scripts/generate.py text "red and white toy mushroom" --wait --height 70
   ```
   For image-to-3D, check whether the downloaded GLB has a texture. If it doesn't, continue as
   single-color.
3. **Colorize**:
   ```
   python3 scripts/colorize model.glb --height 70 --max_colors 8 --bambu-map
   ```
   This writes `model_multicolor.obj` (vertex colors), a flat preview PNG, and with `--bambu-map`,
   `model_multicolor_color_map.txt` listing the closest Bambu filament for each color (by CIELAB ΔE).
   Take the exact paths from the script output.
4. **Preview**:
   ```
   python3 scripts/preview.py model_multicolor.obj --views turntable --height 70
   ```
5. **Send one consolidated report** (template below) and wait for the user's answer. If they
   want changes, re-run colorize with adjusted options and report again.
6. When approved, run the normal analyze step, then [open in Bambu Studio](#importing-into-bambu-studio).

## Report template

Put everything in one message:

> ## 🎨 [Model name]: multi-color preview
>
> [preview PNG and turntable GIF]
>
> | # | Color | Hex | Share | Suggested filament | ΔE |
> |---|-------|-----|-------|--------------------|----|
> | 1 | yellow | #FFD700 | 58% | PLA Basic Yellow | 3.2 |
> | 2 | brown | #8B4513 | 22% | PLA Basic Brown | 5.1 |
> | … | | | | | |
>
> **N colors, AMS compatible.** How would you like to proceed?
> - Fewer colors: I'll re-run with fewer (e.g. 4)
> - Something looks off: tell me what to change
> - Looks good: I'll open it in Bambu Studio

ΔE below ~5 is a close filament match. Above ~10, mention that the printed color will differ
noticeably.

## Tuning options

Use these only when the user asks for adjustments:

| Option | Default | Effect |
|---|---|---|
| `--max_colors N` | 8 | Maximum colors (1–8; AMS limit is 8, AMS Lite 4) |
| `--min-pct X` | 1.0 | Drop color families below X% of the surface (0 keeps nearly all) |
| `--no-merge` | off | Treat all 12 color families independently (no mutual exclusion) |
| `--island-size N` | 1000 | Merge isolated patches smaller than N texture pixels (0 = off) |
| `--smooth N` | 5 | Boundary smoothing passes (0 = raw) |
| `--subdivide 0-3` | 1 | Mesh subdivision for finer color boundaries (higher = slower, bigger) |
| `--method` | `hybrid` | `hybrid` (HSV + k-means) or `kmeans` |
| `--no-geometry-protect` | off | Disable curvature protection for small features such as eyes and buttons |
| `--colors "#hex,…"` | | Force a fixed palette (legacy) |
| `--bambu-map` | off | Also write the filament suggestion file |

Common requests:
- "Too many colors" → `--max_colors 4`
- "The eyes disappeared" → `--min-pct 0 --island-size 200`
- "Edges look noisy" → `--smooth 8`

## Importing into Bambu Studio

Bambu Studio's vertex-color OBJ import is unreliable. To give it the best chance:

1. Open the OBJ as a **new project** (File → New Project → Import, or
   `python3 scripts/bambu.py open model_multicolor.obj`). Don't use "Import to current plate".
2. Check that the filament list in the right panel shows N colors.
3. If it shows only one color: close Bambu Studio completely, reopen it and import again, or
   drag the OBJ onto an empty window.
4. If it still shows one color, that's a Bambu Studio compatibility issue, not a problem with
   the file. Don't re-run colorize; tell the user, and suggest painting colors manually in
   Bambu Studio as a fallback.

Then the user assigns AMS slots to the colors (the `_color_map.txt` suggestions help) and slices.
