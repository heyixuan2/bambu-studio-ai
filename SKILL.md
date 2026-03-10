---
name: bambu-studio-ai
description: "Bambu Lab 3D printer control and automation. Activate when user mentions: printer status, 3D printing, slice, analyze model, generate 3D, AMS filament, print monitor, Bambu Lab, or any 3D printing task. Full pipeline: search → generate → analyze → colorize → preview → open BS → user slice → print → monitor. Supports all 9 Bambu Lab printers (A1 Mini, A1, P1S, P2S, X1C, X1E, H2C, H2S, H2D)."
version: "1.0.1"
license: MIT
author: TieGaier
metadata:
  openclaw:
    emoji: "🖨️"
    os: ["macos"]
    os_note: "Core scripts (analyze, generate, colorize, search) work cross-platform. macOS required for: Bambu Studio integration (open -a), Homebrew cask installs, macOS notifications (osascript). Linux/Windows users can run the Python scripts directly but lose BS integration."
    requires:
      bins: ["python3", "pip3"]
    install:
      - id: pip-deps
        kind: pip
        packages: ["bambulabs-api", "bambu-lab-cloud-api", "requests", "trimesh", "numpy", "Pillow", "ddgs", "pygltflib", "cryptography", "paho-mqtt", "scipy", "manifold3d"]
        required: true
      - id: ffmpeg
        kind: brew
        package: ffmpeg
        optional: true
        label: "Camera snapshots (LAN mode)"
      - id: bambu-studio
        kind: cask
        package: bambu-studio
        optional: true
        label: "Model preview and manual slicing (macOS)"
      - id: blender
        kind: cask
        package: blender
        optional: true
        label: "Multi-color pipeline + HQ preview rendering (macOS)"
      - id: orcaslicer
        kind: cask
        package: orcaslicer
        optional: true
        label: "Optional CLI slicing backend (macOS)"
env:
  - name: BAMBU_MODE
    required: false
    description: "Connection mode: local (default, recommended) or cloud"
  - name: BAMBU_MODEL
    required: false
    description: "Printer model (e.g., H2D, A1 Mini, X1C)"
  - name: BAMBU_EMAIL
    required: false
    description: "Bambu account email (cloud mode only)"
  - name: BAMBU_IP
    required: false
    description: "Printer LAN IP (local mode only)"
  - name: BAMBU_SERIAL
    required: false
    description: "Printer serial number (local mode only)"
  - name: BAMBU_ACCESS_CODE
    required: false
    description: "LAN access code from printer touchscreen (local mode only)"
  - name: BAMBU_VERIFY_CODE
    required: false
    description: "Cloud login verification code (one-time, cloud mode only)"
  - name: BAMBU_DEVICE_ID
    required: false
    description: "Cloud device ID (auto-detected, cloud mode only)"
  - name: BAMBU_3D_PROVIDER
    required: false
    description: "AI 3D gen provider: meshy, tripo, printpal, 3daistudio, rodin (optional)"
  - name: BAMBU_3D_API_KEY
    required: false
    description: "API key for chosen 3D generation provider (optional)"
secrets:
  - name: BAMBU_PASSWORD
    required_when: "mode=cloud"
    storage: ".secrets.json"
    description: "Bambu Lab account password (cloud mode only)"
  - name: BAMBU_ACCESS_CODE
    required_when: "mode=local"
    storage: ".secrets.json"
    description: "LAN access code from printer Settings → Device (local mode only)"
  - name: BAMBU_3D_API_KEY
    required_when: "3D generation enabled"
    storage: ".secrets.json"
    description: "API key from chosen 3D generation provider (optional)"
