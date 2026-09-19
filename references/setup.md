# First-Time Setup

Nothing here is required to search, design, check or preview models. Setup adds three things:
the printer model (build volume and material limits), printer status (read-only), and AI
generation keys.

Check the current state first:

```
python3 scripts/configure.py show
```

Walk the user through the missing pieces conversationally, a few questions at a time.
Save each answer as you go with `configure.py`, so you never hand-edit JSON and nothing is
lost if the conversation ends halfway.

## Contents

1. [Printer model](#1-printer-model)
2. [Printer status (optional)](#2-printer-status-optional)
3. [AI generation (optional)](#3-ai-generation-optional)
4. [Verify](#4-verify)
5. [Settings reference](#settings-reference)
6. [Where files live](#where-files-live)

## 1. Printer model

One of: `A1 Mini`, `A1`, `A2L`, `P1P`, `P1S`, `P2S`, `X1C`, `X1E`, `X2D`, `H2C`, `H2S`, `H2D`,
`H2D Pro` (case-insensitive). The model sets build-volume and temperature limits for generation,
analysis and slicing.

```
python3 scripts/configure.py set model "A1 Mini"
```

## 2. Printer status (optional)

Lets the agent answer "is my print done?", "what's in the AMS?", and watch a print for problems.
It is **read-only** and works with the printer in its normal mode: no LAN Only Mode, no
Developer Mode, and the Bambu Handy app and cloud printing keep working. The computer running
the agent must be on the same network as the printer.

On the printer's touchscreen, find:

- **IP address** and **access code**: Settings → Network (the access code is the 8-character
  "LAN access code"; it changes if the user refreshes it)
- **Serial number**: Settings → Device

Save them. The access code is a secret: pass it on stdin so it stays out of shell history and
out of the settings command's arguments:

```
python3 scripts/configure.py set printer_ip 192.168.1.50 serial 01P00A000000000
printf '%s' "$ACCESS_CODE" | python3 scripts/configure.py secret access_code
```

If the user typed the code in chat, `--value` also works:
`configure.py secret access_code --value 12345678`. Don't repeat it back afterwards.

A router can give the printer a new IP after a restart. If status stops working, check the IP on
the touchscreen again (or ask the user to reserve one for the printer in their router).

### What this skill does not do

Starting, pausing, cancelling or changing a print from third-party software requires putting the
printer in LAN Only Mode with Developer Mode on, which disconnects the Bambu Handy app and cloud
printing. This skill doesn't ask users to do that. Prints start from Bambu Studio
(`bambu.py open model.3mf`, then **Print**), and pausing or cancelling happens on the printer
screen or in Bambu Handy.

## 3. AI generation (optional)

Only needed for text-to-3D and image-to-3D. Providers:

| Provider | `3d_provider` value | Notes |
|---|---|---|
| Meshy | `meshy` | Default. Text and image. API access needs a paid Meshy plan |
| Tripo | `tripo` | Text and image. Separate API credits (new accounts get trial credits) |
| Hyper3D Rodin | `rodin` | Text and image. API access depends on the Rodin plan |

```
python3 scripts/configure.py set 3d_provider meshy
printf '%s' "$KEY" | python3 scripts/configure.py secret meshy_api_key
```

Keys are stored per provider (`meshy_api_key`, `tripo_api_key`, `rodin_api_key`); `3d_api_key` is
a fallback for whichever provider is active. Details, pricing and formats:
[3d-generation-apis.md](3d-generation-apis.md).

## 4. Verify

Ask before contacting the printer, then:

```
python3 scripts/bambu.py status      # connection, progress, temperatures, loaded filaments
python3 scripts/bambu.py ams         # loaded filaments only
python3 scripts/doctor.py            # local dependencies and tools
```

Finish with a short summary: printer model, whether status works, the generation provider, and
anything still missing, such as Bambu Studio or Blender.

## Settings reference

`config.json` (non-secret):

| Key | Values | Purpose |
|---|---|---|
| `model` | printer model | Build volume, material and temperature limits |
| `printer_ip`, `serial` | | Printer status over the local network |
| `3d_provider`, `rodin_tier` | | AI generation |
| `output_dir` | path | Where generated files go (default `./bambu-output`) |

`.secrets.json` (chmod 600): `access_code`, `<provider>_api_key`, `3d_api_key`.

Environment variables override both files: `BAMBU_MODEL`, `BAMBU_IP`, `BAMBU_SERIAL`,
`BAMBU_ACCESS_CODE`, `BAMBU_3D_PROVIDER`, `BAMBU_3D_API_KEY`, `BAMBU_OUTPUT_DIR`,
`BAMBU_STUDIO_AI_HOME`.

## Where files live

| What | Location | Override |
|---|---|---|
| Config, secrets, monitor state | `~/.bambu-studio-ai/` | `BAMBU_STUDIO_AI_HOME` |
| Generated models, previews, monitor events | `./bambu-output/` (current directory) | `BAMBU_OUTPUT_DIR` or `output_dir` |

User state is kept outside the skill folder on purpose. Agents install skills into
directories that get replaced on update (`npx skills update`, `git pull`).

**Upgrading from v1.x:** older versions kept `config.json` and `.secrets.json` inside the skill
folder. Those files are still read. Move them to the new location with:

```
python3 scripts/configure.py migrate
```

Settings from older versions that no longer do anything (`mode`, `print_mode`, `email`,
`password`, `device_id`, certificate files) can be left in place or removed with
`configure.py unset <key>`.
