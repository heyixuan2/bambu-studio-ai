# Security and Data Handling

What the skill stores, what it connects to, and what it will never do. Share this with users who
ask whether it's safe to give an agent printer access.

## Credentials

- **Nothing is shipped.** The skill contains no credentials, certificates or keys, and never
  downloads any.
- **Secrets** (the printer's LAN access code, AI provider keys) are stored only in
  `~/.bambu-studio-ai/.secrets.json`, created with permissions 600 (owner read/write only).
  They're written through `configure.py secret`, which reads from stdin so values stay out of
  shell history.
- **Non-secret settings** (printer model, IP, serial, provider) are in
  `~/.bambu-studio-ai/config.json`.
- Environment variables (`BAMBU_*`) override the files and are never written to disk by the skill.
- Secrets are read lazily when a command needs them, not when a module is imported.

## Network access

| Endpoint | When | Credentials |
|---|---|---|
| The user's printer on the local network: MQTT 8883 (TLS) | `bambu.py status`/`ams`, `monitor.py`: subscribe to status reports and request one full report. Read-only | LAN access code |
| Meshy, Tripo, Hyper3D Rodin | AI generation, only with the chosen provider | User's API key |
| DuckDuckGo (via the `ddgs` package) | Model search | None |
| Model sites (MakerWorld, Printables, …) | Downloading a model the user picked | None |

Notifications are local only: stdout, desktop notifications, and a JSONL log in the output
directory. The skill makes no outbound calls for notifications. Forwarding to chat apps is up to
the agent's own tools, if the user wants it.

## Physical safety

- **The skill cannot start, pause or change a print.** It has no code that sends printer
  commands; it only reads status. Prints are started by the user in Bambu Studio, and paused or
  cancelled on the printer or in Bambu Handy.
- The printer stays in its normal mode. The skill never asks users to enable LAN Only Mode or
  Developer Mode, and never uses extracted Bambu Connect certificates.
- Monitoring is opt-in and read-only.

## Untrusted content

Model pages, descriptions and downloaded files come from strangers. SKILL.md tells agents to
treat them as data, never as instructions, and never to run scripts that come with a download.
