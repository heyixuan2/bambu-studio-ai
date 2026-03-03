---
name: bambu-studio-ai
description: "From chat to finished print — the first full-pipeline AI 3D printing skill. Single-color (STL) and multi-color AMS (OBJ+MTL) with AI-optimized color pipeline: shadow removal, CIELAB nearest-neighbor color mapping, texture smoothing. Auto-orient, auto-scale, 11-point printability analysis, mesh repair. All 9 Bambu Lab printers. 4 AI 3D generation providers."
version: "0.20.1"
author: TieGaier
metadata:
  openclaw:
    emoji: "🖨️"
    requires:
      bins: ["python3", "pip3"]
    install:
      - id: pip-deps
        kind: pip
        packages: ["bambulabs-api", "bambu-lab-cloud-api", "requests", "trimesh"]
        required: true
        description: "Core Python dependencies for printer control, 3D generation, and model analysis"
      - id: ffmpeg
        kind: brew
        package: ffmpeg
        optional: true
        description: "Required for camera snapshots (local mode only)"
      - id: bambu-studio
        kind: cask
        package: bambu-studio
        optional: true
        label: "Bambu Studio (recommended for model preview and slicing — required before printing generated models)"
      - id: blender
        kind: cask
        package: blender
        optional: true
        label: "Blender 4.0+ (required for multi-color printing only)"
env:
  - name: BAMBU_MODE
    required: false
    description: "cloud (default) or local"
  - name: BAMBU_MODEL
    required: false
    description: "Printer model (e.g., H2D, A1 Mini, X1C)"
  - name: BAMBU_EMAIL
    required: false
    description: "Bambu account email (required for cloud mode)"
  - name: BAMBU_DEVICE_ID
    required: false
    description: "Device ID (cloud mode, optional — auto-detected if only one printer)"
  - name: BAMBU_IP
    required: false
    description: "Printer local IP (required for local mode)"
  - name: BAMBU_SERIAL
    required: false
    description: "Serial number (required for local mode)"
  - name: BAMBU_3D_PROVIDER
    required: false
    description: "3D gen provider: meshy, tripo, printpal, 3daistudio"
secrets:
  - name: BAMBU_PASSWORD
    required_when: "mode=cloud"
    storage: ".secrets.json"
    description: "Bambu account password (user-provided, never shipped with skill)"
  - name: BAMBU_ACCESS_CODE
    required_when: "mode=local"
    storage: ".secrets.json"
    description: "LAN access code from printer touchscreen (user-provided)"
  - name: BAMBU_3D_API_KEY
    required_when: "3D generation enabled"
    storage: ".secrets.json"
    description: "API key from chosen 3D generation provider (user-provided)"
security:
  no_credentials_shipped: true
  secrets_storage: ".secrets.json (chmod 600, git-ignored, user creates manually)"
  no_plaintext_in: ["config.json", "SKILL.md", "*.py"]
  config_gitignored: true
  files_gitignored: [".secrets.json", "config.json", ".token_cache.json", ".verify_code"]
  data_access:
    local_reads:
      - "config.json and .secrets.json in skill directory"
    network_calls:
      - "Bambu Lab Cloud API (cloud.bambulab.com) — printer control"
      - "Bambu Lab printer via MQTT (local IP) — local control"
      - "3D generation APIs (Meshy/Tripo/Printpal/3DAI) — model generation only"
    uploads:
      - "Text prompts to 3D generation API (user-initiated only)"
      - "Images to 3D generation API for image-to-3D (user-initiated only)"
    subprocesses:
      - "ffmpeg — camera snapshot extraction (optional, local only)"
    consent: "All network calls, uploads, and monitoring require explicit user consent before first use. Setup flow asks permission at each step."
keywords:
  - 3d printing
  - bambu lab
  - ams
  - mqtt
  - text to 3d
  - image to 3d
  - print monitoring
  - maker
---

# 🖨️ Bambu Studio AI

The first full-pipeline AI 3D printing skill — from a chat message to a finished print.

Connect your Bambu Lab printer + pick a 3D generation API, and your agent handles everything:
search → generate → analyze → repair → preview → print → monitor.

Supports all 9 Bambu Lab printers. Cloud + LAN dual mode.

## Installation

```bash
clawhub install bambu-studio-ai
```

Or clone from GitHub:
```bash
git clone https://github.com/heyixuan2/bambu-studio-ai.git ~/.agents/skills/bambu-studio-ai
pip3 install bambulabs-api bambu-lab-cloud-api requests trimesh
```

