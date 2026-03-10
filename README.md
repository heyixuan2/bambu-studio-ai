# Bambu Studio AI

**The most complete open-source AI agent skill for Bambu Lab 3D printers.**

Idea → Search/Generate → Analyze & Repair → Preview → Bambu Studio → Print → Monitor → Notify

[![ClawHub](https://img.shields.io/badge/ClawHub-bambu--studio--ai-blue)](https://clawhub.ai/heyixuan2/bambu-studio-ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-57%20passed-brightgreen)]()
[![Version](https://img.shields.io/badge/version-1.0.0-blue)]()

---

## Why This Project?

Most 3D printing tools give you one piece of the puzzle — a slicer, a model generator, or a printer controller. **Bambu Studio AI is the full pipeline**: from the moment you have an idea to a finished print, every step is automated, analyzed, and verified.

You tell your AI agent "print me a phone stand", and it handles search, generation, format conversion, printability analysis, mesh repair, multi-color processing, preview rendering, Bambu Studio handoff, print control, live monitoring, and failure detection — all while keeping you in the loop at every decision point.

### What Makes This Different

| | Bambu Studio AI | Typical 3D Print Tools |
|---|---|---|
| **End-to-end** | Idea → finished print in one conversation | Manual: download model, open slicer, configure, upload, monitor separately |
| **AI model generation** | 5 providers, auto prompt enhancement, auto-retry, auto-scale | DIY: manually download from each provider's website |
| **Multi-color** | Auto-detect colors from texture, vertex-color OBJ, AMS filament mapping | Manual: paint in Bambu Studio or use separate tools |
| **Quality assurance** | 11-point printability check, auto mesh repair, dimension verification | Hope it works, waste filament on failures |
| **Smart sizing** | `--height` across entire pipeline — generate, analyze, colorize, preview all use the same target | Manually scale in slicer, hope units are right |
| **Shadow handling** | HSV-based classification immune to baked lighting | Shadow removal artifacts ruin color accuracy |
| **Monitoring** | AI vision analyzes camera feed, auto-pause on failure | Stare at Bambu Handy or walk to the printer |
| **9 printers** | All Bambu Lab models with correct build volumes, temp limits, material compatibility | Usually supports 1-2 models |

---

## Core Capabilities

### 1. Model Search — Find Existing Designs

```bash
python3 scripts/search.py "phone stand" --limit 5
```

Searches **MakerWorld, Printables, Thingiverse, and Thangs** simultaneously. Results are deduplicated and ranked. Community-tested models are always preferred over AI-generated ones for functional parts.

### 2. AI 3D Model Generation — Text-to-3D & Image-to-3D

```bash
python3 scripts/generate.py text "cute cat figurine" --wait --height 60
python3 scripts/generate.py image photo.jpg --wait --height 80
```

**5 providers:** Meshy, Tripo3D, Printpal, 3D AI Studio, Hyper3D Rodin

- **Smart prompt enhancement** — your "phone stand" becomes a print-optimized prompt with wall thickness, base stability, overhang constraints
- **Image-to-3D pipeline** — auto validates image, removes background (`rembg`), enhances prompt, uploads
- **Auto-scale** — AI models come in arbitrary units; `--height` scales to exact mm target
- **Auto-retry** — if mesh has disconnected parts, regenerates with stronger constraints
- **Format detection** — magic-byte validation, auto-rename, GLB→3MF/STL conversion
- **Download integrity** — `.tmp` file + `Content-Length` verification prevents corrupt files

### 3. Parametric Generation — Precision Functional Parts

```bash
python3 scripts/parametric.py bracket --width 30 --height 40 --thickness 3 --hole-diameter 3.2 -o bracket.stl
python3 scripts/parametric.py enclosure --width 60 --depth 40 --height 30 --wall 2 --lid -o case.stl
python3 scripts/parametric.py csg spec.json -o assembly.stl
```

When you need exact dimensions — brackets, enclosures, mounting plates — `manifold3d` CSG modeling generates watertight meshes with sub-mm precision. No AI randomness, just math.

Built-in templates: **box, cylinder, sphere, extrude, L-bracket, plate-with-holes, enclosure, arbitrary CSG from JSON**.

### 4. Multi-Color AMS Pipeline — Texture to Vertex Colors

```bash
python3 scripts/colorize model.glb --height 80 --max_colors 8 --bambu-map
```

The most technically sophisticated part of the project. Converts textured GLB models into vertex-color OBJ files that Bambu Studio maps to AMS filaments.

**Pipeline (6 steps, <2 min):**

| Step | What | How |
|------|------|-----|
| 1. Extract texture | Parse GLB binary directly (no Blender) | `pygltflib` |
| 2. Classify pixels | 4M+ pixels → HSV → 12 color families | Shadow-immune |
| 3. Select colors | Greedy by area, mutual exclusion groups | ≤8 for AMS |
| 4. Assign pixels | Per-pixel CIELAB distance to nearest color | Perceptually accurate |
| 5. Build texture | N-color quantized PNG | Preview + source |
| 6. Vertex colors | Blender subdivide → UV sample → OBJ export | Bambu-ready |

**Why HSV?** AI models bake lighting into textures. A "red" surface in shadow is RGB(120,30,25) — very different from bright red RGB(255,50,40). Traditional color matching fails. HSV classification groups by **hue**, which shadows don't affect. No delight, no albedo extraction, no artifacts.

**Geometry-aware saliency** protects fine details (eyes, edges) from color bleeding during subdivision.

**Bambu filament mapping** finds the closest match from 43 Bambu Lab filament colors (ΔE distance) and generates a mapping file.

### 5. 11-Point Printability Analysis & Auto Repair

```bash
python3 scripts/analyze.py model.stl --height 80 --repair --material PLA
```

| Check | What It Catches |
|-------|----------------|
| Dimensional tolerance | Missing clearance for mating parts |
| Wall thickness | Too thin for material (1.2mm PLA, 1.6mm TPU, 2.0mm PEEK) |
| Load direction | Stress aligned with weak layer lines |
| Overhang angle | >45° faces needing support |
| Print orientation | No flat base = bad adhesion |
| Floating parts | Disconnected pieces that fall during printing |
| Layer height | Optimal for detail vs speed |
| Infill / walls / top layers | Structural integrity recommendations |
| Material compatibility | Printer supports the material? |
| Mesh quality | Watertight, manifold, build volume fit |

**Tiered auto-repair:** Minor issues (holes, normals) → trimesh. Major issues (non-manifold) → PyMeshLab. Stubborn meshes → manual guidance.

**`--height` now always exports** the scaled model to disk as `_scaled` file — no more "scaled in memory but not saved" bugs.

### 6. HQ Preview Rendering

```bash
python3 scripts/preview.py model.obj --views turntable --height 80 -o preview.gif
```

Blender Cycles rendering with automatic material detection:
- **PBR textures** → full material preview
- **Vertex colors** → 3-layer detection (color_attributes → legacy vertex_colors → manual OBJ parse)
- **Plain mesh** → clean studio lighting
- **Turntable** → 360° animated GIF (black background)
- **Dimension verification** → `--height` warns if actual size differs >10% from target

### 7. Full Printer Control — LAN & Cloud

```bash
python3 scripts/bambu.py status          # Printer status
python3 scripts/bambu.py print model.3mf # Start print
python3 scripts/bambu.py snapshot        # Camera photo
python3 scripts/bambu.py ams             # AMS filament details
python3 scripts/bambu.py speed ludicrous # Max speed
python3 scripts/bambu.py gcode "G28"     # Raw G-code
```

**LAN mode** (recommended): MQTT + FTP, full control, camera access, G-code, sub-second response.
**Cloud mode**: Remote access when not on same network, limited features.

Supports **all 9 Bambu Lab printers**: A1 Mini, A1, P1S, P2S, X1C, X1E, H2C, H2S, H2D.

### 8. AI Print Monitoring

```bash
python3 scripts/monitor.py --interval 300 --auto-pause
```

Camera snapshots analyzed by vision AI at configurable intervals:

| Issue | Action |
|-------|--------|
| Stringing | Log, continue |
| Warping | Shorten check interval |
| Layer shift | Notify + recommend pause |
| Bed detachment | **Auto-pause** + alert |
| Spaghetti | **Auto-pause** + alert |

---

## Supported Printers

| Series | Models | Build Volume | Max Speed | Key Feature |
|--------|--------|-------------|-----------|-------------|
| **A** (Entry) | A1 Mini, A1 | 180³ / 256³ mm | 500mm/s | Affordable, open frame |
| **P** (Prosumer) | P1S, P2S | 256³ mm | 500-600mm/s | Enclosed, AMS |
| **X** (Pro) | X1C, X1E | 256³ mm | 500mm/s | Lidar, sealed chamber |
| **H** (High-Perf) | H2C, H2S, H2D | 256³ / 340³ / 350³ mm | 600-1000mm/s | 350°C nozzle, dual extruder |

---

## Quick Start

```bash
# Install
git clone https://github.com/heyixuan2/bambu-studio-ai.git
cd bambu-studio-ai
pip3 install -r requirements.txt

# Verify
python3 scripts/doctor.py

# Try it
python3 scripts/search.py "vase" --limit 3
python3 scripts/bambu.py status
```

**Via ClawHub:**
```bash
clawhub install bambu-studio-ai
```

### Optional Dependencies

| Tool | What For | Install |
|------|----------|---------|
| Blender 4.0+ | Multi-color pipeline, HQ preview | `brew install --cask blender` |
| Bambu Studio | Model verification, slicing | `brew install --cask bambu-studio` |
| rembg | Image background removal | `pip3 install rembg` |
| PyMeshLab | Advanced mesh repair | `pip3 install pymeshlab` |
| ffmpeg | Camera snapshots | `brew install ffmpeg` |

---

## Setup

Run `python3 scripts/doctor.py` to verify all dependencies.

### LAN Mode (Recommended)

1. Printer touchscreen → **Settings → Network → LAN Mode → ON**
2. Note: **IP Address**, **Serial Number**, **Access Code** (Settings → Device)
3. Your computer and printer must be on the same network

### Configuration

**config.json** (shareable):
```json
{
  "model": "A1",
  "mode": "local",
  "printer_ip": "192.168.1.100",
  "serial": "01P00A000000000",
  "3d_provider": "meshy",
  "monitor_level": "standard"
}
```

**.secrets.json** (git-ignored, chmod 600):
```json
{
  "access_code": "printer_lan_access_code",
  "3d_api_key": "your_provider_api_key"
}
```

---

## The Full Pipeline — Example

```
You:   "Print me a cute cat figurine, about 6cm tall"

Agent: Searches MakerWorld, Printables, Thingiverse...
       Found 3 options. None match? Let me generate one.

       generate.py text "cute cat figurine" --wait --height 60
       ✨ Enhanced prompt (print-optimized)
       📏 Target height: 60mm
       ⏳ Generating via Meshy...
       ✅ Done! Auto-scaled to 60mm

       analyze.py cat.3mf --height 60 --repair
       Score 8.5/10 ✅ Watertight ✅ Single piece
       💾 Scaled model: cat_scaled.3mf

       preview.py cat.3mf --views turntable --height 60
       ✅ Height OK: 60.0mm (target 60mm)
       📸 cat_preview.gif

       Opens in Bambu Studio → you verify → slice → confirm

       bambu.py print cat.3mf
       monitor.py --interval 300
       🎉 Print complete!
```

---

## Architecture

```
bambu-studio-ai/                    ~7,800 lines of Python
├── SKILL.md                        Agent instructions (660 lines, 6 workflows)
├── scripts/
│   ├── generate.py                 AI generation (5 providers, image pipeline, auto-scale)
│   ├── analyze.py                  11-point analysis, tiered repair, auto-orient
│   ├── colorize/                   Multi-color pipeline (6 modules)
│   │   ├── __init__.py             Pipeline orchestration
│   │   ├── color_science.py        sRGB↔CIELAB, HSV classification
│   │   ├── selection.py            Greedy color selection, mutual exclusion
│   │   ├── texture.py              GLB texture extraction, quantization
│   │   ├── geometry.py             Saliency detection, feature protection
│   │   ├── vertex_colors.py        Blender vertex color application
│   │   └── bambu_map.py            Filament color matching (43 colors)
│   ├── parametric.py               CSG modeling (manifold3d)
│   ├── preview.py                  Blender Cycles rendering
│   ├── bambu.py                    Printer control (LAN + Cloud)
│   ├── monitor.py                  AI print monitoring
│   ├── search.py                   Model search (4 sources)
│   ├── slice.py                    OrcaSlicer CLI
│   ├── doctor.py                   Dependency verification
│   └── common.py                   Shared config, constants
├── tests/                          57 tests (pytest)
├── references/                     Protocol docs, filament colors, prompt guides
└── .cursor/rules/                  Agent memory (colorize, parametric)
```

---

## Material Guide

| Material | Nozzle | Bed | Enclosure | Best For |
|----------|--------|-----|-----------|----------|
| **PLA** | 200-210°C | 60°C | Open | General purpose |
| **PETG** | 230-250°C | 80°C | Open | Strength, water resistance |
| **TPU** | 220-240°C | 50°C | Open | Flexible parts, phone cases |
| **ABS/ASA** | 240-260°C | 100°C | Required | Outdoor, heat resistance |
| **Nylon/PA** | 260-280°C | 80°C | Required | Mechanical parts |
| **PEEK/PEI** | 340-350°C | 120°C | H2C/H2D only | Aerospace, medical |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Can't connect (LAN) | LAN Mode ON? Correct IP? Same network? |
| Model too small/large | Use `--height` to specify exact mm |
| Multi-color shows single color | Import OBJ in new Bambu Studio window (not "import to current") |
| Non-manifold mesh | `analyze.py --repair` auto-fixes most cases |
| Generation failed | Try different provider, more detailed prompt |
| Camera not working | LAN mode only, requires ffmpeg |

Run `python3 scripts/doctor.py` to diagnose dependency issues.

---

## Contributing

PRs welcome! Areas that need help:

- Additional 3D generation providers
- Better mesh repair algorithms
- Print failure pattern recognition
- Windows/Linux Bambu Studio integration
- Localization

---

## Version History

| Version | Highlights |
|---------|-----------|
| **1.0.0** | Pipeline sizing fix (`--height` across all tools), smart unit detection in colorize, Printpal format fix, preview dimension verification, parametric modeling (`manifold3d`), 57-test suite, download integrity, MQTT timeout, search dedup |
| **0.23.0** | Colorize → 6-module package, common.py, pyproject.toml, pytest, BYTE_COLOR fix |
| **0.22.0** | Colorize v4: HSV + CIELAB + vertex-color OBJ. Preview renderer (Blender Cycles) |
| **0.20.0** | CLI slicing, auto-orient, Rodin provider, X.509 MQTT |
| **0.18.0** | Model search (4 sources), notifications |

---

## License

MIT — see [LICENSE](LICENSE)