security:
  no_credentials_shipped: true
  secrets_storage: ".secrets.json (chmod 600, git-ignored)"
  config_storage: "config.json (non-sensitive printer settings, git-ignored)"
  token_cache: ".token_cache.json (cloud auth token, 90d TTL, git-ignored). User can delete to force re-auth."
  verify_code_file: ".verify_code (one-time cloud login code, git-ignored)"
  files_gitignored: [".secrets.json", "config.json", ".token_cache.json", ".verify_code"]
  persistence: "Reads config.json at startup, .secrets.json on demand (lazy, not at import). Writes .token_cache.json, .verify_code locally. No remote data exfiltration."
  shipped_credentials: "NONE — no credentials, certificates, or keys are shipped or auto-downloaded."
  x509_setup: "User provides authentication certificate during setup if they enable Developer Mode auto-print. Stored locally in references/*.pem (git-ignored, key chmod 600). Not shipped, not downloaded by code."
  x509_scope: "Signs MQTT commands for LAN auto-print only. Requires user's own access code + same network."
  notifications: "Notifications use ONLY local macOS osascript (display notification) and a local JSONL log file. No external notification services (Discord/Telegram/Slack/etc.) are implemented in code — those are handled by the agent's own messaging tools if available. The skill itself makes NO outbound calls for notifications."
  network_access:
    - "Bambu Lab Cloud API (bambulab.com) — printer control, cloud mode only, requires user credentials"
    - "Bambu Lab MQTT (LAN, local network only) — printer control, local mode only"
    - "Meshy API (api.meshy.ai) — 3D generation, optional, requires user-provided API key"
    - "Tripo3D API (api.tripo3d.ai) — 3D generation, optional, requires user-provided API key"
    - "Hyper3D Rodin API (hyperhuman.deemos.com) — 3D generation, optional, requires user-provided API key"
    - "Printpal API — 3D generation, optional, requires user-provided API key"
    - "3D AI Studio API — 3D generation, optional, requires user-provided API key"
    - "DuckDuckGo (via ddgs library) — model search, no API key needed"
  consent: "All network calls, file writes, printer operations, and monitoring require explicit user consent. No credentials are auto-fetched or auto-stored without user confirmation."
keywords:
  - 3d printing
  - bambu lab
  - ams
  - text to 3d
  - slicing
  - print monitoring
  - multi-color
---

# 🖨️ Bambu Studio AI

Request → Collect Info → Search/Generate → Analyze(11pt) → [Colorize] → Preview(chat) → Open BS → [User Slices in BS] → Confirm → Print → Monitor

Pre-check: If `config.json` does not exist → run First-Time Setup before any operation.

**At the start of each turn:** If handling a print request, re-read the Pipeline Checklist and Compliance Rules. Ensure you are not skipping any MUST step.

---

## ⛔ COMPLIANCE RULES — Follow Strictly

**Before every action, verify you are not violating these rules:**

| Rule | Meaning |
|------|---------|
| **MUST** | Non-negotiable. Skip = failure. |
| **NEVER** | Forbidden. Doing it = failure. |
| **WAIT** | Do not proceed until user responds. |

### NEVER Do These
- ❌ **NEVER skip Information Collection** — Always ask: model source (search/generate), dimensions (if generating), single/multi-color, material
- ❌ **NEVER generate without dimensions** — MUST ask "How big? e.g., 80mm tall" before `generate.py`
- ❌ **NEVER skip analyze** — Every model MUST go through `analyze.py --orient --repair`
- ❌ **NEVER skip preview** — MUST send preview image/GIF to chat before opening Bambu Studio. User must SEE the model.
- ❌ **NEVER skip Bambu Studio confirmation** — MUST open in BS, tell user to inspect, WAIT for explicit "looks good" / "print it"
- ❌ **NEVER auto-print** — No `bambu.py print` without user confirmation. AI models have errors.
- ❌ **NEVER skip model source choice** — MUST ask user: search vs generate vs not sure (default: search first)

### MUST Do These (in order)
1. **Collect info** → Ask model source, dimensions (if generate), colors, material
2. **Get model** → Search or generate per user choice
3. **Analyze** → `analyze.py --orient --repair` on every model
4. **Preview to chat** → `preview.py --views turntable` → **send image/GIF to user**
5. **Open Bambu Studio** → `open -a "BambuStudio" model.3mf` (or model.stl/obj)
6. **User slices in Bambu Studio** → Tell user to slice, inspect, and confirm
7. **Wait for confirmation** → Do not proceed until user says ready
8. **Print** → Only after confirmation

> **Note:** `slice.py` (CLI slicing via OrcaSlicer) is **optional** — only use if user explicitly requests CLI slicing. The default is for users to slice in Bambu Studio themselves, where they can adjust supports, infill, and other settings visually.