📦 **GitHub:** https://github.com/heyixuan2/bambu-studio-ai

---

## Quick Reference

| I want to... | Command |
|--------------|---------|
| Check printer status | `python3 scripts/bambu.py status` |
| See print progress | `python3 scripts/bambu.py progress` |
| Start a print | `python3 scripts/bambu.py print <file>` |
| Pause / Resume / Cancel | `python3 scripts/bambu.py pause\|resume\|cancel` |
| Set speed mode | `python3 scripts/bambu.py speed silent\|standard\|sport\|ludicrous` |
| Toggle light | `python3 scripts/bambu.py light on\|off` |
| Check AMS filament | `python3 scripts/bambu.py ams` |
| Camera snapshot | `python3 scripts/bambu.py snapshot` |
| Send G-code | `python3 scripts/bambu.py gcode "G28"` |
| Generate 3D from text | `python3 scripts/generate.py text "description" --wait` |
| Generate 3D from image | `python3 scripts/generate.py image photo.jpg --wait` |
| Check generation status | `python3 scripts/generate.py status <task_id>` |
| Download model | `python3 scripts/generate.py download <task_id> --format 3mf` |
| Analyze model before printing | `python3 scripts/analyze.py model.3mf --material PLA --purpose functional` |
| Analyze + auto-repair mesh | `python3 scripts/analyze.py model.3mf --repair --material PLA` |
| Auto-orient for printing | `python3 scripts/analyze.py model.stl --orient` |
| Orient + repair combo | `python3 scripts/analyze.py model.stl --orient --repair --material PLA` |
| Convert to multi-color OBJ | `python3 scripts/colorize.py model.glb --colors "#FF0,#000,#F00,#FFF" --height 80` |
| Slice model for printing | `python3 scripts/slice.py model.stl --orient --arrange` |
| Slice with quality preset | `python3 scripts/slice.py model.stl --quality fine` |
| Slice with specific printer | `python3 scripts/slice.py model.stl --printer H2D --nozzle 0.4` |
| List available profiles | `python3 scripts/slice.py --list-profiles` |
| Get printer hardware info | `python3 scripts/bambu.py info` |
| Send notification | `python3 scripts/bambu.py notify --message "done"` |
| Single print check | `python3 scripts/monitor.py --once` |
| Continuous monitoring | `python3 scripts/monitor.py --interval 120` |
| Monitor with auto-pause | `python3 scripts/monitor.py --interval 120 --auto-pause` |

---

## Detection Triggers

Activate this skill when you see:

| Trigger | Action |
|---------|--------|
| "check my printer" / "printer status" | Run `bambu.py status` |
| "what's printing?" / "how far along?" | Run `bambu.py progress` |
| "print this" / "start printing" | Pre-gen flow → `bambu.py print` |
| "print a ..." / "make me a ..." | Ask: search online or AI generate? |
| "turn image into 3D" / sends photo | `generate.py image` |
| "slice this" / "prepare for printing" | `slice.py` with auto-detect |
| "what nozzle is installed?" | `bambu.py info` |
| "pause" / "stop" / "resume" printing | `bambu.py pause\|cancel\|resume` |
| "speed up" / "quiet mode" / "ludicrous" | `bambu.py speed` |
| "how much filament?" / "AMS" | `bambu.py ams` |
| "show me the printer" / "camera" | `bambu.py snapshot` |
| "watch my print" / "monitor" | Ask permission → `monitor.py` |
| "light on/off" | `bambu.py light on\|off` |
| "find a model" / "download" / known object | Search online model libraries first |
| "analyze" / "check this model" / before any print | `analyze.py` → 10-point check |
| First use + no config.json | → Start Setup Flow |

---

## First-Time Setup

**If `config.json` does not exist in the skill directory, walk the user through setup via conversation before running any commands.**

### Phase 1: Configure

Ask these in order. Be conversational, not robotic.

**1. Printer Model**
> "Which Bambu Lab printer do you have?"

Show options grouped by series:
- 🟢 **A Series** (Entry): A1 Mini (180³mm, 500mm/s), A1 (256³mm, 500mm/s)
- 🔵 **P Series** (Prosumer): P1S (256³mm, 500mm/s, enclosed), P2S (256³mm, 600mm/s)
- 🟠 **X Series** (Pro): X1C (256³mm, AI features), X1E (Industrial, HEPA)
- 🔴 **H Series** (High-end): H2C (350°C, heated chamber), H2S (340³mm, 1000mm/s), H2D (dual extruder, laser, cutting)

