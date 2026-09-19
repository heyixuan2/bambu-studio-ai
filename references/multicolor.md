# Multi-Color (AMS) Workflow

`colorize` turns a textured model (GLB, glTF or OBJ) into a **Bambu Studio project 3MF whose
triangles are already painted** with up to 8 filaments. Open it and the filament list already
holds one filament per colour; you only map them to AMS slots. Pure Python, no Blender.

## Two ways to get colour into Bambu Studio

| | `colorize` → project 3MF | Textured GLB straight into Bambu Studio 2.7+ |
|---|---|---|
| Who picks the colours | The script (or you, with `--colors`), before Bambu Studio opens | Bambu Studio, when it converts the texture to paint on import |
| What you can show the user first | Palette, share per colour, nearest Bambu filament, preview PNG | Nothing until it is open in Bambu Studio |
| Colour boundaries | Per triangle: as fine as the mesh (AI models have 100k+ triangles) | Bambu Studio's own conversion |
| Works for | GLB, glTF, OBJ with a base-colour texture, material colours or vertex colours | GLB with a texture |

Use `colorize` by default: the agent can report the colours, limit them to the user's AMS and
hand over a file that is ready to slice. Use the GLB directly when the user wants to pick colours
interactively in Bambu Studio, or when `colorize` stops with "colours lost" (texture detail finer
than the mesh) and the user wants to keep that detail.

## Steps

1. **Size only.** Ask how tall it should be. Don't ask the user to pick colours: they come from
   the texture. Colour limits the user volunteers ("only 3 colours", "I have white, black and
   red loaded") become `--max-colors 3` or `--colors "#FFFFFF,#161616,#C12E1F"`.
2. **Generate** (text or image). The provider returns a textured GLB:
   ```
   python3 scripts/generate.py text "red and white toy mushroom" --wait --height 70
   ```
3. **Colorize**:
   ```
   python3 scripts/colorize model.glb --height 70 --json
   ```
   Writes `model_multicolor.3mf` and `model_multicolor_preview.png` next to the input. With
   `--json`, stdout is one object: `output_file`, `preview_file`, `size_mm`, `metric`
   (`CIEDE2000`), `warnings`, and `colors`: for each filament its `hex`, `area_pct` and
   `suggested_filament` (`line`, `name`, `hex`, `delta_e`). Take paths from there.
4. **Check** with `python3 scripts/analyze.py model_multicolor.3mf` for the report only. Its
   repaired or re-oriented copies don't keep the paint, so fix problems on the GLB and colorize
   again.
5. **Send one consolidated report** (template below) with the preview and wait for the answer.
   If they want changes, re-run colorize with adjusted options and report again.
6. **Open** it: `python3 scripts/bambu.py open model_multicolor.3mf` (see
   [importing](#importing-into-bambu-studio)).

## Report template

> ## 🎨 [Model name]: multi-color preview
>
> [preview PNG]
>
> | # | Colour | Share | Nearest Bambu filament | ΔE |
> |---|--------|-------|------------------------|----|
> | 1 | #F4D03F | 58% | PLA Basic Yellow | 3.2 |
> | 2 | #7A4A1E | 22% | PLA Basic Brown | 5.1 |
> | … | | | | |
>
> **N filaments.** How would you like to proceed?
> - Fewer colours: I'll re-run with fewer (e.g. 3)
> - Use the filaments you have loaded: tell me their colours
> - Looks good: I'll open it in Bambu Studio

ΔE is CIEDE2000 between the detected colour and the catalogue colour: under about 3 looks the
same, above about 10 the print will visibly differ, so say so.

## Options

| Option | Default | Effect |
|---|---|---|
| `--max-colors N` | 4 | Most filaments to use, 1–8 (AMS and AMS lite hold 4 each) |
| `--colors "#hex,…"` | | Use exactly these filaments, in this order, instead of detecting colours |
| `--min-area F` | 0.002 | Smallest share of the surface that gets its own filament (0.002 = 0.2 %) |
| `--height MM` | keep | Scale uniformly to this height (Z) |
| `--smooth N` | 1 | Speckle-removal passes over the mesh; 0 turns it off |
| `--format obj` | `3mf` | Vertex-colour OBJ instead of a project (Bambu Studio then asks you to map colours) |
| `-o FILE` | `<input>_multicolor.3mf` | Output path; a `.obj` suffix implies `--format obj` |
| `--json` | | One JSON object on stdout |

Common requests:
- "Too many colours" → `--max-colors 3`
- "The eyes disappeared" → `--min-area 0.0005`
- "Use what's in my AMS" → read the tray colours with `python3 scripts/bambu.py ams --json`, then
  `--colors` with those hex values
- "Spots of the wrong colour" → `--smooth 2`

Exit codes: `0` done · `1` failed (no texture or colours in the model, a colour would be lost,
unreadable file, write error) · `2` bad arguments or file not found. When a colour would be lost,
the message names it and gives the `--colors` list without it.

## How it works

Each triangle's colour is read from its own material's base-colour texture (times
`baseColorFactor` and vertex colours), at several points spread over the triangle; transparent
texels and texture space no triangle uses are ignored. A palette is picked in CIELAB: similar
shades (CIEDE2000 under 10) merge, colours under `--min-area` join their nearest neighbour, and a
small but distinct feature such as eyes keeps its own filament. Each triangle gets the filament
covering most of it, and isolated specks take their neighbours' colour. The model is converted to
Z-up millimetres and centred on the plate.

## Importing into Bambu Studio

1. Open the `.3mf` as a project (double-click it, File → Open Project, or
   `python3 scripts/bambu.py open model_multicolor.3mf`). It is a Bambu Studio project, so the
   plate shows the model already coloured and the filament list shows one filament per colour.
2. The project uses the Bambu Lab A1 0.4 mm profiles with Bambu PLA Basic. For another printer,
   pick it in the printer list: the filaments and the paint stay. On an A1 mini, press Arrange (A)
   afterwards, because the model sits at the centre of the larger A1 plate.
3. Map the filaments to AMS slots: set each filament's type and colour to what is loaded, or map
   them in the send dialog when printing. The paint follows the filament number, so filament 1
   stays filament 1 whatever spool it maps to.
4. Slice and check the preview: every colour should appear, with a prime tower. The tower sits
   at the back left and the model at the centre, so a model over about 140 mm across can overlap
   it ("G-code conflicts" / "path conflicts with WipeTower"): press Arrange (A) or drag the tower.

A `--format obj` file goes through Bambu Studio's colour-mapping dialog on import instead: choose a
filament for each colour there.
