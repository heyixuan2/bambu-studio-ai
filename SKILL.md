---
name: bambu-studio-ai
description: >-
  End-to-end 3D printing for Bambu Lab printers. Finds models online (MakerWorld, Printables,
  Thingiverse), generates them with AI (text-to-3D, image-to-3D) or as exact-dimension parametric
  CAD, checks and repairs printability, converts textures to AMS multi-color, renders previews,
  opens them in Bambu Studio, then starts, controls and monitors prints over LAN or cloud.
  Use this whenever the user wants to 3D print something, design or model an object for printing,
  work with STL/3MF/OBJ/GLB files for a printer, check on or control a Bambu Lab printer
  (A1, A1 Mini, P1S, P2S, X1C, X1E, X2D, H2C, H2S, H2D), or asks about AMS filament, slicing
  or print progress, even if they don't say "Bambu".
license: MIT
compatibility: >-
  Python 3.10+ with requirements.txt installed. Optional: Blender 4+ (previews, multi-color),
  Bambu Studio, ffmpeg (camera), OrcaSlicer (CLI slicing). Printer control needs LAN or Bambu cloud
  access; AI generation needs a provider API key. macOS, Linux, Windows.
metadata:
  author: TieGaier
  version: "2.0.0"
  homepage: https://github.com/heyixuan2/bambu-studio-ai
---

# Bambu Studio AI

Turns "print me X" into a finished print on a Bambu Lab printer:

```
request → get a model (search / AI text or image / parametric / user file)
        → analyze + repair → [multi-color] → preview → user reviews and slices in Bambu Studio
        → print (only when the user says so) → monitor
```

The work is done by Python scripts in this skill's `scripts/` folder. This file tells you which one
to run at each step and where the user needs to be in the loop.

## Running the scripts

- `scripts/…` paths below are relative to the folder that contains this SKILL.md. Call them by
  full path **from the user's working directory**, and don't `cd` into the skill folder. Downloads,
  snapshots and logs go to `./bambu-output/` in the current directory (override with
  `BAMBU_OUTPUT_DIR`). `parametric.py` and `analyze.py`/`preview.py` write next to the file you
  name (`-o` or the input), so pass a path inside `bambu-output/` if you want everything together.
- Use a Python interpreter that has `requirements.txt` installed. On first use run
  `scripts/doctor.py`. If packages are missing, ask the user before installing them
  (`python3 -m pip install -r <skill-folder>/requirements.txt`, or into a venv / with `uv pip`).
- Every script has `--help`. Scripts print progress and end with the paths of the files they
  wrote, so take file names from their output rather than guessing.
- AI generation with `--wait` takes 1–5 minutes; a Blender turntable render takes 30–60 s. Run
  these in the background if your environment supports it, and tell the user what's happening.
- Printer settings live in `~/.bambu-studio-ai/` (see [setup](references/setup.md)). Only
  printer commands need them. Searching, generating, analyzing and previewing all work without
  a configured printer, so don't block those tasks on setup.

## Ground rules

A 3D printer is a physical machine that runs unattended for hours with hot parts. Mistakes
waste filament and time, and occasionally damage hardware. These rules keep the user in control:

1. **The user decides when to print.** Run `bambu.py print … --confirmed` only after the user has
   seen the model and explicitly said to print it. `--confirmed` is your statement that this
   happened. AI-generated meshes often have defects that analysis can't catch.
2. **Analyze every model**, whether downloaded, generated or supplied by the user.
   `analyze.py --repair` catches wrong units, floating parts, thin walls and parts that don't
   fit the build plate. Add `--orient` for downloaded and AI models, which arrive in arbitrary
   orientations, but not for parametric parts (see step 3).
3. **Show the preview before opening Bambu Studio.** The user should see the model before they
   spend time slicing it.
4. **Know the size before AI generation.** Generation costs API credits and minutes, and scale
   is the thing most often gotten wrong. If the user didn't give one, ask: "How big? e.g. 80 mm tall".
   Parametric parts need exact dimensions.
5. **Confirm disruptive printer commands** (`cancel`, `gcode`, `speed ludicrous`, enabling
   auto-pause) unless the user asked for exactly that. Pausing when something is clearly going
   wrong is fine.
6. **Keep secrets out of the conversation.** Store access codes, passwords and API keys with
   `configure.py secret` and never echo them back.

## Showing results to the user

Agents differ in what they can display, so adapt:

- If your interface can show images (attachments, inline markdown images, a file viewer),
  show the preview PNG/GIF directly.
- Otherwise open it for the user (`open` on macOS, `xdg-open` on Linux, `start` on Windows)
  and give the path.
- If you can look at images yourself, check the preview before presenting it. Floating
  fragments, a model lying the wrong way or a mangled shape are easier to spot by eye than
  in the numbers.

## Workflow

### 1. Understand the request

Find out the following, asking only for what's missing, in one message rather than an interrogation:

- **What** to print and **how big** (mm)
- **Single or multi-color** (multi-color needs an AMS)
- **Material**: default PLA. **Purpose**: decorative or functional, which changes walls and infill.

Then pick a route:

| The request looks like… | Route |
|---|---|
| Exact dimensions or tolerances, screw holes, "fits a …", brackets, enclosures, mounts, plates | **Parametric**: exact, free, instant |
| Common everyday object (phone stand, hook, cable clip, vase) or user unsure | **Search first**, offer AI generation if nothing fits |
| Character, figurine, organic or artistic shape | **AI text-to-3D** |
| User provides a photo | **Image-to-3D** |
| User provides an STL / 3MF / OBJ / GLB / STEP | **Use their file** |

If the route isn't clear, offer the choice in one line: "I can search MakerWorld/Printables for
existing designs, which are usually better tested, or generate a custom one with AI. Which do you prefer?"

### 2. Get the model

**Search**

```
python3 scripts/search.py "phone stand" --limit 5
```

This searches MakerWorld, Printables, Thingiverse and Thangs. Show the user each result's name,
source and link, then let them pick. Model sites often need a login to download, so if you
can't fetch the file, give the link and ask the user to download it.

**AI text-to-3D**: needs a provider and API key (see [setup](references/setup.md#ai-generation)).

```
python3 scripts/generate.py text "cute cat figurine" --wait --height 60
```

The prompt is rewritten for printability automatically (`--raw` skips this), and the result is
scaled to `--height` mm. The first time, tell the user that AI models are drafts to review, not
finished parts. Prompt tips: [references/3d-prompt-guide.md](references/3d-prompt-guide.md).

**Image-to-3D**

```
python3 scripts/generate.py image photo.jpg --wait --height 80
```

Prompt enhancement is automatic (`--raw` turns it off), and so is background removal if the
optional `rembg` package is installed (`--no-bg-remove` turns it off). It works best with one
centered object on a plain background. Don't ask for colors, because they come from the image.

**Parametric**: collect exact dimensions, screw sizes (an M3 screw needs a 3.2 mm clearance
hole) and fit (clearance or press fit).

```
python3 scripts/parametric.py bracket --width 30 --height 40 --thickness 3 --hole-diameter 3.2 -o bracket.stl
python3 scripts/parametric.py enclosure --width 60 --depth 40 --height 30 --wall 2 --lid -o case.stl
python3 scripts/parametric.py csg spec.json -o assembly.stl      # anything more complex
```

Other shapes: `box`, `cylinder`, `sphere`, `extrude`, `plate-with-holes`. The output is
watertight, dimensionally exact and single-color. Tell the user the dimensions and volume, and
let them adjust before you continue. Tolerance tables and the CSG JSON format are in
[references/manifold-examples.md](references/manifold-examples.md).

**Multi-color**: generate as above, since the textured GLB carries the colors, then follow
[references/multicolor.md](references/multicolor.md). It covers colorizing, the color report
and a Bambu Studio import quirk. Don't ask the user to choose colors upfront, because they are
detected from the texture.

### 3. Analyze and repair

```
python3 scripts/analyze.py model.3mf --orient --repair --height 60 --material PLA --purpose decorative
```

The build-volume and material checks use the configured printer, falling back to A1. When no
printer is configured but the user named one, pass `--printer "A1 Mini"` (any of the 10 models).

This runs an 11-point check (walls, overhangs, floating parts, orientation, build volume,
material and printer compatibility, …), repairs and orients the mesh, and detects the units. It
may write several files (`_oriented`, `_scaled`, `_repaired`, …). Its last line,
`➡️ Use this file for the next steps: …`, names the one to continue with.

Pass `--height` and `--orient` for AI-generated and downloaded models: they arrive at random
sizes and orientations. Leave both off for parametric parts. Their dimensions are already
exact, and they were designed with the print orientation built in (largest flat face down,
teardrop side holes pointing up). Auto-orient only optimises for stability and can flip such a
part upside down while keeping the same footprint, so the mistake is easy to miss.

The overhang figure is area-weighted and material-aware, and "Supports: needed" is a hint,
not a verdict. For parts you designed flat on the plate, tell the user supports are not
needed.

Report the score, the repairs, any warnings and recommended settings, for example:
"Score 8/10 · repaired 58K non-manifold edges · walls 1.5 mm ✅ · overhangs 3% ✅ · suggest 0.20 mm
layers, 15% infill, PLA at 210 °C."

AI meshes often report dozens of "bodies". This is usually non-manifold topology rather than
loose pieces, so look at the preview before using `--keep-main` or regenerating.

### 4. Preview

```
python3 scripts/preview.py model_scaled.3mf --views turntable --height 60   # 360° GIF
python3 scripts/preview.py model_scaled.3mf                                 # single PNG, faster
```

This needs Blender 4+. `--height` warns you if the model isn't the intended size. Show the
preview to the user (see [Showing results](#showing-results-to-the-user)). Without Blender, say
so and go straight to Bambu Studio, which has its own 3D view.

### 5. Hand off to Bambu Studio

```
python3 scripts/bambu.py open model_scaled.3mf
```

This works on macOS, Windows and Linux. Then ask the user to review and slice:

> I've opened it in Bambu Studio. Please check the shape and the size (shown in the bottom bar),
> look for floating pieces, then slice (Ctrl/Cmd+R) and check the time, filament use and supports.
> Tell me when it looks good, or what to change.

Wait for their answer. If they want changes, go back to the relevant step. `scripts/slice.py`
(CLI slicing through OrcaSlicer) exists, but use it only when the user asks. Slicing visually in
Bambu Studio is where people catch problems.

### 6. Print

- **Manual (default, `print_mode: manual`)**: the user starts the print from Bambu Studio or
  Bambu Handy. Offer to watch for it starting (step 7).
- **Auto (`print_mode: auto`, needs Developer Mode)**: see [setup](references/setup.md#print-modes).
  Only after the user explicitly says to print:
  `python3 scripts/bambu.py print model.3mf --confirmed [--ams-mapping 0,1,2]`

### 7. Monitor (optional, ask first)

Ask: "Want me to keep an eye on the print? I can pause it if something looks seriously wrong."
Then use whatever your environment supports (details in [references/monitoring.md](references/monitoring.md)):

- **You can run a command in the background and read its output later**:
  `python3 scripts/monitor.py --wait-start 30 --interval 300 [--auto-pause]`. Relay each
  `📢 NOTIFY` line to the user together with the latest snapshot.
- **You can schedule recurring tasks**: run `python3 scripts/monitor.py --once` on a schedule.
  It keeps its state between runs.
- **Neither**: check when the user asks (`bambu.py progress` and `bambu.py snapshot`), or
  suggest they run `monitor.py` in a terminal, where it shows desktop notifications.

Monitoring and snapshots need LAN mode.

### Checklist before you say you're done

```
[ ] Size, colors and material known
[ ] Model obtained (search / generate / parametric / user file)
[ ] analyze.py --repair run (plus --orient/--height for downloaded and AI models) and results reported
[ ] Preview shown to the user
[ ] Opened in Bambu Studio; user reviewed and sliced it
[ ] Print started only after the user explicitly approved it
```

## Printer commands

Quick questions like "is my print done?" or "what's in the AMS?" don't need the workflow. Run the
command and answer.

| Task | Command |
|---|---|
| Status / progress | `bambu.py status` (`--json`), `bambu.py progress` |
| Hardware info, AMS filaments | `bambu.py info`, `bambu.py ams` |
| Camera snapshot (LAN, ffmpeg) | `bambu.py snapshot` |
| Pause / resume / cancel | `bambu.py pause` · `resume` · `cancel` |
| Speed, light | `bambu.py speed silent\|standard\|sport\|ludicrous` · `bambu.py light on\|off` |
| Upload a file to the printer | `bambu.py upload model.3mf` |
| Raw G-code (LAN) | `bambu.py gcode "G28"` |
| Open a model in Bambu Studio | `bambu.py open model.3mf` |

## First-time setup

If a printer command reports missing settings, run `python3 scripts/configure.py show` and walk
the user through [references/setup.md](references/setup.md). The short version for LAN mode:

```
python3 scripts/configure.py set model "A1 Mini" mode local printer_ip 192.168.1.50 serial 01P00A000000000
printf '%s' "$ACCESS_CODE" | python3 scripts/configure.py secret access_code
python3 scripts/bambu.py status
```

## Common mistakes

| Mistake | Instead |
|---|---|
| Generating before knowing the size | Ask for the size first. It's one question and saves a paid generation. |
| Going from generate.py straight to Bambu Studio | Run analyze.py, then preview.py, in between |
| Saying "the model is ready" without showing it | Show the preview image or GIF |
| Skipping analysis because the model came from a model site | Downloads can have wrong units or broken meshes too |
| Regenerating because analysis reports 60+ bodies | Check the preview first; it's usually harmless topology |
| Starting a print because the user said "looks good" about the preview | Ask explicitly whether to start printing now |
| Running scripts from inside the skill folder | Run them from the user's directory so outputs land there |
| Re-running colorize when Bambu Studio shows only one color | It's an import quirk, see [multicolor](references/multicolor.md#importing-into-bambu-studio) |

## Reference files

Read these when the task calls for them:

| File | When |
|---|---|
| [references/setup.md](references/setup.md) | First-time setup, LAN vs cloud, manual vs auto-print, all settings, env vars, file locations |
| [references/multicolor.md](references/multicolor.md) | Multi-color / AMS: colorize, color report template, tuning, importing into Bambu Studio |
| [references/monitoring.md](references/monitoring.md) | Watching a print: strategies, alerts, auto-pause, status message format |
| [references/troubleshooting.md](references/troubleshooting.md) | Connection, camera, generation, mesh and import problems; known limitations |
| [references/model-specs.md](references/model-specs.md) | Build volumes, temperature limits and materials for all 10 printers |
| [references/3d-prompt-guide.md](references/3d-prompt-guide.md) | Writing prompts for AI generation |
| [references/manifold-examples.md](references/manifold-examples.md) | Parametric parts: tolerances, CSG JSON, design rules |
| [references/security.md](references/security.md) | What the skill stores, which network endpoints it calls, and why |
| [references/bambu-mqtt-protocol.md](references/bambu-mqtt-protocol.md), [3d-generation-apis.md](references/3d-generation-apis.md) | Protocol and API details for debugging |
