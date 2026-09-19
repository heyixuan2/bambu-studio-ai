# Security and Data Handling

What the skill stores, what it connects to, and what it will never do. Share this with users who
ask whether it's safe to give an agent printer access.

## Credentials

- **Nothing is shipped.** The skill contains no credentials, certificates or keys, and never
  downloads any.
- **Secrets** (LAN access code, cloud password, AI provider keys) are stored only in
  `~/.bambu-studio-ai/.secrets.json`, created with permissions 600 (owner read/write only).
  They're written through `configure.py secret`, which reads from stdin so values stay out of
  shell history.
- **Non-secret settings** (printer model, IP, serial, provider) are in
  `~/.bambu-studio-ai/config.json`.
- **Cloud login token**: `~/.bambu-studio-ai/.token_cache.json` (600, expires after 90 days).
  Delete it to force a fresh login.
- **Auto-print certificates**, if the user sets up auto-print, live at
  `~/.bambu-studio-ai/bambu_connect_{cert,key}.pem`. The user supplies them. They're used only to
  sign MQTT commands to the user's own printer on the local network.
- Environment variables (`BAMBU_*`) override the files and are never written to disk by the skill.
- Secrets are read lazily when a command needs them, not when a module is imported.

## Network access

| Endpoint | When | Credentials |
|---|---|---|
| Printer on the LAN: MQTT 8883, FTPS 990, RTSP 322 | LAN mode printer commands, uploads, snapshots | LAN access code |
| Bambu Lab cloud API (bambulab.com) | Cloud mode only | Account email and password or token |
| Meshy, Tripo3D, Printpal, 3D AI Studio, Hyper3D Rodin | AI generation, only with the chosen provider | User's API key |
| DuckDuckGo (via the `ddgs` package) | Model search | None |
| Model sites (MakerWorld, Printables, …) | Downloading a model the user picked | None |

Notifications are local only: stdout, desktop notifications, and a JSONL log in the output
directory. The skill makes no outbound calls for notifications. Forwarding to chat apps is up to
the agent's own tools, if the user wants it.

## Physical safety

- `bambu.py print` refuses to run without `--confirmed`, and the skill instructs agents to pass
  it only after the user has reviewed the model and explicitly asked to print.
- Monitoring and auto-pause are opt-in.
- Raw G-code, cancel and speed changes should be confirmed with the user first (see the ground
  rules in SKILL.md).
