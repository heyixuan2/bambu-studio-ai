# 🖨️ Bambu Studio AI

Full-stack Bambu Lab 3D printing skill for [OpenClaw](https://github.com/openclaw/openclaw) — from idea to finished print.

**Idea → 3D Model → Preview → Print → Monitor → Notify**

[![ClawHub](https://img.shields.io/badge/ClawHub-bambu--studio--ai-blue)](https://clawhub.ai/heyixuan2/bambu-studio-ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## What It Does

| Feature | Description |
|---------|-------------|
| 🖨️ **Printer Control** | Status, print, pause, resume, cancel, speed, light, G-code |
| 🎨 **AI 3D Generation** | Text-to-3D and Image-to-3D via Meshy, Tripo3D, Printpal, or 3D AI Studio |
| 🔍 **AI Print Monitoring** | Periodic camera snapshots → AI anomaly detection → auto-pause |
| 📦 **AMS Management** | Filament slot status, low-filament alerts |
| 📸 **Camera** | Live snapshots from printer camera |
| 🔔 **Notifications** | Print complete/fail alerts via Discord, iMessage, Telegram, WhatsApp, Slack |
| 🌐 **Dual Mode** | Cloud (remote, anywhere) + Local (LAN, faster) |

## Supported Printers

All 9 Bambu Lab models:

| Series | Models | Highlights |
|--------|--------|------------|
| 🟢 **A** (Entry) | A1 Mini, A1 | 180–256mm³, 500mm/s |
| 🔵 **P** (Prosumer) | P1S, P2S | Enclosed, up to 600mm/s |
| 🟠 **X** (Pro) | X1C, X1E | AI features, industrial |
| 🔴 **H** (High-end) | H2C, H2S, H2D | 350°C, 1000mm/s, dual extruder, laser |

## Install

```bash
clawhub install bambu-studio-ai
```

Or manually:
```bash
git clone https://github.com/YOUR_USERNAME/bambu-studio-ai.git ~/.agents/skills/bambu-studio-ai
pip3 install bambulabs-api bambu-lab-cloud-api requests
```

## Setup

No CLI wizard needed — your OpenClaw agent handles setup through conversation:

1. Tell your agent anything about printing (e.g., "check my printer")
2. Agent detects no config → walks you through setup:
   - Printer model
   - Cloud or Local connection
   - AI 3D generation provider (optional)
   - Notification channel
   - Print monitoring preferences
3. Agent runs verification tests (with your permission)
4. Done!

## The Full Pipeline

```
You: "Make me an iPhone 15 Pro Max case and print it"

Agent: "Let me look up the exact dimensions — ok?"     ← Research
Agent: "159.9×76.7×8.25mm, camera bump 40×36mm.        ← Confirm specs
        I'll add 1mm tolerance. TPU material.
        Generating 3MF now..."
                    ↓
        generate.py → Meshy API → phone_case.3mf        ← Generate (3MF priority)
                    ↓
        analyze.py → 10-point printability check            ← AI Analysis
        "Score 9/10. Wall thickness OK, no overhangs.
         Recommended: 0.2mm layers, 30% infill, 3 walls"
                    ↓
Agent: "Score 9/10 ✅ Opening in Bambu Studio             ← Preview
        for you to preview and slice..."
                    ↓
Agent: "Looks good? Ready to print?"                     ← User confirms
                    ↓
        bambu.py print phone_case.3mf                    ← Print
                    ↓
        monitor.py (every 5 min)                         ← AI monitors
                    ↓
Agent: "Print complete! Here's the final photo."         ← Notify
```

## AI 3D Generation

### Supported Providers

| Provider | Text→3D | Image→3D | Price |
|----------|---------|----------|-------|
| **Meshy** | ✅ | ✅ | Free tier + $20/mo |
| **Tripo3D** | ✅ | ✅ | Free tier + $10/mo |
| **Printpal** | ✅ | ✅ | Print-optimized |
| **3D AI Studio** | ✅ | ✅ | Early access |

### Output Format Priority

Models are generated in Bambu Lab compatible formats:

| Priority | Format | Why |
|----------|--------|-----|
| 1st | **.3mf** | Bambu Lab native format, best compatibility |
| 2nd | **.stl** | Universal, widely supported |
| 3rd | **.step/.stp** | Precise geometry, editable |
| 4th | **.obj** | Fallback, basic mesh |

### Smart Features

- **Auto prompt enhancement** — adds 3D printing constraints (wall thickness, overhangs, flat base)
- **Auto size limiting** — scales to your printer's build volume
- **Pre-generation research** — agent looks up real dimensions (with your permission)
- **Bambu Studio preview** — opens model in Bambu Studio before printing (mandatory)

## Print Monitoring

AI-powered anomaly detection with configurable intensity:

| Level | Interval | Token Cost | Best For |
|-------|----------|------------|----------|
| 🟢 **Light** | Every 30 min | ~2 tokens/hr | Long prints, budget-conscious |
| 🟡 **Standard** | Every 5 min | ~12 tokens/hr | Recommended default |
| 🔴 **Intensive** | Every 2 min | ~30 tokens/hr | Critical prints, new materials |
| ⚫ **Off** | — | 0 | When you're watching it yourself |

Agent asks during setup: *"How closely should I monitor your prints?"*

### What It Detects

| Issue | Severity | Action |
|-------|----------|--------|
| Stringing | ⚠️ Low | Continue, note for cleanup |
| Warping | ⚠️ Medium | Watch closely |
| Layer Shift | ❌ High | Recommend pause |
| Detachment | ❌ Critical | Auto-pause + alert |
| Spaghetti | ❌ Critical | Auto-pause + alert |

## Configuration

Two files, auto-loaded by all scripts:

### config.json (non-sensitive)
```json
{
  "model": "H2D",
  "mode": "cloud",
  "email": "user@example.com",
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
  "access_code": "lan_access_code",
  "3d_api_key": "generation_api_key"
}
```

## Commands

```bash
# Printer
python3 scripts/bambu.py status
python3 scripts/bambu.py progress
python3 scripts/bambu.py print model.3mf
python3 scripts/bambu.py pause | resume | cancel
python3 scripts/bambu.py speed silent|standard|sport|ludicrous
python3 scripts/bambu.py light on|off
python3 scripts/bambu.py ams
python3 scripts/bambu.py snapshot
python3 scripts/bambu.py gcode "G28"

# 3D Generation
python3 scripts/generate.py text "phone stand with cable hole" --wait --format 3mf
python3 scripts/generate.py image photo.jpg --wait
python3 scripts/generate.py status <task_id>
python3 scripts/generate.py download <task_id> --format 3mf

# Analysis (before printing)
python3 scripts/analyze.py model.3mf                          # Quick check
python3 scripts/analyze.py model.stl --material PETG --purpose functional  # Full
python3 scripts/analyze.py model.3mf --render --json          # JSON + views

# Monitoring
python3 scripts/monitor.py --once
python3 scripts/monitor.py --interval 300
python3 scripts/monitor.py --interval 120 --auto-pause
```

## Project Structure

```
bambu-studio-ai/
├── SKILL.md                    — Agent instructions (566 lines)
├── README.md                   — This file
├── .gitignore
├── config/
│   ├── config.example.json     — Config template
│   └── .secrets.example.json   — Secrets template
├── references/
│   ├── bambu-mqtt-protocol.md  — MQTT protocol docs
│   ├── bambu-cloud-api.md      — Cloud API reference
│   ├── 3d-generation-apis.md   — 3D provider endpoints
│   ├── 3d-prompt-guide.md      — Prompt engineering guide
│   └── model-specs.md          — All 9 printer specs
└── scripts/
    ├── bambu.py                — Printer control (Cloud + Local)
    ├── analyze.py             — 10-point printability analysis
    ├── generate.py             — AI 3D model generation
    └── monitor.py              — AI print monitoring
```

## Contributing

PRs welcome! Especially for:
- Additional printer model support
- New 3D generation providers
- Better anomaly detection patterns
- Localization

## License

MIT
