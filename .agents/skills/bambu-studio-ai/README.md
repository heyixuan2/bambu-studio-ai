# 🖨️ Bambu Studio AI

Full-stack Bambu Lab 3D printing skill for [OpenClaw](https://github.com/openclaw/openclaw).

**Idea → Search/Generate → Analyze & Repair → Preview → Print → Monitor → Notify**

[![ClawHub](https://img.shields.io/badge/ClawHub-bambu--studio--ai-blue)](https://clawhub.ai/heyixuan2/bambu-studio-ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## Table of Contents

- [Features](#features)
- [Supported Printers](#supported-printers)
- [Model Requirements](#model-requirements)
- [Installation](#installation)
- [Setup](#setup)
- [The Full Pipeline](#the-full-pipeline)
- [Model Sourcing](#model-sourcing-search-vs-generate)
- [AI 3D Generation](#ai-3d-generation)
- [Model Analysis & Repair](#model-analysis--repair)
- [Print Monitoring](#print-monitoring)
- [Connection Modes](#connection-modes)
- [Configuration](#configuration)
- [Commands Reference](#commands-reference)
- [Material Guide](#material-guide)
- [Troubleshooting](#troubleshooting)
- [Project Structure](#project-structure)
- [Contributing](#contributing)

---

## Features

| Feature | Description |
|---------|-------------|
| 🖨️ **Printer Control** | Status, print, pause, resume, cancel, speed, light, G-code |
| 🔎 **Model Search** | Search Printables, MakerWorld, Thingiverse, Thangs for existing models |
| 🎨 **AI 3D Generation** | Text-to-3D and Image-to-3D via Meshy, Tripo3D, Printpal, or 3D AI Studio |
| 🔍 **Model Analysis** | 11-point printability check before every print |
| 🔧 **Auto Mesh Repair** | Fix non-manifold edges, holes, bad normals automatically |
| 🔄 **Format Conversion** | Auto-convert GLB/OBJ to 3MF/STL (Bambu Lab compatible) |
| 📸 **Camera** | Live snapshots from printer camera (LAN mode) |
| 🔍 **AI Print Monitoring** | Periodic snapshots → AI anomaly detection → auto-pause |
| 📦 **AMS Management** | Filament slot status, low-filament alerts (LAN mode) |
| 🔔 **Notifications** | Print complete/fail alerts via Discord, iMessage, Telegram, WhatsApp, Slack |
| 🌐 **Dual Mode** | LAN (recommended, full features) + Cloud (remote, limited) |

---

## Supported Printers

All 9 current Bambu Lab models:

### A Series (Entry Level)

| | A1 Mini | A1 |
|---|---------|-----|
| Build Volume | 180×180×180mm | 256×256×256mm |
| Max Speed | 500mm/s | 500mm/s |
| Max Nozzle Temp | 300°C | 300°C |
| Enclosure | Open | Open |
| AMS | AMS Lite | AMS Lite |
| Best For | Small prints, beginners | General purpose |

### P Series (Prosumer)

| | P1S | P2S |
|---|---------|-----|
| Build Volume | 256×256×256mm | 256×256×256mm |
| Max Speed | 500mm/s | 600mm/s |
| Max Nozzle Temp | 300°C | 300°C |
| Enclosure | Enclosed | Enclosed |
| AMS | AMS | AMS 2 Pro |
| Best For | ABS/ASA printing | Fast + enclosed |

### X Series (Professional)

| | X1C | X1E |
|---|---------|-----|
| Build Volume | 256×256×256mm | 256×256×256mm |
| Max Speed | 500mm/s | 500mm/s |
| Enclosure | Enclosed | Full sealed + HEPA |
| Features | Lidar, AI detection | Industrial sealed chamber |
| Best For | Multi-material | Industrial/medical |

### H Series (High-Performance)

| | H2C | H2S | H2D |
|---|---------|------|------|
| Build Volume | 256×256×256mm | 340×320×340mm | 350×320×325mm |
| Max Speed | 600mm/s | 1000mm/s | 600mm/s |
| Max Nozzle Temp | **350°C** | 300°C | **350°C** |
| Extruders | 1 | 1 | **2 (Dual)** |
| Enclosure | 65°C heated chamber | Enclosed | Enclosed |
| Extras | High-temp materials | Ultra-fast + large | Laser + cutting modules |
| Best For | PEEK/PEI | Speed + volume | Multi-material + laser |

---

## Model Requirements

This skill has 700+ lines of instructions with multi-step branching flows. The AI model running it needs to reliably follow complex instructions.

| Tier | Models | Notes |
|------|--------|-------|
| ✅ **Recommended** | Claude Opus 4, Claude Sonnet 4.5, GPT-4o, GPT-5.x, Gemini 2.5 Pro, DeepSeek-V3, Qwen-Max, or equivalent flagship models | Full capability — follows all multi-step flows correctly |
| ⚠️ **Usable** | Claude Haiku 3.5, GPT-4o-mini, Gemini 2.0 Flash, Llama 3.1/3.3 70B+, DeepSeek-V2.5, Qwen-72B, GLM-4, Yi-Large, or similar mid-tier models | May simplify pre-generation or skip monitoring details |
| ❌ **Not recommended** | Llama 8B, Phi-3/4, Qwen-7B, ChatGLM-6B, Mistral 7B, or any model under ~30B parameters | Will miss critical safety steps — not safe for printer control |

> **Why it matters:** The skill has a strict pipeline: search → generate → analyze → repair → preview → confirm → print → monitor. Small models tend to skip the analyze/preview steps, which can waste filament, damage prints, or in worst case harm the printer. When in doubt, use a recommended-tier model.

---

## Installation

**Via ClawHub (recommended):**
```bash
clawhub install bambu-studio-ai
```

**Manual:**
```bash
git clone https://github.com/heyixuan2/bambu-studio-ai.git ~/.agents/skills/bambu-studio-ai
pip3 install bambulabs-api bambu-lab-cloud-api requests trimesh
```

**Optional but recommended:**
```bash
brew install --cask bambu-studio  # Required for model preview before printing
```

---

## Setup

No CLI wizard — your OpenClaw agent handles setup through conversation:

1. Tell your agent anything about printing (e.g., "check my printer")
2. Agent detects no config → walks you through setup:
   - **Printer model** (all 9 Bambu Lab models)
   - **Connection mode** (LAN recommended, Cloud for remote)
   - **AI 3D generation provider** (optional)
   - **Notification channel**
   - **Print monitoring intensity** (Light/Standard/Intensive/Off)
3. Agent runs verification tests (with your permission)
4. Done!

### LAN Setup (Recommended)

Your OpenClaw host and printer must be on the **same WiFi/network**.

On your printer's touchscreen:
1. **Settings → Network → LAN Mode → ON**
2. Note down: **IP Address**, **Serial Number**, **Access Code** (Settings → Device)

### Cloud Setup (Remote Only)

Only use if you can't be on the same network. Limited features (no camera, no G-code, no AI monitoring).

First login requires email verification code. Token is cached for 24 hours.

---

## The Full Pipeline

Here's what happens when you say "make me an iPhone 15 Pro Max case and print it":

```
You: "帮我打印一个iPhone 16 Pro Max的手机壳"

Agent: "你想：                                             ← Ask preference
  1. 🔎 搜索现有模型
  2. 🎨 AI生成定制
  3. 🤷 不确定"

User: "不确定"

Agent: "让我先搜搜..."                                     ← Search online
 → Searches Printables, MakerWorld, Thangs
Agent: "找到3个：                                          ← Present results
  1. ⭐ iPhone 16 PM Case (4.8★, 12K downloads)
  2. Slim Case with MagSafe
  3. Rugged Case with kickstand"

User: "没有喜欢的，帮我生成"

Agent: "几个问题：                                          ← Clarify requirements
  1. 什么材质？建议TPU(柔软)
  2. 需要什么功能？(纯保护/支架/卡槽)
  3. 风格偏好？"

Agent: "我查一下精确尺寸..."                                ← Research (with permission)
 → Searches iPhone 16 Pro Max specs
Agent: "159.9×76.7×8.25mm, 摄像头40×36mm                  ← Confirm specs
  加1mm公差, TPU材质. OK?"

User: "OK"
                    ↓
generate.py → Meshy API → phone_case.glb                   ← Generate
                    ↓
Auto-convert GLB → 3MF                                     ← Format conversion
"🔄 Converted GLB → 3MF"
                    ↓
analyze.py → 11-point printability check                    ← Analyze
"Score 9/10. Single piece ✅ Watertight ✅
 Walls: 1.5mm ✅ Overhangs: 3.2% ✅"
                    ↓
Auto-repair if needed                                       ← Repair
"🔧 Fixed 58K non-manifold edges"
                    ↓
open -a "BambuStudio" phone_case.3mf                       ← Preview (MANDATORY)
Agent: "已在Bambu Studio打开，请检查：                        ← User must verify
  - 模型看起来对吗？
  - 有没有悬空/断开的部分？
  - 尺寸对吗？
  - 切片看看时间和耗材
  确认后告诉我！"

User: "可以，打印吧"
                    ↓
bambu.py print phone_case.3mf                               ← Print
                    ↓
monitor.py (every 5 min)                                    ← AI Monitor
                    ↓
Agent: "打印完成！这是最终照片。"                              ← Notify
```

---

## Model Sourcing (Search vs Generate)

The agent always asks first: search existing models or AI generate?

### Online Model Libraries

| Source | URL | Best For |
|--------|-----|----------|
| **Printables** | printables.com | Bambu Lab community, pre-sliced profiles |
| **MakerWorld** | makerworld.com | Bambu Lab official, ready-to-print |
| **Thingiverse** | thingiverse.com | Largest library |
| **Thangs** | thangs.com | Search engine, aggregates multiple sites |
| **MyMiniFactory** | myminifactory.com | Curated, high quality |
| **Cults3D** | cults3d.com | Designer models |

### When to Search vs Generate

| Scenario | Recommendation |
|----------|---------------|
| Common object (phone stand, hook, organizer) | **Search** — 99% chance it exists, community-tested |
| Specific product accessory (iPhone case) | **Search first** — likely exists with exact dimensions |
| Custom/unique object | **Generate** |
| Mechanical/functional part | **Search** — tested designs > AI guesses |
| Artistic/decorative | **Search first**, generate if nothing fits |

---

## AI 3D Generation

### ⚠️ Important: About AI-Generated Model Quality

**The quality of generated 3D models depends primarily on two factors:**
1. **Your 3D generation API provider** — Meshy, Tripo3D, etc. each have different strengths
2. **The prompt** — more detailed = better results

**AI-generated models are NOT production-ready.** They are a starting point. Common issues:
- Non-manifold geometry (auto-repaired by analyze.py)
- Floating/disconnected parts
- Thin walls that break during printing
- Imprecise dimensions
- Missing fine details

**Always verify in Bambu Studio before printing.** The agent will remind you.

### Supported Providers

| Provider | Text→3D | Image→3D | Output | Price | Quality |
|----------|---------|----------|--------|-------|---------|
| **Meshy** | ✅ | ✅ | GLB (auto→3MF) | Free + $20/mo | ⭐⭐⭐⭐ Most mature |
| **Tripo3D** | ✅ | ✅ | GLB (auto→3MF) | Free + $10/mo | ⭐⭐⭐ Good value |
| **Printpal** | ✅ | ✅ | STL | Varies | ⭐⭐⭐ Print-optimized |
| **3D AI Studio** | ✅ | ✅ | STL/OBJ | Early access | ⭐⭐ New |

### Output Format Priority

Most AI providers return GLB, which Bambu Studio cannot open. The skill auto-converts:

| Step | Format | Why |
|------|--------|-----|
| Provider returns | GLB | That's what they output |
| Auto-convert to | **3MF** | Bambu Lab native format |
| Fallback | **STL** | If 3MF conversion fails |
| Also supported | **STEP/STP**, **OBJ** | For CAD editing or fallback |

### Smart Prompt Enhancement

Your prompt is automatically enhanced for 3D printing:

```
You say: "a phone stand"

Enhanced to: "a phone stand. Optimized for FDM 3D printing.
Maximum dimensions: 315x288x292mm. CRITICAL REQUIREMENTS:
Single connected piece (no floating parts), flat stable base,
all parts physically connected to base, watertight manifold mesh,
no overhangs beyond 45°, minimum 1.5mm wall thickness,
no thin features under 2mm. Printable without supports if possible."
```

Use `--raw` flag to skip enhancement if you've crafted your own prompt.

### Auto Size Limiting

Models are constrained to your printer's build volume (with 10% safety margin):

| Printer | Max Printable Dimensions |
|---------|------------------------|
| A1 Mini | 162×162×162mm |
| A1/P1S/P2S/X1C/X1E/H2C | 230×230×230mm |
| H2S | 306×288×306mm |
| H2D | 315×288×292mm |

---

## Model Analysis & Repair

Every model goes through an **11-point printability check** before printing:

| # | Check | What It Detects |
|---|-------|----------------|
| 1 | Dimensional tolerance | Missing +0.2mm clearance for mating parts |
| 2 | Wall thickness | Walls thinner than material minimum (1.2mm PLA, 1.6mm TPU, 2.0mm PEEK) |
| 3 | Load direction | Stress axis aligned with weak layer lines |
| 4 | Overhang detection | Faces >45° that need support material |
| 5 | Print orientation | No flat base = bad bed adhesion |
| 5b | **Floating parts** | Disconnected pieces that will fall during printing |
| 6 | Layer height | 0.12mm (detail), 0.20mm (default), 0.28mm (fast) |
| 7 | Infill rate | 15% decorative, 30% functional |
| 8 | Wall count | ≥3 standard, ≥4 functional parts |
| 9 | Top layers | ≥5 for clean top surface |
| 10 | Material compatibility | Checks if printer supports the material |
| + | Mesh quality | Watertight, manifold, build volume fit |

### Auto Repair

If mesh issues are found (non-manifold edges, holes, bad normals), the script automatically:
1. Fixes normals and winding
2. Fills holes
3. Removes degenerate/duplicate faces
4. Saves repaired version

For stubborn meshes that can't be auto-repaired:
- Bambu Studio: Right-click model → Fix Model
- Online: [Formware STL Repair](https://www.formware.co/onlinestlrepair)

### Score

Each model gets a **printability score out of 10**:
- 🟢 **8-10**: Ready to print
- 🟡 **5-7**: Review warnings, may need adjustments
- 🔴 **1-4**: Significant issues, fix before printing

---

## Print Monitoring

AI-powered anomaly detection with configurable intensity:

| Level | Interval | Token Cost | Best For |
|-------|----------|------------|----------|
| 🟢 **Light** | Every 30 min | ~2 tokens/hr | Long prints, budget-conscious |
| 🟡 **Standard** | Every 5 min | ~12 tokens/hr | Recommended default |
| 🔴 **Intensive** | Every 2 min | ~30 tokens/hr | Critical prints, new materials, first prints |
| ⚫ **Off** | — | 0 | When you're watching it yourself |

### What It Detects

| Issue | Severity | Automatic Action |
|-------|----------|-----------------|
| Stringing | ⚠️ Low | Log, continue, clean after |
| Warping | ⚠️ Medium | Shorten check interval, watch closely |
| Layer Shift | ❌ High | Notify + recommend pause |
| Bed Detachment | ❌ Critical | Auto-pause + immediate alert |
| Spaghetti (total failure) | ❌ Critical | Auto-pause + immediate alert |
| Nozzle Clog | ❌ Critical | Auto-pause + alert |

### How It Works

```
monitor.py takes camera snapshot
        ↓
Agent analyzes image with vision AI
        ↓
Normal → log, continue
Suspicious → shorten interval
Critical → auto-pause + notify user
```

Requires **LAN mode** (camera access) and **user consent** (agent always asks before enabling).

---

## Connection Modes

### 🔌 LAN (Recommended)

**Requirements:** OpenClaw host and printer on the same WiFi/network.

**Setup on printer:**
1. Touchscreen → Settings → Network → **LAN Mode → ON**
2. Note: IP Address, Serial Number, Access Code (Settings → Device)

| Feature | Available |
|---------|-----------|
| Status / Control | ✅ |
| Camera Snapshot | ✅ |
| Full AMS Details | ✅ |
| G-code Commands | ✅ |
| AI Print Monitoring | ✅ |
| Speed | Fast (direct connection) |
| Auth | One-time access code |

### ☁️ Cloud (Remote Only)

Use only when you can't be on the same network as the printer.

| Feature | Available |
|---------|-----------|
| Status / Control | ✅ |
| Camera Snapshot | ❌ |
| Full AMS Details | ❌ (basic only) |
| G-code Commands | ❌ |
| AI Print Monitoring | ❌ |
| Speed | Slower (via Bambu servers) |
| Auth | Email + verification code (every 24h) |

---

## Configuration

### config.json (non-sensitive, shareable)

```json
{
  "model": "H2D",
  "mode": "local",
  "email": "user@example.com",
  "device_id": "",
  "printer_ip": "192.168.1.100",
  "serial": "01P00A000000000",
  "3d_provider": "meshy",
  "notify_channel": "auto",
  "monitor_level": "standard",
  "monitor_interval": 300,
  "auto_pause": false,
  "preferred_format": "3mf"
}
```

### .secrets.json (chmod 600, git-ignored)

```json
{
  "password": "bambu_account_password",
  "access_code": "printer_lan_access_code",
  "3d_api_key": "generation_provider_api_key"
}
```

**Exact key names matter.** Use these keys exactly as shown above.

---

## Commands Reference

### Printer Control

```bash
python3 scripts/bambu.py status                    # Printer status
python3 scripts/bambu.py progress                  # Print progress
python3 scripts/bambu.py print model.3mf           # Start printing
python3 scripts/bambu.py pause                     # Pause print
python3 scripts/bambu.py resume                    # Resume print
python3 scripts/bambu.py cancel                    # Cancel print
python3 scripts/bambu.py speed silent              # Quiet mode (night)
python3 scripts/bambu.py speed standard            # Normal
python3 scripts/bambu.py speed sport               # Fast
python3 scripts/bambu.py speed ludicrous           # Maximum
python3 scripts/bambu.py light on|off              # Chamber light
python3 scripts/bambu.py ams                       # AMS filament status
python3 scripts/bambu.py snapshot                  # Camera photo
python3 scripts/bambu.py gcode "G28"               # Send G-code
```

### 3D Generation

```bash
python3 scripts/generate.py text "phone stand" --wait --format 3mf
python3 scripts/generate.py image photo.jpg --wait
python3 scripts/generate.py status <task_id>
python3 scripts/generate.py download <task_id> --format 3mf
python3 scripts/generate.py text "custom design" --raw   # Skip prompt enhancement
```

### Model Analysis

```bash
python3 scripts/analyze.py model.3mf                                    # Quick check
python3 scripts/analyze.py model.stl --material PETG --purpose functional  # Full analysis
python3 scripts/analyze.py model.3mf --repair                           # Analyze + repair
python3 scripts/analyze.py model.3mf --repair --material TPU --json     # JSON output
python3 scripts/analyze.py model.3mf --render                           # With preview images
```

### Print Monitoring

```bash
python3 scripts/monitor.py --once                  # Single check
python3 scripts/monitor.py --interval 300          # Every 5 min (standard)
python3 scripts/monitor.py --interval 1800         # Every 30 min (light)
python3 scripts/monitor.py --interval 120          # Every 2 min (intensive)
python3 scripts/monitor.py --interval 300 --auto-pause  # Auto-pause on failure
```

---

## Material Guide

### Standard Materials (All printers)

| Material | Nozzle | Bed | Speed | Notes |
|----------|--------|-----|-------|-------|
| PLA | 200–210°C | 60°C | Ludicrous | Most common, easy to print |
| PLA+ | 210–220°C | 60°C | Ludicrous | Tougher than PLA |
| PETG | 230–250°C | 80°C | Sport | Strong, water-resistant |
| TPU | 220–240°C | 50°C | Silent | Flexible, phone cases |
| PVA | 190–210°C | 50°C | Standard | Soluble support material |

### Engineering Materials (Enclosed printers: P1S, P2S, X1C, X1E, H2C, H2S, H2D)

| Material | Nozzle | Bed | Notes |
|----------|--------|-----|-------|
| ABS | 240–260°C | 100–110°C | Needs enclosure, strong |
| ASA | 240–260°C | 100–110°C | UV-resistant outdoor use |
| Nylon/PA | 260–280°C | 80–90°C | Dry filament first! |
| PC | 270–300°C | 100–120°C | Very strong, heat-resistant |
| CF-Nylon | 260–280°C | 80°C | Carbon fiber, needs hardened nozzle |

### High-Temp Materials (H2C, H2D only — 350°C nozzle)

| Material | Nozzle | Bed | Notes |
|----------|--------|-----|-------|
| PEEK | 340–350°C | 120°C | Aerospace/medical grade |
| PEI | 340–350°C | 120°C | Extreme temperature resistance |
| PPSU | 340–350°C | 120°C | Chemical resistant, medical |

---

## Troubleshooting

### Connection Issues

| Problem | Fix |
|---------|-----|
| Cloud login failed | Check email/password |
| Verification code spam | Don't retry — wait for code, enter once |
| SSL handshake error (LAN) | Normal (self-signed certs), auto-handled |
| Can't connect (LAN) | 1) LAN Mode ON 2) IP correct 3) Same network |
| Auth failed (LAN) | Wrong serial or access code |
| Timeout | Tap printer touchscreen to wake |
| Token expired | Auto re-authenticates after 24h |
| API method not found | `pip3 install --upgrade bambulabs-api` |

### Print Issues

| Problem | Fix |
|---------|-----|
| First layer not sticking | Raise bed temp +5°C, calibrate Z offset |
| Stringing | Lower nozzle temp 5–10°C |
| Warping | Raise bed temp, disable chamber fan |
| Nozzle clog | Raise temp, clean nozzle, check filament moisture |
| AMS feed failure | Check spool tangle, re-feed |

### Generation Issues

| Problem | Fix |
|---------|-----|
| GLB format returned | Auto-converted to 3MF. If fails: `pip3 install trimesh` |
| Model has floating parts | Re-generate with more specific prompt, or fix in Bambu Studio |
| Non-manifold mesh | `analyze.py --repair` auto-fixes most cases |
| Model too small/large | Specify dimensions in prompt |
| Low quality output | Try different provider, add more detail to prompt |

---

## Project Structure

```
bambu-studio-ai/
├── SKILL.md                    — Agent instructions (770+ lines)
├── README.md                   — This file
├── LICENSE                     — MIT License
├── .gitignore
├── config/
│   ├── config.example.json     — Config template
│   └── .secrets.example.json   — Secrets template (exact key names)
├── references/
│   ├── bambu-mqtt-protocol.md  — MQTT protocol documentation
│   ├── bambu-cloud-api.md      — Cloud API reference
│   ├── 3d-generation-apis.md   — 3D provider API endpoints
│   ├── 3d-prompt-guide.md      — Prompt engineering for 3D models
│   └── model-specs.md          — All 9 printer specifications
└── scripts/
    ├── bambu.py                — Printer control (Cloud + LAN, token caching)
    ├── generate.py             — AI 3D generation (4 providers, auto-convert, prompt enhancement)
    ├── analyze.py              — 11-point printability analysis + mesh repair
    └── monitor.py              — AI print monitoring (anomaly detection)
```

---

## Contributing

PRs welcome! Areas that need help:
- Additional 3D generation providers
- Better mesh repair algorithms
- Print failure pattern recognition
- Localization (Chinese, German, etc.)
- New printer model support as Bambu Lab releases them

---

## Version History

| Version | Changes |
|---------|---------|
| **0.10.2** 🏷️ | **First production-ready release** — full bambulabs-api v2.6.6 compatibility, 20+ iterations of real-world testing on H2D |

---

## License

MIT — see [LICENSE](LICENSE)
