# Bambu Studio AI

**An agent skill that takes Bambu Lab 3D printing from idea to finished print.**

Works with any agent that supports the open [Agent Skills](https://agentskills.io) `SKILL.md`
standard: Claude Code, OpenAI Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode, Windsurf,
Cline, Goose, Amp, Kiro, Roo Code, OpenClaw and more.

[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-SKILL.md-8A2BE2)](https://agentskills.io)
[![CI](https://github.com/heyixuan2/bambu-studio-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/heyixuan2/bambu-studio-ai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-2.0.0-blue)](#version-history)

```
"Print me a cute cat figurine, about 6 cm tall"
   → search / AI-generate → analyze & repair → multi-color → preview
   → you review & slice in Bambu Studio → print → monitor with camera snapshots
```

---

## Install

### 1. Add the skill to your agent

The quickest way is the [`skills` CLI](https://github.com/vercel-labs/skills). It detects which
agents you have installed and puts the skill in the right place:

```bash
npx skills add heyixuan2/bambu-studio-ai          # this project only
npx skills add heyixuan2/bambu-studio-ai -g       # all projects (your user account)
npx skills add heyixuan2/bambu-studio-ai -g -a claude-code -a codex   # specific agents
```

Update later with `npx skills update bambu-studio-ai`.

<details>
<summary><b>Manual install (git clone)</b></summary>

Clone into your agent's skills folder. The folder **must** be named `bambu-studio-ai`.

```bash
git clone https://github.com/heyixuan2/bambu-studio-ai.git ~/.claude/skills/bambu-studio-ai
```

| Agent | For all projects | For one project |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| OpenAI Codex | `~/.codex/skills/` | `.agents/skills/` |
| Cursor | `~/.cursor/skills/` | `.agents/skills/` |
| Gemini CLI | `~/.gemini/skills/` | `.agents/skills/` |
| GitHub Copilot | `~/.copilot/skills/` | `.agents/skills/` |
| OpenCode | `~/.config/opencode/skills/` | `.agents/skills/` |
| Windsurf | `~/.codeium/windsurf/skills/` | `.windsurf/skills/` |
| Cline | `~/.agents/skills/` | `.agents/skills/` |
| Goose | `~/.config/goose/skills/` | `.goose/skills/` |
| OpenClaw | `~/.openclaw/skills/` | `skills/` |

`.agents/skills/` is shared by most agents, so one project-level clone there covers Codex,
Cursor, Gemini CLI, Copilot, OpenCode, Cline and Amp at once.

</details>

<details>
<summary><b>Claude.ai / Claude Desktop (upload)</b></summary>

Zip the folder and upload it under Settings → Capabilities → Skills. Search, generation,
parametric modeling and analysis work there. Printer control needs a machine on the same
network as your printer, so use a local agent (Claude Code, Codex, …) for that.

</details>

### 2. Install the Python dependencies

Agent skill installers copy files but don't install packages, so install them once:

```bash
cd ~/.claude/skills/bambu-studio-ai          # wherever the skill ended up
python3 -m pip install -r requirements.txt   # or: uv pip install -r requirements.txt
python3 scripts/doctor.py                    # checks everything
```

Optional tools, which `doctor.py` tells you about:

| Tool | Used for | Install |
|---|---|---|
| [Bambu Studio](https://bambulab.com/en/download/studio) | Reviewing and slicing models | macOS `brew install --cask bambu-studio` · Windows/Linux: installer, AppImage or Flatpak |
| [Blender 4+](https://www.blender.org/download/) | Preview renders, multi-color pipeline | macOS `brew install --cask blender` · Linux `snap install blender --classic` · Windows installer |
| ffmpeg | Camera snapshots | `brew install ffmpeg` · `apt install ffmpeg` · `winget install ffmpeg` |
| OrcaSlicer | Optional CLI slicing | [github.com/SoftFever/OrcaSlicer](https://github.com/SoftFever/OrcaSlicer) |
| `rembg`, `pymeshlab` | Photo background removal, heavy mesh repair | `pip install rembg pymeshlab` |

### 3. Connect your printer

Ask your agent to *"set up my Bambu printer"*. It walks you through it. Or do it yourself:

```bash
python3 scripts/configure.py set model A1 mode local printer_ip 192.168.1.50 serial 01P00A000000000
printf '%s' 'YOUR_ACCESS_CODE' | python3 scripts/configure.py secret access_code
python3 scripts/bambu.py status
```

LAN mode: on the printer touchscreen, turn on LAN mode and note the IP, serial number and access
code. Settings are stored in `~/.bambu-studio-ai/`, outside the skill folder, so updates never
wipe them. See [references/setup.md](references/setup.md) for cloud mode, auto-print and AI
provider keys.

---

## Try it

Talk to your agent normally. The skill activates on its own:

- *"Print me a cute cat figurine, about 6 cm tall"*
- *"Design a wall bracket for a 32 mm pipe with two M4 screw holes"*
- *"Turn this photo into a 3D print, 8 cm tall, in full color"*
- *"Find me a good cable organizer on MakerWorld"*
- *"Is my print done? Show me the camera"*
- *"What filament is loaded in my AMS?"*

The agent always shows you a preview, opens the model in Bambu Studio for you to check and slice,
and never starts a print without your explicit go-ahead.

---

## What it can do

| Capability | Script | Highlights |
|---|---|---|
| **Model search** | `search.py` | MakerWorld, Printables, Thingiverse, Thangs; deduplicated |
| **AI text/image-to-3D** | `generate.py` | Meshy, Tripo3D, Printpal, 3D AI Studio, Hyper3D Rodin; print-aware prompt enhancement, auto-scale to `--height`, retries, format conversion |
| **Parametric CAD** | `parametric.py` | Exact-dimension functional parts with `manifold3d`: boxes, brackets, plates with holes, enclosures, arbitrary CSG from JSON; always watertight |
| **Printability analysis** | `analyze.py` | 11-point check (walls, overhangs, floating parts, orientation, build volume, material/printer fit); tiered auto-repair; auto-orient; unit detection |
| **Multi-color (AMS)** | `colorize` | Texture → HSV families → CIELAB assignment → vertex-color OBJ, ≤ 8 colors, nearest Bambu filament match |
| **Preview** | `preview.py` | Blender Cycles renders, 360° turntable GIF, size verification |
| **Bambu Studio handoff** | `bambu.py open` | Opens the model on macOS, Windows or Linux |
| **Printer control** | `bambu.py` | Status, AMS, camera, pause/resume/cancel, speed, light, G-code, upload, print (LAN MQTT/FTPS or cloud) |
| **Monitoring** | `monitor.py` | Waits for the print to start, progress reports, stall/temperature/pause alerts, snapshots, optional auto-pause |
| **Setup** | `configure.py`, `doctor.py` | Settings and secrets without hand-editing JSON; dependency diagnostics |

Supports all 10 current Bambu Lab printers: **A1 Mini, A1, P1S, P2S, X1C, X1E, X2D, H2C, H2S, H2D**
([specs](references/model-specs.md)).

---

## How it's organized

```
bambu-studio-ai/
├── SKILL.md                 What the agent reads: workflow, ground rules, commands (~300 lines)
├── references/              Loaded on demand: setup, multicolor, monitoring, troubleshooting,
│                            printer specs, prompt guide, CSG patterns, protocol notes, security
├── scripts/                 The tools (plain Python CLIs, all with --help)
│   ├── common.py            Shared config, paths, printer data, cross-platform helpers
│   ├── configure.py         Settings and secrets  →  ~/.bambu-studio-ai/
│   ├── doctor.py            Dependency check
│   ├── search.py  generate.py  parametric.py  analyze.py  preview.py
│   ├── colorize/            Multi-color package (python3 scripts/colorize …)
│   ├── bambu.py             Printer control + open in Bambu Studio
│   ├── monitor.py           Print monitoring
│   └── slice.py             Optional OrcaSlicer CLI slicing
├── tests/                   pytest suite, including SKILL.md spec compliance
└── research/                Design notes (not loaded by agents)
```

The skill follows the Agent Skills approach of progressive disclosure. Agents see only the name
and description until a 3D-printing task comes up, then load `SKILL.md`, and open reference
files only when a step needs them.

**Where your data goes**

| What | Where | Override |
|---|---|---|
| Settings, secrets (chmod 600), cloud token, certificates | `~/.bambu-studio-ai/` | `BAMBU_STUDIO_AI_HOME` |
| Generated models, previews, snapshots, logs | `./bambu-output/` in your working directory | `BAMBU_OUTPUT_DIR` |

See [references/security.md](references/security.md) for every network endpoint the skill talks to.

---

## Using it without an agent

Every script is a normal CLI:

```bash
python3 scripts/search.py "vase" --limit 3
python3 scripts/generate.py text "cute cat figurine" --wait --height 60
python3 scripts/analyze.py bambu-output/models/cat.3mf --orient --repair --height 60
python3 scripts/preview.py bambu-output/models/cat_scaled.3mf --views turntable
python3 scripts/bambu.py open bambu-output/models/cat_scaled.3mf
python3 scripts/monitor.py --wait-start 30 --interval 300
```

---

## Upgrading from v1.x

v2.0 turns this from an OpenClaw/ClawHub skill into a standard Agent Skill:

- **Frontmatter follows the Agent Skills spec.** The OpenClaw-specific install and env metadata is
  gone. Install Python dependencies with `pip install -r requirements.txt`.
- **Config moved** from the skill folder to `~/.bambu-studio-ai/`. Old files are still read.
  Run `python3 scripts/configure.py migrate` to move them.
- **Outputs moved** from `<skill>/output/` to `./bambu-output/` in your working directory.
- **Fixed:** printer IP, serial and access code in `config.json` / `.secrets.json` are now actually
  used. v1.x only read them from environment variables, which OpenClaw injected.
- **New:** `configure.py`, `bambu.py open` (cross-platform), `monitor.py --wait-start`, Linux
  desktop notifications, fast failure (~12 s) when the printer is unreachable.

---

## Development

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q          # includes SKILL.md spec + link checks
python3 -m ruff check .
pip install "git+https://github.com/agentskills/agentskills.git#subdirectory=skills-ref"
skills-ref validate "$PWD"    # official Agent Skills validator
```

Contributions welcome, especially: more generation providers, better mesh repair, print-failure
recognition from camera images, and Windows/Linux testing.

---

## Version history

| Version | Highlights |
|---|---|
| **2.0.0** | Universal Agent Skill: spec-compliant `SKILL.md` with progressive disclosure, config moved to `~/.bambu-studio-ai/`, `configure.py`, cross-platform `bambu.py open`, `monitor.py --wait-start`, config.json connection bug fixed, fast fail on unreachable printer, printer-aware temperature alerts, skills-ref validation in CI |
| **1.0.2** | X2D support, MIT license text fix, CI for pytest + ruff |
| **1.0.0** | `--height` across the pipeline, smart unit detection, parametric modeling (`manifold3d`), test suite, download integrity |
| **0.23.0** | Colorize → 6-module package, `common.py`, pytest |
| **0.22.0** | Colorize v4 (HSV + CIELAB + vertex-color OBJ), Blender preview renderer |
| **0.20.0** | CLI slicing, auto-orient, Rodin provider, X.509 MQTT |

---

## License

MIT, see [LICENSE](LICENSE).