### Pipeline Checklist (verify before claiming done)
```
[ ] Info collected (source, dimensions, colors, material)
[ ] Model obtained (search/generate/download)
[ ] analyze.py --orient --repair run
[ ] Preview image/GIF sent to chat
[ ] Opened in Bambu Studio
[ ] User sliced + inspected in Bambu Studio
[ ] User confirmed "looks good" / "print it"
[ ] Print started (only after confirmation)
```

---

## Quick Reference

| I want to... | Command |
|---|---|
| Printer status | `python3 scripts/bambu.py status` |
| Print progress | `python3 scripts/bambu.py progress` |
| Printer hardware info | `python3 scripts/bambu.py info` |
| Start a print | `python3 scripts/bambu.py print <file> --confirmed` |
| Pause / Resume / Cancel | `python3 scripts/bambu.py pause\|resume\|cancel` |
| Speed mode | `python3 scripts/bambu.py speed silent\|standard\|sport\|ludicrous` |
| Light on/off | `python3 scripts/bambu.py light on\|off` |
| AMS filament info | `python3 scripts/bambu.py ams` |
| Camera snapshot | `python3 scripts/bambu.py snapshot` |
| Send G-code | `python3 scripts/bambu.py gcode "G28"` |
| Notification | `python3 scripts/bambu.py notify --message "done"` |
| Generate 3D (text) | `python3 scripts/generate.py text "desc" --wait --height 80` (`--raw` skips auto-enhancement; `--height` sets target mm, default auto 80mm) |
| Generate 3D (image) | `python3 scripts/generate.py image photo.jpg --wait --height 80` (auto: validate, bg-remove, prompt enhance; `--no-bg-remove` / `--raw` to skip) |
| Download model | `python3 scripts/generate.py download <task_id> --height 80` |
| Analyze model | `python3 scripts/analyze.py model.stl --height 80 --orient --repair --material PLA` (always exports `_scaled` file when `--height` is used) |
| Keep main only (remove fragments) | `python3 scripts/analyze.py model.stl --repair --keep-main` |
| Multi-color | `python3 scripts/colorize model.glb --height 80 --max_colors 8 -o out.obj` (tunable: `--min-pct`, `--no-merge`, `--island-size`, `--smooth`, `--bambu-map`) |
| Slice (optional CLI) | `python3 scripts/slice.py model.stl --orient --arrange --quality fine` |
| Slice (specific setup, optional) | `python3 scripts/slice.py model.stl --printer A1 --filament "Bambu PETG Basic"` |
| List slicer profiles | `python3 scripts/slice.py --list-profiles` |
| Preview (quick) | `python3 scripts/preview.py model.stl` (`--height 80` to verify dimensions) |
| Preview (HQ Blender) | `python3 scripts/preview.py model.stl --hq` |
| Search models | `python3 scripts/search.py "phone stand" --limit 5` |
| Monitor print | `python3 scripts/monitor.py --auto-pause` |
| Check deps | `python3 scripts/doctor.py` |
| Parametric box | `python3 scripts/parametric.py box 30 20 10 -o box.stl` |
| Parametric cylinder | `python3 scripts/parametric.py cylinder --radius 5 --height 20 -o cyl.stl` |
| Parametric bracket | `python3 scripts/parametric.py bracket --width 30 --height 40 --thickness 3 --hole-diameter 3.2 -o bracket.stl` |
| Parametric plate with holes | `python3 scripts/parametric.py plate-with-holes --width 60 --depth 40 --holes 4 --hole-diameter 3.2 --hole-spacing 25 -o plate.stl` |
| Parametric enclosure | `python3 scripts/parametric.py enclosure --width 60 --depth 40 --height 30 --wall 2 --lid -o case.stl` |
| Parametric CSG (complex) | `python3 scripts/parametric.py csg spec.json -o assembly.stl` |

All scripts support `--help`. `generate.py` auto-enhances prompts and limits size to printer build volume.

---

## Overall Flow