**2. Connection Mode**
> "How is your printer connected?"
> 
> **🔌 LAN (Recommended)** — If your computer and printer are on the same WiFi/network.
> Full features: camera, G-code, AMS, AI monitoring, fast response.
> You'll need: IP address, serial number, and access code from printer Settings → Device.
> Also make sure LAN Mode is turned ON on the printer (Settings → Network → LAN Mode → ON).
>
> **☁️ Cloud** — If you're accessing remotely (not on the same network).
> Limited features: no camera, no G-code, no AI monitoring. Requires email verification.

Default to LAN unless user specifically needs remote access.

- **LAN** → printer IP + serial + access code (Settings → Device → LAN Access Code)
- **Cloud** → email + password (will require verification code on first login)
- **Both** → collect all, default to LAN

**3. AI 3D Generation** (optional)
> "Want AI 3D model generation? Create printable models from text or photos."

If yes → pick provider + API key:
- **Meshy** — Most mature, STL/3MF, $20/mo
- **Tripo3D** — Python SDK, $10/mo  
- **Printpal** — Print-optimized output
- **3D AI Studio** — Early access

**4. Notifications**
> "How should I notify you? Auto (match your channel), Discord, iMessage, Telegram, WhatsApp, or Slack?"

**5. AI Print Monitoring** (optional)
> "Want AI monitoring? I'll photograph prints and check for failures."

If yes → interval (default 120s), auto-pause on anomaly (default no)

**6. Save Configuration**

Write `config.json` (non-sensitive, shareable):
```json
{
  "model": "H2D",
  "mode": "cloud",
  "email": "user@example.com",
  "device_id": "",
  "printer_ip": "",
  "serial": "",
  "3d_provider": "meshy",
  "notify_channel": "auto",
  "monitor_enabled": false,
  "monitor_interval": 120,
  "auto_pause": false
}
```

Write `.secrets.json` (sensitive, **use these exact keys**):
```json
{
  "password": "bambu_account_password",
  "access_code": "printer_lan_access_code",
  "3d_api_key": "generation_api_key"
}
```

Then run:
```bash
chmod 600 .secrets.json
```

Ensure `.gitignore` includes `.secrets.json` and `config.json`.

### Phase 2: Verify (ask permission)

> "Config saved! I'd like to run quick tests — no prints will start, no significant API costs. OK?"

**Only proceed if user agrees.**

| Test | Command | When |
|------|---------|------|
| Printer connection | `python3 scripts/bambu.py status` | Always |
| Camera snapshot | `python3 scripts/bambu.py snapshot` | Local mode only |
| AMS status | `python3 scripts/bambu.py ams` | Local mode only |
| 3D API test | `python3 scripts/generate.py text "10mm cube" --raw` | If 3D gen configured (ask first) |
| Bambu Studio | `brew list --cask bambu-studio` | macOS only |

If Bambu Studio not installed, offer: `brew install --cask bambu-studio`

### Phase 3: Summary

```
🎉 Setup Complete!

🖨️ Printer:     H2D (350×320×325mm, 600mm/s)
☁️ Connection:  Cloud ✅
🎨 3D Gen:      Meshy ✅
🔍 Monitor:     ON (every 120s)
📸 Camera:      ✅
📦 AMS:         4 slots loaded
📥 Studio:      ✅ Installed

Try: "What's my printer status?" or "Generate a phone stand"
```



---

## Model Sourcing (Search Before Generating)

**When a user wants to print something, always ask first:**

> "Do you want me to:
> 1. 🔎 **Search online** — find existing models (usually higher quality, tested by community)
> 2. 🎨 **AI Generate** — create a custom model from scratch
> 3. 🤷 **Not sure** — I'll search first, generate if nothing fits"

Then follow the appropriate flow. Don't assume — the user may already have a specific design in mind,
or may want something completely custom that doesn't exist.

### Search Priority

| Source | URL | Best For |
|--------|-----|----------|
| **Printables** | printables.com | Bambu Lab community, pre-sliced profiles |
| **Thingiverse** | thingiverse.com | Largest library, everything |
| **MakerWorld** | makerworld.com | Bambu Lab official, ready-to-print |
| **Thangs** | thangs.com | 3D search engine, searches multiple sites |
| **MyMiniFactory** | myminifactory.com | Curated, high quality |
| **Cults3D** | cults3d.com | Designer models, some paid |

