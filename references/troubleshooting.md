# Troubleshooting

Start with `python3 scripts/doctor.py`. It checks packages, Blender, Bambu Studio (the app, its
command line and its printer profiles) and where the config is being read from.

## Setup and connection

| Problem | Fix |
|---|---|
| `Printer not configured: missing …` | `configure.py show`, then set whatever is missing (see [setup](setup.md#2-printer-status-optional)) |
| `no report from … within 20 s` | Printer on? Same network as this computer? Correct IP (it can change after a router restart; check Settings → Network)? Correct serial number? |
| `printer refused the connection: Not authorized` | Wrong LAN access code. Read it again on the printer (Settings → Network); it changes if the user refreshed it |
| Commands run in a sandbox can't reach the printer | The agent's sandbox may block local network access. Ask the user to allow it, or to run the command themselves |
| `bambu.py print` / `pause` / `snapshot` … "was removed" | Printer control was removed in v2.1 (it needs LAN Only + Developer Mode). Open the file in Bambu Studio and print from there; pause from the printer or Bambu Handy |
| Config ignored after updating the skill | v1.x kept config inside the skill folder. Run `configure.py migrate` |
| `ModuleNotFoundError` | The script ran with a Python that doesn't have `requirements.txt` installed. Use that interpreter, or install into it |

## Models and generation

| Problem | Fix |
|---|---|
| Generation fails | The error names the cause (credits, content filter, bad image). Try again, try another provider (`--provider tripo`), or make the prompt more specific (see [3d-prompt-guide](3d-prompt-guide.md)) |
| Generation "still running" after `--wait` | Normal for busy providers. Run the printed `next_command` (`generate.py download <task id>`) later; it resumes without paying again |
| `401` from provider | Wrong or expired API key: `configure.py secret <provider>_api_key` (`3d_api_key` is the fallback) |
| Model far too small or large | Pass `--height` to generate, analyze and preview alike. Analyze only converts units on clear evidence (a 3MF's declared unit, `--unit`, or a model under 0.5 units read as metres) and otherwise reports what it assumed |
| AI model lying on its side in Bambu Studio | Models from `generate.py` are turned upright automatically. For a GLB from elsewhere, run `analyze.py --orient` |
| Holes, non-manifold edges, flipped normals | Expected for AI meshes. `analyze.py` fixes small defects by default and `--repair` does more. Install `pymeshlab` for heavier repair |
| "68 bodies" reported | Usually harmless topology. Check the preview, and use `analyze.py --keep-main` only if pieces are visibly loose; it refuses when no body clearly dominates |
| Floating fragments visible in the preview | `analyze.py --keep-main`, or generate again with a clearer prompt |
| Preview is slow the first time | The first Blender GPU render on a machine compiles its kernels once (about 2 minutes). Use `--cpu`, or `--renderer software` for a quick check |

## Bambu Studio

| Problem | Fix |
|---|---|
| `Bambu Studio not found` | Install it from bambulab.com/en/download/studio. On Linux, AppImage or Flatpak (`com.bambulab.BambuStudio`) are detected; otherwise open the file manually |
| Colorize stops with "colours lost" | Use the `--colors` list in the message, raise `--max-colors`, or import the GLB into Bambu Studio 2.7+ directly (see [multicolor](multicolor.md)) |

## Slicing (`slice.py`)

`slice.py` runs Bambu Studio's own command line with Bambu Studio's own printer profiles, so the
sliced 3MF keeps the printer's start sequence (bed levelling, vibration compensation, AMS loading)
unchanged. Verified with Bambu Studio 02.07.01.62 on macOS; the Windows and Linux paths are
untested.

| Problem | Fix |
|---|---|
| `No printer given and none configured` | Pass `--printer P1S` (or any model `slice.py --help` lists), or `configure.py set model P1S` |
| `Bambu Studio not found` | Install Bambu Studio 02.05.02 or newer and start it once. On Linux, or for an unusual install, set `BAMBU_STUDIO_CLI` to the executable and `BAMBU_STUDIO_PROFILES` to the folder that holds `BBL.json` |
| Crashes or prints nothing | Bambu Studio 02.05.00–02.05.01 crashed in command-line mode; update. On Windows the command line may print nothing (bambulab/BambuStudio#9802, open): slice in the app instead |
| `can't read STEP files` | The command line reads STL, 3MF, OBJ, AMF, PLY, glTF/GLB and FBX. Export one of those, or open the STEP with `bambu.py open` and slice in the app |
| `No … process profile` / `No … filament profile` / `no … nozzle profile` | The message lists what exists for that printer. `slice.py --list-profiles --printer P1S` shows nozzles, quality presets, layer heights and materials |
| `Filaments are not compatible with the plate type` | That filament can't print on the printer's default plate (Textured PEI). Pick the plate and slice in the app |
| Estimate looks long for a small part | It includes Bambu's start sequence (heating, bed levelling, purge: several minutes), like the "total estimated time" Bambu Studio shows |

## Known limitations

| Feature | Status |
|---|---|
| Single-color pipeline | Stable |
| Multi-color (colorize) | Writes a painted Bambu Studio project; verified by headless slicing with filament changes. Opening it in the Bambu Studio app is not yet tested on every printer |
| Parametric modeling | Geometric and functional parts only, single-color STL |
| CLI slicing | Bambu Studio command line with its own profiles; one filament per slice. Needs Bambu Studio installed |
| Auto-print | Works with Developer Mode (signed MQTT + FTPS upload). Disconnects Bambu Studio cloud and Handy |
| Cloud mode | Status and basic control only. No camera, G-code or monitoring |
| Desktop notifications | macOS and Linux (`notify-send`). Windows prints to the console only |