```
User Request
    │
    ▼
Information Collection
    │
    ▼
Decision 1: Model Source
    ├─ A: Internet Search (preferred default)
    ├─ B: AI Generate (single-color)
    ├─ C: AI Generate (multi-color)
    ├─ D: User-provided file
    ├─ E: Image to 3D
    └─ F: Parametric (functional parts — manifold3d)
    │
    ▼
Model Processing (analyze → repair → orient → [colorize])
    │
    ▼
Report Results to User
    │
    ▼
⛔ Open in Bambu Studio → User Inspects
    │
    ▼
User Confirms ("looks good" / "print it")
    │
    ▼
Decision 2: Print Method
    ├─ E: Auto Print (Developer Mode only, not recommended)
    └─ F: Manual Print (user handles in Bambu Studio)
    │
    ▼
Print Monitoring (both workflows, or on user request)
```

---

## Step 1: Information Collection

**Gate:** Before ANY search/generate/download, you MUST complete this step.

Collect before proceeding:

**Model requirements:**
- What to print (object description)
- Target dimensions — MUST ask before generating ("How big? e.g., 80mm tall")
- Style / appearance (optional)

**Print parameters:**
- Single-color or multi-color (AMS)
- Material (default: PLA)
- Quality: draft / standard / fine / extra (optional)
- Purpose: functional or decorative (optional, affects walls + infill)

**Model source — ask user:**
> "Do you want me to:
> 1. 🔎 Search online — existing models, usually higher quality
> 2. 🎨 AI generate — custom model from scratch
> 3. 🤷 Not sure — I'll search first, generate if nothing fits"

Default: search first. Common objects (phone stand, hook, vase) almost always exist online.

**Decision flow:** User says "search" / "generate" / "not sure" → If "not sure" → search first → if no good results → offer generate.

**Auto-routing (agent determines path based on description):**

| Signal in user's description | Route to | Examples |
|------------------------------|----------|----------|
| Specific dimensions / tolerances / fit | Parametric (Workflow F) | "M3 screw hole", "inner diameter 40mm", "press fit" |
| Standard interfaces / mounting | Parametric (Workflow F) | "USB-C cutout", "GoPro mount", "VESA mount" |
| Functional part keywords | Parametric (Workflow F) | "bracket", "hinge", "hook", "clip", "gear", "mount", "enclosure", "stand" |
| Characters / figurines / organic | AI Generate (Workflow B/C) | "pikachu", "dragon", "bust", "sculpture" |
| Decorative / artistic | AI Generate (Workflow B/C) | "vase", "lamp shade", "desk ornament" |
| Photo reference | Image-to-3D (Workflow E) | user sends image file or URL |

When the description clearly matches functional/precision signals, skip the source question and route directly to Workflow F. If ambiguous (e.g., "phone stand" — could be searched or parametric), default to search first.

---

## Step 2: Model Source (Decision Point 1)

**Gate:** Before this step, you MUST have asked user: "Search, generate, or not sure?" Default: search first.

### Workflow A — Internet Search (preferred)

1. `search.py "query" --limit 5` → MakerWorld, Printables, Thingiverse, Thangs
2. Present results with name, source, URL
3. User selects → download → validate format (STL/OBJ/3MF)
4. → Model Processing

If no good results → offer AI generate.

### Workflow B — AI Generate (single-color)

**Checkpoint before generate:** Did you ask for dimensions? If not, ask now.

1. First-time disclaimer (once): "AI models depend on provider + prompt. NOT production-ready — always review in Bambu Studio."
2. Confirm dimensions — **MUST have before** `generate.py text`
3. `generate.py text "prompt" --wait --height <mm>` → auto-enhances, auto-scales to exact target
4. `preview.py model.stl --views turntable --height <mm> -o preview.gif` → **send GIF to chat** (verifies dimensions)
5. → Model Processing

### Workflow C — AI Generate (multi-color)

**Checkpoint before generate:** Did you ask for dimensions? If not, ask now.
Do NOT ask user to specify colors upfront — AI textures determine the colors. Colorize will auto-detect them.

1. Same disclaimer as B
2. Confirm **dimensions only** — "What size do you want?" is the only required question
   - Colors are auto-detected from AI texture, NOT user-specified
   - If user volunteers color preferences (e.g., "only 3 colors"), note for colorize params