### When to Search vs Generate

| Scenario | Action |
|----------|--------|
| Common object (phone stand, hook, box) | **Search first** — 99% chance it exists |
| Specific product accessory (iPhone 15 case) | **Search first** — likely exists with exact dimensions |
| Custom/unique object | **Generate** with AI |
| Artistic/decorative | **Search first**, generate if nothing fits |
| Mechanical/functional part | **Search first** — tested designs > AI guesses |

### Search Flow

1. Ask user: "Want me to search for existing models first? Often better quality than AI-generated."
2. If yes → search Thangs/Printables/MakerWorld via web_search
3. Present top 3-5 results with:
   - Name, thumbnail URL, download count/rating
   - File format (prefer .3mf > .stl)
   - Whether it has Bambu Lab print profiles
4. If user picks one → download → `analyze.py` → preview → print
5. If nothing good → fall back to AI generation

### Example

> User: "Print me a headphone stand"
> Agent: "Let me search — headphone stands are very common online."
> → Searches Printables + MakerWorld
> Agent: "Found 3 good options:
> 1. ⭐ 'Minimal Headphone Stand' — 4.8★, 12K downloads, has Bambu profile
> 2. 'Under-desk Hook Stand' — 4.6★, wall-mounted
> 3. 'RGB Headphone Holder' — with cable channel
>
> Want one of these, or should I generate a custom design?"

---

## Pre-Generation Flow

**Before generating any 3D model, follow these steps. Do NOT skip.**

### Step 1: Clarify Requirements

Ask about anything unclear:

| Ask about | Why |
|-----------|-----|
| Dimensions | "How big?" — must fit build volume |
| Purpose | Functional vs decorative → affects wall thickness |
| Material | PLA/TPU/ABS → affects design constraints |
| Phone/device model | If it's a case/holder → need exact dimensions |
| Features | Cable holes, mounting points, adjustable angles |

Example:
> User: "Print me a phone stand"  
> Agent: "Sure! Quick questions:  
> 1. Which phone? (affects holder width)  
> 2. Viewing angle? (15°, 45°, upright?)  
> 3. Any features? (cable hole, non-slip base?)  
> 4. Material preference?"

### Step 2: Research Unknown Objects (ask permission)

If you don't know exact dimensions or appearance:

> User: "Print an iPhone 15 Pro Max case"  
> Agent: "I'll need the exact dimensions for a proper fit. Mind if I look them up?"

After research, confirm:
> "iPhone 15 Pro Max: 159.9 × 76.7 × 8.25mm, camera bump 40 × 36mm.  
> I'll add 1mm tolerance per side. Sound right?"

**What to research:**
- Physical dimensions of real objects
- Tolerance/clearance for cases (typically 0.5–1mm)
- Standard sizes (screws, USB ports, cables)
- Reference images for complex shapes

### Step 3: Confirm Before Generating

> "Here's what I'll generate:  
> - iPhone 15 Pro Max case  
> - 162 × 79 × 12mm (1mm tolerance)  
> - Camera cutout: 42 × 38mm  
> - Material: TPU (flexible)  
> - Est. print time: ~2h  
>  
> Ready to generate?"

### Step 4: Generate

**Before generating, tell the user:**
> "A quick heads-up: AI-generated 3D model quality depends mainly on two things:
> 1. Your 3D generation provider (Meshy, Tripo, etc.) — each has different strengths
> 2. How detailed your prompt is — the more specific, the better
> 
> AI-generated models are not production-ready out of the box. Always review in Bambu Studio.
> If the result isn't great, try a different provider or refine your prompt."

Call `generate.py` with a detailed, dimensions-aware prompt. The script auto-enhances prompts with printability instructions and scales to your printer's build volume.

Use `--raw` to skip auto-enhancement if you've crafted a precise prompt.

---

## Supported Printers

### A Series (Entry Level)

| | A1 Mini | A1 |
|---|---|---|
| Volume | 180×180×180mm | 256×256×256mm |
| Speed | 500mm/s | 500mm/s |
| Nozzle Max | 300°C | 300°C |
| Bed Max | 80°C | 100°C |
| Enclosure | Open | Open |
| AMS | AMS Lite | AMS Lite |

### P Series (Prosumer)

