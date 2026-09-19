# First-Time Setup

Setup is only needed for printer commands (status, print, monitor, camera, AMS) and for AI
generation. Search, analysis, parametric modeling and previews work without it.

Check the current state first:

```
python3 scripts/configure.py show
```

Walk the user through the missing pieces conversationally, a few questions at a time.
Save each answer as you go with `configure.py`, so you never hand-edit JSON and nothing is
lost if the conversation ends halfway.

## Contents

1. [Printer model](#1-printer-model)
2. [Connection: LAN or cloud](#2-connection-lan-or-cloud)
3. [Print modes](#print-modes)
4. [AI generation](#ai-generation)
5. [Verify](#5-verify)
6. [Settings reference](#settings-reference)
7. [Where files live](#where-files-live)

## 1. Printer model

One of: `A1 Mini`, `A1`, `P1S`, `P2S`, `X1C`, `X1E`, `X2D`, `H2C`, `H2S`, `H2D`
(case-insensitive). The model sets build-volume limits for generation and analysis.

```
python3 scripts/configure.py set model "A1 Mini"
```

## 2. Connection: LAN or cloud

**LAN (recommended).** Fastest, and the only mode with camera, G-code, monitoring and auto-print.
The computer running the agent must be on the same network as the printer.

1. On the printer touchscreen, turn on LAN mode (Settings → Network).
2. Note the **IP address**, **serial number** and **access code** (Settings → Device / Network).
3. Save them. The access code is a secret, so pass it on stdin so it doesn't end up in
   shell history or in the arguments of the settings command:

```
python3 scripts/configure.py set mode local printer_ip 192.168.1.50 serial 01P00A000000000
printf '%s' "$ACCESS_CODE" | python3 scripts/configure.py secret access_code
```

If you can't avoid seeing the value (the user typed it in chat), `--value` also works:
`configure.py secret access_code --value 12345678`. Don't repeat it back afterwards.

**Cloud.** Works from anywhere, but is limited: no camera, no G-code, no monitoring.

```
python3 scripts/configure.py set mode cloud email user@example.com
printf '%s' "$PASSWORD" | python3 scripts/configure.py secret password
```

The first login may trigger an emailed verification code. Ask the user for it, then either run
the command again with `BAMBU_VERIFY_CODE=123456` set in its environment, or write the code to
`~/.bambu-studio-ai/.verify_code`. The login token is cached for 90 days.

## Print modes

Explain both options clearly and let the user choose:

- **Manual (recommended, default).** The agent prepares the model and opens it in Bambu Studio.
  The user slices, reviews and starts the print themselves. No printer changes are needed, and
  Bambu Studio and Bambu Handy keep working.
- **Auto-print.** The agent uploads the file and starts the print over MQTT. This requires:
  - **Developer Mode ON** (touchscreen: Settings → LAN Only Mode → ON → Developer Mode → ON)
  - Accepting that **Bambu Studio cloud features and Bambu Handy disconnect** (LAN access only)
  - On current firmware, signed MQTT commands using certificate files the user supplies at
    `~/.bambu-studio-ai/bambu_connect_cert.pem` and `bambu_connect_key.pem`. The skill never
    ships or downloads these.

  Even in auto mode, the agent still shows a preview and waits for an explicit "print it"
  before starting.

```
python3 scripts/configure.py set print_mode manual     # or: auto
```

## AI generation

This is optional and only needed for text-to-3D and image-to-3D. Providers:

| Provider | `3d_provider` value | Notes |
|---|---|---|
| Meshy | `meshy` | Default. Text and image. Free tier available |
| Tripo3D | `tripo` | Text and image. Free tier available |
| Printpal | `printpal` | Tuned for printable geometry |
| 3D AI Studio | `3daistudio` | Early-access API |
| Hyper3D Rodin | `rodin` | High quality. Business plan; set `rodin_tier` (`Regular` / `Gen-2`) |

```
python3 scripts/configure.py set 3d_provider meshy
printf '%s' "$KEY" | python3 scripts/configure.py secret 3d_api_key
```

To keep keys for several providers, store `meshy_api_key`, `tripo_api_key` and so on. The key for
the active provider is used first, then `3d_api_key` as a fallback.

## 5. Verify

Ask before contacting the printer, then:

```
python3 scripts/bambu.py status      # connection
python3 scripts/bambu.py ams         # filaments loaded
python3 scripts/bambu.py snapshot    # camera (LAN + ffmpeg)
python3 scripts/doctor.py            # local dependencies
```

Finish with a short summary: printer, connection mode, print mode, generation provider, and
anything still missing, such as Blender or ffmpeg.

## Settings reference

`config.json` (non-secret):

| Key | Values | Purpose |
|---|---|---|
| `model` | printer model | Build volume, material limits |
| `mode` | `local` / `cloud` | Connection type (default `local`) |
| `printer_ip`, `serial` | | LAN connection |
| `email`, `device_id` | | Cloud connection (`device_id` is auto-detected) |
| `print_mode` | `manual` / `auto` | See [Print modes](#print-modes) |
| `3d_provider`, `rodin_tier` | | AI generation |
| `output_dir` | path | Where generated files go (default `./bambu-output`) |
| `printer_name`, `preferred_format`, `monitor_interval`, `auto_pause` | | Preferences |

`.secrets.json` (chmod 600): `access_code`, `password`, `3d_api_key`, `<provider>_api_key`.

Environment variables override both files: `BAMBU_MODE`, `BAMBU_MODEL`, `BAMBU_IP`,
`BAMBU_SERIAL`, `BAMBU_ACCESS_CODE`, `BAMBU_EMAIL`, `BAMBU_PASSWORD`, `BAMBU_DEVICE_ID`,
`BAMBU_VERIFY_CODE`, `BAMBU_3D_PROVIDER`, `BAMBU_3D_API_KEY`, `BAMBU_RODIN_TIER`.

## Where files live

| What | Location | Override |
|---|---|---|
| Config, secrets, token cache, certificates | `~/.bambu-studio-ai/` | `BAMBU_STUDIO_AI_HOME` |
| Generated models, previews, snapshots, logs | `./bambu-output/` (current directory) | `BAMBU_OUTPUT_DIR` or `output_dir` |

User state is kept outside the skill folder on purpose. Agents install skills into
directories that get replaced on update (`npx skills update`, `git pull`).

**Upgrading from v1.x:** older versions kept `config.json`, `.secrets.json` and the certificates
inside the skill folder. Those files are still read. Move them to the new location with:

```
python3 scripts/configure.py migrate
```