3. `generate.py text "prompt" --wait --height <mm>` → textured GLB (scaled to target height)
4. `python3 scripts/colorize model.glb --height <mm> --max_colors 8 --bambu-map` → vertex-color OBJ + _color_map.txt
5. `preview.py model.obj --views turntable --height <mm> -o preview.gif`
6. **Send ONE consolidated report** (MUST include all of the following in a single message):

   **Multi-color report template:**
   > ## 🎨 [Model Name] Multi-Color Preview
   >
   > 📷 [attach _preview.png AND turntable.gif]
   >
   > | # | Color | Hex | % | Suggested Filament | ΔE |
   > |---|-------|-----|---|--------------------|----|
   > | 1 | yellow | #FFD700 | 58% | PLA Basic Yellow | 3.2 |
   > | 2 | brown | #8B4513 | 22% | PLA Basic Brown | 5.1 |
   > | ... | | | | | |
   >
   > **N colors detected, AMS compatible.** Ready to proceed?
   > - Want fewer colors → I'll re-run with `--max_colors N`
   > - Want to adjust → tell me what to change
   > - Looks good → I'll open in Bambu Studio

7. **WAIT for user response.** If user requests changes → re-run colorize → show updated report
8. When user approves → Model Processing

⚠️ BS import may fail to detect vertex colors — see Step 4 for import procedure.

**Colorize tuning (only if user requests adjustments):**
| Parameter | Default | Effect |
|-----------|---------|--------|
| `--max_colors N` | 8 | Maximum colors (hard limit ≤8 for AMS) |
| `--min-pct X` | 0.1 | Min family % threshold (0=keep all, 5=aggressive filter) |
| `--no-merge` | off | Disable family group exclusion (all 12 families independent) |
| `--island-size N` | 1000 | Remove isolated patches < N pixels (0=disabled) |
| `--smooth N` | 5 | Majority vote boundary passes (0=raw, higher=smoother) |
| `--bambu-map` | on | Output _color_map.txt with suggested Bambu filaments (CIELAB match) |

### Workflow D — User-Provided File

1. Validate format (STL/OBJ/3MF/GLB), convert if needed
2. → Model Processing

### Workflow E — Image to 3D

**Trigger:** User provides a photo, image file, or image URL to generate a 3D model from.

**Checkpoint:** Did you ask for dimensions? If not, ask now. Do NOT ask for colors — they come from the image.

1. Same disclaimer as B
2. Confirm **dimensions only**
3. Save image to workspace (if from chat) or note the file path/URL
4. `python3 scripts/generate.py image photo.jpg --wait` (auto: validate, remove background, enhance prompt)
   - To skip background removal: add `--no-bg-remove`
   - To skip prompt enhancement: add `--raw`
5. **Auto-detect single vs multi-color:**
   - If downloaded GLB has texture → run colorize (same as Workflow C steps 4-6, send consolidated multi-color report)
   - If no texture → single-color path (same as Workflow B steps 4-5)
6. Preview + report to user → WAIT for approval
7. When user approves → Model Processing

**Tips for best results:**
- Clean product photos on plain/white background work best
- Single object, centered, well-lit
- Multiple angles of the same object are NOT supported (single image only)
- If background removal hurts the result, re-run with `--no-bg-remove`

### Workflow F — Parametric (functional parts)

**Trigger:** User requests a part with precise dimensions, standard interfaces (screw holes, mounts), or functional keywords (bracket, hinge, enclosure). See auto-routing table in Step 1.

**Checkpoint:** MUST have exact dimensions in mm. Do NOT accept vague sizes like "about 80mm" — ask for precise values.

1. Collect **exact dimensions** — width, height, depth, wall thickness, hole sizes, spacing
2. Identify standard interfaces: screw size (M3? M4?), mounting pattern, clearance vs press fit
3. Choose the right `parametric.py` command:
   - Simple shapes → `box`, `cylinder`, `sphere`, `extrude`
   - L-brackets → `bracket --width W --height H --thickness T --hole-diameter D`
   - Mounting plates → `plate-with-holes --width W --depth D --holes N --hole-diameter D --hole-spacing S`
   - Enclosures → `enclosure --width W --depth D --height H --wall T [--lid]`
   - Complex assemblies → write a JSON spec, use `csg spec.json`