| | P1S | P2S |
|---|---|---|
| Volume | 256×256×256mm | 256×256×256mm |
| Speed | 500mm/s | 600mm/s |
| Nozzle Max | 300°C | 300°C |
| Bed Max | 100°C | 110°C |
| Enclosure | Enclosed | Enclosed |
| AMS | AMS | AMS 2 Pro |

### X Series (Professional)

| | X1C | X1E |
|---|---|---|
| Volume | 256×256×256mm | 256×256×256mm |
| Speed | 500mm/s | 500mm/s |
| Nozzle Max | 300°C | 300°C |
| Enclosure | Enclosed | Full enclosed + HEPA |
| Features | Lidar, AI detection | Industrial sealed |

### H Series (High-Performance)

| | H2C | H2S | H2D |
|---|---|---|---|
| Volume | 256×256×256mm | 340×320×340mm | 350×320×325mm |
| Speed | 600mm/s | 1000mm/s | 600mm/s |
| Nozzle Max | **350°C** | 300°C | **350°C** |
| Extruders | 1 | 1 | **2 (Dual)** |
| Enclosure | 65°C heated | Enclosed | Enclosed |
| Extras | High-temp materials | Ultra-large + fast | Laser + cutting modules |

---

## Connection Modes

> **⚠️ Recommendation: Use LAN mode whenever possible.**
> Cloud mode has limited features and requires email verification on every login.
> LAN mode is faster, has full features, and no auth headaches.

### 🔌 Local / LAN (Recommended)

**Requirements:** OpenClaw host and Bambu Lab printer on the **same local network** (WiFi or Ethernet).

**How to enable LAN mode on your printer:**
1. On printer touchscreen → **Settings** → **Network** → **LAN Mode**
2. Toggle **LAN Mode** to **ON** (Live)
3. Note down:
   - **IP Address** — shown on the network screen
   - **Serial Number** — Settings → Device Info
   - **Access Code** — Settings → Device Info → LAN Access Code

```bash
export BAMBU_MODE="local"
export BAMBU_IP="192.168.1.100"        # Your printer's IP
export BAMBU_SERIAL="01P00A000000000"   # From Device Info
export BAMBU_ACCESS_CODE="12345678"     # From Device Info
```

### ☁️ Cloud (remote access only)

Only use Cloud mode if you **cannot** be on the same network as the printer.

**Limitations:**
- ❌ No camera snapshots
- ❌ No G-code commands
- ❌ Limited AMS info
- ❌ Requires email verification code on first login (and after token expires)
- ⚠️ Slower response, depends on Bambu servers

**Login includes verification code flow:**
1. Script sends login request
2. Bambu emails you a verification code
3. Enter the code when prompted (script will **wait patiently** — no auto-retry)
4. Token is cached for 24 hours

```bash
export BAMBU_MODE="cloud"
export BAMBU_EMAIL="you@email.com"
export BAMBU_PASSWORD="password"
```

| Feature | Cloud | LAN |
|---------|-------|-----|
| Status / Control | ✅ | ✅ |
| Camera Snapshot | ❌ | ✅ |
| AMS Full Details | ❌ | ✅ |
| G-code Send | ❌ | ✅ |
| AI Monitoring | ❌ | ✅ |
| Speed | Slow | Fast |
| Auth | Email + verify code | Access code (one-time) |
| Network | Anywhere | Same LAN |

Scripts auto-load `config.json` + `.secrets.json` from the skill directory.
Environment variables override config file values.

---

## Configuration Files

### config.json (non-sensitive, shareable)
See `config/config.example.json` for template.

### .secrets.json (sensitive, chmod 600)
See `config/.secrets.example.json` for template.
**Exact keys:** `password`, `access_code`, `3d_api_key`

### .gitignore
Ships with the skill. Excludes `.secrets.json` and `config.json`.

---

## 3D Generation

Supports 4 providers:

| Provider | Text→3D | Image→3D | Best Format | Price |
|----------|---------|----------|-------------|-------|
| **Meshy** | ✅ | ✅ | STL/3MF | Free + $20/mo |
| **Tripo3D** | ✅ | ✅ | GLB/STL | Free + $10/mo |
| **Printpal** | ✅ | ✅ | STL | Print-optimized |
| **3D AI Studio** | ✅ | ✅ | STL/OBJ | Early access |

### Auto Prompt Enhancement
User says "a phone stand" → script auto-adds:
> "...Optimized for FDM 3D printing. Max 230×230×230mm. Flat base, watertight mesh, no overhangs >45°, min 1.5mm walls."

