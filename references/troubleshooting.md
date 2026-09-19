# Troubleshooting

Start with `python3 scripts/doctor.py`. It checks packages, Blender, Bambu Studio, ffmpeg,
OrcaSlicer, API compatibility and where the config is being read from.

## Setup and connection

| Problem | Fix |
|---|---|
| `Missing LAN connection settings` | `configure.py show`, then set whatever is missing (see [setup](setup.md)) |
| `Printer not reachable at …` | Printer on and awake? LAN mode on? Same network as this computer? Correct IP (it can change after a router restart)? |
| SSL handshake warnings on LAN | Normal: the printer uses self-signed certificates. Handled automatically |
| `API method not found` / attribute errors | `pip install --upgrade bambulabs-api` (needs 2.6.6+) |
| Cloud asks for a verification code | Ask the user for the emailed code, then re-run with `BAMBU_VERIFY_CODE=<code>`. Or switch to LAN mode |
| Commands run in a sandbox can't reach the printer | The agent's sandbox may block local network access. Ask the user to allow it, or to run the command themselves |
| Config ignored after updating the skill | v1.x kept config inside the skill folder. Run `configure.py migrate` |
| `ModuleNotFoundError` | The script ran with a Python that doesn't have `requirements.txt` installed. Use that interpreter, or install into it |

## Camera

| Problem | Fix |
|---|---|
| Snapshot timeout | Camera already in use (Bambu Studio / Handy)? Printer asleep? Wrong IP? |
| `401` / unauthorized | Wrong access code. Check it on the printer (Settings → Device) |
| `ffmpeg not installed` | macOS `brew install ffmpeg` · Linux `apt install ffmpeg` · Windows `winget install ffmpeg` |
| Cloud mode | Snapshots are LAN only |

## Models and generation

| Problem | Fix |
|---|---|
| Generation fails or times out | Try again, try another provider, or make the prompt more specific (see [3d-prompt-guide](3d-prompt-guide.md)) |
| `401` from provider | Wrong or expired API key: `configure.py secret 3d_api_key` |
| Model far too small or large | Pass `--height` to generate, analyze and preview alike. Analyze auto-detects meters, cm and inches |
| Holes, non-manifold edges, flipped normals | Expected for AI meshes. `analyze.py --repair` fixes most of it. Install `pymeshlab` for heavier repair |
| "68 bodies" reported | Usually harmless topology. Check the preview, and use `analyze.py --repair --keep-main` only if pieces are visibly loose |
| Floating fragments visible in the preview | `analyze.py --repair --keep-main`, or `generate.py … --auto-retry 2` |
| Background removal hurt an image-to-3D result | Re-run with `--no-bg-remove` (needs `pip install rembg` to use it at all) |
| Preview fails | Needs Blender 4+. Check `doctor.py`. Without Blender, skip to `bambu.py open` |

## Bambu Studio

| Problem | Fix |
|---|---|
| `Bambu Studio not found` | Install it from bambulab.com/en/download/studio. On Linux, AppImage or Flatpak (`com.bambulab.BambuStudio`) are detected; otherwise open the file manually |
| Multi-color OBJ imports as one color | See [multicolor: importing](multicolor.md#importing-into-bambu-studio). Don't re-run colorize |
| CLI slicing crashes | `slice.py` uses OrcaSlicer because the Bambu Studio CLI crashed in v2.5. Slice in the Bambu Studio GUI instead |

## Known limitations

| Feature | Status |
|---|---|
| Single-color pipeline | Stable |
| Multi-color (colorize) | Pipeline stable. Bambu Studio's vertex-color import sometimes misses colors |
| Parametric modeling | Geometric and functional parts only, single-color STL |
| CLI slicing | OrcaSlicer backend. Optional |
| Auto-print | Works with Developer Mode (signed MQTT + FTPS upload). Disconnects Bambu Studio cloud and Handy |
| Cloud mode | Status and basic control only. No camera, G-code or monitoring |
| Desktop notifications | macOS and Linux (`notify-send`). Windows prints to the console only |