4. `python3 scripts/parametric.py <command> [args] -o model.stl`
5. `preview.py model.stl --views turntable -o preview.gif` → **send GIF to chat**
6. Report dimensions, volume, triangle count (printed by parametric.py)
7. **WAIT for user approval** — user may request dimension adjustments
8. If adjustments needed → modify command/spec, regenerate, re-preview
9. When user approves → Model Processing

**Advantages over AI generation:**
- Exact dimensions (to 0.01mm precision)
- Guaranteed watertight mesh (no repair needed)
- Instant generation (no API call, no waiting)
- Free (no API credits consumed)
- Reproducible (same params = same output)

**Limitations:**
- Geometric shapes only — no organic/artistic forms
- Single-color output (STL) — no vertex colors or textures

**Reference:** See `references/manifold-examples.md` for tolerance tables, CSG JSON patterns, and design rules.

---

## Step 3: Model Processing

**Gate:** Before this step, you MUST have a model file (from search, generate, or user).

All models MUST go through this. No exceptions. **NEVER skip analyze or preview.**

**Analysis (11-point check):**
```
analyze.py model.stl --orient --repair --material PLA --purpose functional
```
Checks: dimensional tolerance, wall thickness, load direction, overhangs (>45°), print orientation, floating parts, layer height, infill rate, wall count, top layers, material compatibility. Also: watertight, manifold, build volume fit.

**Auto-repair:** Fix normals, fill holes, remove degenerate faces.

**Auto-orient:** Optimal stability, auto unit detection (meters→mm).

**Report to user (MANDATORY):**
- Printability score (X/10)
- Warnings and issues
- Repairs performed
- Recommended settings (layer height, infill, walls, temps, supports)

Example: "Score 8/10. Repaired 58K non-manifold edges. Walls: 1.5mm ✅ Overhangs: 3.2% ✅ Recommended: 0.20mm layers, 20% infill, PLA 210°C."

**Preview rendering (MANDATORY — NEVER skip):**
```
preview.py model.stl --views turntable -o model_preview.gif
```
- Single-color: renders STL/3MF with default blue material
- Multi-color: renders colorize'd OBJ with vertex colors
- **MUST send the preview image/GIF to the chat** — user cannot proceed without seeing it
- If turntable too slow, use `--views perspective` for a single image
- **Checkpoint:** Have you attached the preview to your message? If not, do it before opening BS

**Optional CLI Slice** (only if user explicitly requests):
```
slice.py model.stl --orient --arrange --quality standard
```
Auto-detects printer + nozzle. Quality: draft(0.24) / standard(0.20) / fine(0.12) / extra(0.08). Output: .3mf with G-code.

---

## Step 4: User Confirmation

⛔ **MANDATORY — NEVER SKIP**

**Gate:** Before this step, you MUST have: (1) sent preview to chat.

1. Open in Bambu Studio: `open -a "BambuStudio" model.3mf` (or .stl/.obj)
2. **Multi-color OBJ — special import procedure (BS import is unstable):**
   - Always open via **File → New Project → Import**, NOT "Import to current plate"
   - After import: check color count in right panel — if BS shows 1 color instead of N:
     1. Close BS completely, reopen, then import again
     2. Or drag-and-drop the OBJ file into an empty BS window
   - If BS still refuses to recognize vertex colors → flag as BS import compatibility issue; do NOT re-run colorize
3. Tell user to inspect and slice:
   > "I've opened the model in Bambu Studio. Please:
   > - Check: does it look correct? Missing or deformed parts?
   > - Check: floating/disconnected pieces?
   > - Check: correct size? (check dimensions in bottom bar)
   > - **For multi-color:** verify the right panel shows the correct number of colors
   > - **Slice** in Bambu Studio (Ctrl+R / Cmd+R) and review: estimated time, filament usage, supports.
   > Let me know when ready!"
4. WAIT for explicit confirmation.

⛔ NEVER auto-print. AI models frequently have errors analysis can't fully catch.

5. Ask print method:
   - Direct automatic printing → Workflow E (Developer Mode only, not recommended)
   - Manual in Bambu Studio → Workflow F

---

## Step 5: Print Execution (Decision Point 2)

### Workflow E — Auto Print (Developer Mode only, not recommended)
⚠️ Requires Developer Mode ON. Bambu Studio and Bambu Handy will disconnect.
1. `bambu.py print model.3mf --confirmed`
2. Confirm: "Print started!"
3. → Monitoring