### Auto Size Limiting
Models auto-constrained to printer build volume (10% margin):

| Printer | Max Printable |
|---------|--------------|
| A1 Mini | 162×162×162mm |
| A1/P1S/P2S/X1C/X1E/H2C | 230×230×230mm |
| H2S | 306×288×306mm |
| H2D | 315×288×292mm |

Skip enhancement: `--raw` flag.

### Output Format Priority

Always generate in Bambu Lab compatible formats, in this order:

| Priority | Format | Why |
|----------|--------|-----|
| 1st | **.3mf** | Bambu Lab native, preserves print settings |
| 2nd | **.stl** | Universal, all slicers support it |
| 3rd | **.step/.stp** | Precise geometry, editable in CAD |
| 4th | **.obj** | Fallback only |

Default `--format 3mf` unless user specifies otherwise.

### Mandatory Pre-Print Pipeline

**NEVER send a model directly to the printer. Always follow this order:**

```
1. Generate/Download → model.3mf
2. Analyze + Repair  → python3 scripts/analyze.py model.3mf --repair --material PLA
3. Report to user    → "Score 8/10, repaired 58K non-manifold edges..."
4. Open in Bambu Studio → open -a "BambuStudio" model.3mf
5. ⚠️ MANDATORY: Tell user to inspect in Bambu Studio
   → "I've opened the model in Bambu Studio. Please check:
      - Does it look correct? Any missing or deformed parts?
      - Any floating/disconnected pieces? (they will fall during printing!)
      - Is the size right? (check dimensions in bottom bar)
      - Any red warnings? (non-manifold, intersecting parts)
      - Are there parts hanging in the air that need supports?
      - Slice it and check: estimated time, filament usage, and support amount.
      Let me know when you're ready to print!"
6. WAIT for explicit user confirmation → "looks good" / "print it" / "go ahead"
7. Print             → python3 scripts/bambu.py print model.3mf
```

**⛔ NEVER skip step 5-6. NEVER auto-print without user seeing the model in Bambu Studio.**
AI-generated models frequently have mesh errors (non-manifold edges, holes, intersections).
The user MUST visually verify before printing.

#### The 11-Point Printability Check

| # | Check | What It Does |
|---|-------|-------------|
| 1 | Dimensional tolerance | Verifies +0.2mm clearance for mating parts |
| 2 | Wall thickness | Must be ≥1.2mm (≥1.6mm for TPU, ≥2.0mm for PEEK) |
| 3 | Load direction | Warns if stress axis aligns with layer lines |
| 4 | Overhang detection | Flags faces >45° that need support |
| 5 | Print orientation | Checks for flat base / bed adhesion |
| 6 | Layer height | Recommends 0.12/0.20/0.28mm based on detail |
| 7 | Infill rate | 15% decorative / 30% functional / custom |
| 8 | Wall count | ≥3 standard, ≥4 functional |
| 9 | Top layers | ≥5 for clean top surface |
| 10 | Material compatibility | Checks printer supports the material |

Also checks: watertight mesh, manifold geometry, build volume fit.

Output includes recommended print settings (layer height, infill, walls, temps, supports).

See `references/3d-prompt-guide.md` for detailed prompt engineering tips.

### Reference Documents

The `references/` folder contains docs the agent can consult:
- `bambu-mqtt-protocol.md` — MQTT topics, commands, report fields
- `bambu-cloud-api.md` — Cloud API Python SDK methods
- `3d-generation-apis.md` — Meshy/Tripo/Printpal/3DAI endpoints
- `3d-prompt-guide.md` — Prompt engineering for printable 3D models
- `model-specs.md` — All 9 printer specs in one table

---

## AI Print Monitoring

### ⚠️ Requires User Consent

**Always ask before enabling:**
> "Want AI print monitoring? I'll photograph your print and use AI to check for failures."

If yes, ask monitoring intensity:
> "How closely should I monitor? This affects token usage:
> - 🟢 **Light** (every 30 min) — ~2 tokens/hr, good for long prints
> - 🟡 **Standard** (every 5 min) — ~12 tokens/hr, recommended
> - 🔴 **Intensive** (every 2 min) — ~30 tokens/hr, for critical prints or new materials
> - ⚫ **Off** — no monitoring
>
> Which level?"

Then: "Should I auto-pause if I detect something serious like spaghetti or bed detachment?"

**Never auto-enable.**

### Anomaly Detection

| Type | Severity | Action |
|------|----------|--------|
| Stringing | ⚠️ Low | Continue, clean after |
| Warping | ⚠️ Medium | Monitor closely |
| Layer Shift | ❌ High | Recommend pause |
| Detachment | ❌ Critical | Pause immediately |
| Spaghetti | ❌ Critical | Pause immediately |
| Clog | ❌ Critical | Pause and inspect |

### Flow
```
monitor.py captures snapshot → outputs image path
    ↓
Agent analyzes image (via image tool)
    ↓
Normal → log, continue
Suspicious → shorten interval, watch
Critical → notify user + optional auto-pause
```

---

## Material Guide

### Standard (All models, open or enclosed)

| Material | Nozzle | Bed | Speed | Notes |
|----------|--------|-----|-------|-------|
| PLA | 200–210°C | 60°C | Ludicrous | Most common |
| PLA+ | 210–220°C | 60°C | Ludicrous | Tougher |
| PETG | 230–250°C | 80°C | Sport | Strong |
| TPU | 220–240°C | 50°C | Silent | Flexible, slow |
| PVA | 190–210°C | 50°C | Standard | Soluble support |

### Engineering (Enclosed models: P1S, P2S, X1C, X1E, H2C, H2S, H2D)

| Material | Nozzle | Bed | Notes |
|----------|--------|-----|-------|
| ABS | 240–260°C | 100–110°C | Needs enclosure |
| ASA | 240–260°C | 100–110°C | UV-resistant |
| Nylon/PA | 260–280°C | 80–90°C | Dry first! |
| PC | 270–300°C | 100–120°C | High strength |
| Carbon Fiber | 260–280°C | 80°C | Hardened nozzle |

### High-Temp (H2C, H2D only — 350°C nozzle)

| Material | Nozzle | Bed | Notes |
|----------|--------|-----|-------|
| PEEK | 340–350°C | 120°C | Industrial, needs heated chamber |
| PEI | 340–350°C | 120°C | Extreme temp |
| PPSU | 340–350°C | 120°C | Medical / Aerospace |

---

## H2D-Specific Features

### Dual Extruder
- Left (T0): Primary | Right (T1): Secondary
- Uses: dual-color, PLA+PVA soluble support, soft+hard combos
- Combine with AMS for more colors

### Laser Modules
- 10W: Engrave wood, leather, acrylic
- 40W: Cut wood, acrylic sheets

### Cutting Module
- Precision cutting of thin materials

---

## Troubleshooting

### Connection

| Problem | Fix |
|---------|-----|
| Cloud login failed | Check email/password, enter verification code when prompted |
| Cloud verification spam | Don't retry — wait patiently for code, enter once |
| SSL handshake error (LAN) | Normal with newer firmware (self-signed certs). Script auto-handles this. |
| API method not found | Run `pip3 install --upgrade bambulabs-api` — v2.6.6+ renamed many methods (e.g. get_progress→get_percentage, get_gcode_state→get_current_state). Skill is tested against v2.6.6. |
| Can't connect (LAN) | 1) LAN Mode ON on printer 2) IP correct 3) Same WiFi/network as OpenClaw |
| Auth failed | Wrong serial or access code (check Settings → Device on printer) |
| Timeout | Wake printer (tap touchscreen), check if printer IP changed |
| Token expired | Auto-handled — re-authenticates after 24h cache expires |

### Print Failures

| Symptom | Fix |
|---------|-----|
| First layer not sticking | Raise bed temp 5°C, calibrate Z offset |
| Stringing | Lower nozzle temp 5–10°C |
| Warping | Raise bed temp, disable chamber fan |
| Clog | Raise temp, clean nozzle, check moisture |
| AMS feed failure | Check spool tangle, re-feed |

---

## Automation Ideas

- **Progress updates** — Cron push to user's channel every 30 min
- **AMS low filament alert** — Warn below 20%
- **Timelapse** — Snapshot every 2 min → ffmpeg video
- **Print complete notification** — Alert + final photo
- **Anomaly detection** — AI analysis → auto-pause + alert

---

## Bambu Studio

Check: `brew list --cask bambu-studio 2>/dev/null`

Not installed? Offer:
> "Bambu Studio gives live camera and slicing. Want me to install it?"
```bash
brew install --cask bambu-studio
```

Other platforms:
- Windows: https://bambulab.com/en/download/studio
- Linux: https://github.com/bambulab/BambuStudio/releases