### Workflow F — Manual Print
- Model already open in Bambu Studio
- User adjusts settings and prints manually from BS/Handy

**Print detection — two methods:**

1. **Active listen (after model handoff):** When agent opens a model in BS (Workflow B/C/D), immediately start a background MQTT listener (30 min window). If printer state changes to RUNNING → notify user and offer monitoring.
   - Implementation: background `exec` running paho-mqtt subscribe loop, poll every 30s for state change
   - Auto-stop after 30 min if no print detected
   - On detection: "🖨️ I see you started printing [filename]! Want me to monitor with live updates and snapshots?"

2. **Heartbeat fallback:** During regular heartbeats, check printer MQTT status. If RUNNING and not already monitoring → notify user.

- If user accepts → Start Monitoring (Step 6)

---

## Step 6: Print Monitoring

Trigger: Auto print (Workflow E), manual print (Workflow F), or user request. Requires LAN mode.

⚠️ Always ask: "Want me to monitor? Auto-pause on serious issues?"

**Monitoring method:** Direct MQTT subscription via paho-mqtt (NOT bambulabs_api — it has SSL issues).
Connect to `{printer_ip}:8883`, subscribe to `device/{serial}/report`, parse `print` messages.

**Camera snapshots are MANDATORY during monitoring:**
- Capture via RTSP: `bambu.py snapshot` (ffmpeg → rtsps://bblp:{code}@{ip}:322/streaming/live/1)
- Send snapshot with EVERY progress update to user
- Include snapshot in anomaly alerts

**Default monitoring schedule (milestone-based, ~5 messages per print):**
| Event | Trigger | Action |
|---|---|---|
| Print start | State → RUNNING | Notify + 📸 snapshot |
| 25% progress | mc_percent ≥ 25 | Status + 📸 snapshot |
| 50% progress | mc_percent ≥ 50 | Status + 📸 snapshot |
| 75% progress | mc_percent ≥ 75 | Status + 📸 snapshot |
| Print complete | State → FINISH/IDLE | Completion + 📸 final snapshot |
| Anomaly | Any time | Immediate alert + 📸 snapshot + auto-pause (if enabled) |

User can adjust frequency. Track reported milestones to avoid duplicates.

**Anomaly detection:**
| Anomaly | Severity | Action |
|---|---|---|
| Progress stall >10min | Warning | Alert user + snapshot |
| Temperature anomaly | Critical | Alert + snapshot + auto-pause |
| Print failure/error | Critical | Alert + snapshot + auto-pause |
| Unexpected pause | Warning | Alert user + snapshot |
| Bed detachment | Critical | Auto-pause + alert + snapshot |
| Spaghetti | Critical | Auto-pause + alert + snapshot |

**Status report format (send to user):**
```
🖨️ Print Update — {filename}
📊 Progress: {percent}% | Layer {current}/{total}
⏱️ Remaining: {time}
🔥 Nozzle: {temp}°C | 🛏️ Bed: {temp}°C
📸 [attached snapshot]
```

---

## First-Time Setup

Triggered when `config.json` doesn't exist. Conversational:

1. **Printer model** — A1 Mini, A1, P1S, P2S, X1C, X1E, H2C, H2S, H2D
2. **Connection** — LAN (recommended: IP + serial + access code) or Cloud (email + password, limited)
3. **Print mode** — MUST explain clearly to user:
   - **Option A: Recommended (safe)** — Agent generates model → opens in Bambu Studio → user slices, reviews, and prints manually. No special printer settings needed.
   - **Option B: Full auto-print** — Agent controls printer directly (start/stop/monitor via MQTT). Requires:
     - ⚠️ **Developer Mode ON** (printer touchscreen → Settings → LAN Only Mode → ON → Developer Mode → ON)
     - ⚠️ Bambu Studio and Bambu Handy will **completely disconnect** (no cloud, no remote monitoring)
     - ⚠️ Only LAN access (same network only)
     - Agent still ALWAYS shows preview before printing (never auto-prints without user confirmation)
   - Save choice as `print_mode: "manual"` or `print_mode: "auto"` in config.json
4. **3D generation** (optional) — Meshy, Tripo, Printpal, 3D AI Studio + API key
5. **Notifications** — macOS system notifications (automatic). Agent handles chat notifications via its own messaging tools.
6. **Save** — `config.json` + `.secrets.json` (chmod 600, git-ignored)
7. **Verify** (ask permission) — test connection, camera, AMS
8. **Summary**

---

## Environment & Dependencies

**Required:** `python3`, `pip3` (macOS recommended; core scripts work cross-platform)
```bash
pip3 install bambulabs-api bambu-lab-cloud-api requests trimesh numpy Pillow ddgs pygltflib cryptography paho-mqtt scipy
```
**Optional (macOS):** `ffmpeg` (camera), Bambu Studio (model preview + slicing), Blender 4.0+ (multi-color + HQ preview), OrcaSlicer (CLI slicing)

**Env vars** (override config.json): `BAMBU_MODE`, `BAMBU_MODEL`, `BAMBU_EMAIL`, `BAMBU_IP`, `BAMBU_SERIAL`, `BAMBU_3D_PROVIDER`

**Secrets** (`.secrets.json`, chmod 600): `password`, `access_code`, `3d_api_key`. All user-provided, never shipped.

---

## Common Agent Mistakes (self-check)

| Mistake | Correct behavior |
|---------|------------------|
| Skipping "search vs generate" question | MUST ask user first. Default: search. |
| Generating without dimensions | MUST ask "How big? e.g., 80mm tall" |
| Running generate.py then immediately opening BS | MUST run analyze.py and preview.py in between |
| Saying "I've prepared the model" without sending image | MUST attach preview GIF/image to the message |
| Opening Bambu Studio without user seeing preview | User must see preview in chat BEFORE you open BS |
| Proceeding to print without "looks good" | MUST wait for explicit user confirmation |
| Skipping analyze "because it's from search" | ALL models need analyze — search results can have issues too |
| Re-generating when model has 68 fragments | First check preview — AI meshes often report many "bodies" but look fine. Only use `--keep-main` if model is visually fragmented |

---

## Common Issues

| Problem | Fix |
|---|---|
| SSL handshake error (LAN) | Normal (self-signed certs). Handled automatically. |
| API method not found | `pip3 install --upgrade bambulabs-api` (v2.6.6+) |
| Can't connect (LAN) | LAN Mode ON + correct IP + same network |
| Cloud verification code | Wait for email, enter once. Token cached 90 days. |
| Camera timeout | Wake printer (tap screen), check IP. |
| AI model has holes/floating parts | Expected. Always run `analyze.py --repair`. |
| Tripo/ Meshy reports 68+ "bodies" | Usually harmless (non-manifold topology, not actual fragments). Check preview first — only use `--keep-main` if model is visually broken |
| BS imports multi-color OBJ as single color | Close BS → reopen → **File > New Project > Import OBJ** (not "Import to plate"). If still single-color after retry, this is a BS-side compatibility issue — do NOT re-run colorize |

---

## Known Limitations

| Feature | Status |
|---|---|
| Single-color pipeline | ✅ Stable |
| Multi-color (colorize) | ⚠️ Colorize pipeline stable; BS vertex-color OBJ import occasionally fails to detect colors — use File → New Project → Import, NOT "Import to plate" |
| CLI slicing | ✅ OrcaSlicer backend (BS CLI SEGFAULT in v2.5.0) |
| End-to-end auto-print | ✅ Works with Developer Mode ON (X.509 signed MQTT + FTP upload) |
| Parametric modeling | ✅ manifold3d — geometric/functional parts only, no organic forms. Single-color STL output. |

---

## Reference Documents

- `references/model-specs.md` — All 9 printer specifications
- `references/manifold-examples.md` — Parametric modeling API, tolerance tables, CSG patterns
- `references/bambu_filament_colors.json` — Bambu Lab 43-color palette (reference only, colorize v4 uses texture-native colors)
- `references/bambu-mqtt-protocol.md` — MQTT protocol
- `references/bambu-cloud-api.md` — Cloud API
- `references/3d-generation-apis.md` — Provider API endpoints
- `references/3d-prompt-guide.md` — Prompt engineering for 3D

## License

MIT · GitHub: https://github.com/heyixuan2/bambu-studio-ai