---

## Speed Modes

```bash
python3 scripts/bambu.py speed silent     # Quiet (night)
python3 scripts/bambu.py speed standard   # Standard
python3 scripts/bambu.py speed sport      # Fast
python3 scripts/bambu.py speed ludicrous  # Max (H2S: 1000mm/s)
```

---

## Known Limitations

| Feature | Status | Note |
|---------|--------|------|
| Single-color printing | ✅ Stable | Full pipeline: generate → analyze → slice → print |
| Multi-color (colorize) | ⚠️ Manual step | OBJ+MTL output works, but user must manually map 43 colors → AMS slots in Bambu Studio |
| CLI slicing | ✅ Stable | OrcaSlicer backend; Bambu Studio CLI has SEGFAULT bug in v2.5.0 |
| End-to-end auto-print | 🔜 Planned | Currently requires Bambu Studio preview before printing |
| OrcaSlicer CLI gcode | ⚠️ Simplified | Start gcode simplified for OrcaSlicer compat; printer firmware handles actual startup sequence |

## Version History

### 0.20.0
- **NEW**: `slice.py` — CLI slicer with OrcaSlicer backend
  - Auto-resolves Bambu Studio profile inheritance chains
  - Auto-detects printer model, nozzle size from live printer
  - Quality presets: draft/standard/fine/extra
  - Auto-orient + auto-arrange flags
  - 3MF post-processing for BS compatibility
  - All 9 Bambu Lab printer models supported
- **NEW**: `bambu.py info` — printer hardware info (model, nozzle, AMS filaments)
- **NEW**: `bambu.py notify` — send notifications
- **NEW**: Smart print monitor with anomaly detection
  - Progress stall detection (>10min)
  - Temperature anomaly alerts
  - 30-min progress summaries, immediate anomaly alerts
  - Auto-pause on critical anomalies
- Fixed: `bambu.py` dispatch for info/notify/status --json
- Fixed: `generate.py` --format 3mf now correctly produces .3mf
- Fixed: `colorize.py` auto-adds .obj extension
- Fixed: `doctor.py` checks OrcaSlicer installation
- Fixed: Relative output paths in slice.py
- Fixed: 3MF compatibility with Bambu Studio 2.5.0

### 0.19.2
- Fixed: `_safe_split()` with 30s SIGALRM timeout for mesh.split() hang protection
- Verified with stress test model T12 (Eiffel Tower lattice)

### 0.19.1
- 17 bug fixes from 3-round audit (B1-B17, R1-R4, D1-D5, O3-O6)
- `search.py` rewritten to use `ddgs` package (DDG HTML scraping broken)
- `analyze.py` stdlib imports moved to top
- Monitor `--status` works offline


- **0.19.0** — 13 bug fixes, doctor.py, --confirmed safety gate, color pipeline overhaul (AO delight, shadow-aware mapping, border vote), search rewrite (ddgs), monitor retry logic
- **0.18.0** — Model search (4 sources), notification system
- **0.17.x** — Bambu Lab official 43-color palette, direct CIELAB NN (K-means removed), default LAN mode
- **0.16.x** — Unit detection fix, start_print fix, MTL color fixes, OBJ meter→mm fix
- **0.15.x** — OBJ mtllib reference fix after rename
- **0.14.x** — Multi-color AMS: mesh-aware delight, CIELAB mapping, texture smoothing, island cleanup
- **0.13.x** — GLB→STL/OBJ+MTL conversion, auto-orient, auto-scale
- **0.12.x** — AI 3D generation (4 providers), prompt enhancement
- **0.11.0** — Multi-color AMS printing (colorize.py), auto-detect AMS colors
- **0.10.0** — 11-point analysis, auto mesh repair, requirements.txt
- **0.9.0** — Cloud login: token caching (24h), verification code patience, LAN recommended
- **0.8.x** — Model sourcing (search before generate), user choice
- **0.7.x** — analyze.py, model requirements table, security scan fixes, README
- **0.6.0** — Monitor intensity levels, 3MF priority, mandatory Bambu Studio preview
- **0.5.x** — Pre-generation research flow, .secrets.example.json
- **0.4.0** — 3-phase setup (configure → test → summary)
- **0.3.x** — Security fixes, config/secrets separation
- **0.2.0** — Full 9-model support, Cloud+Local dual mode, AI monitoring
- **0.1.0** — Initial release

## License

MIT
