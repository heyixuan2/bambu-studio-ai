# Example configuration

These files are examples only. Real settings live in `~/.bambu-studio-ai/` (override with
`BAMBU_STUDIO_AI_HOME`), outside the skill folder, so they survive skill updates.

Don't copy these by hand. Use the helper:

```bash
python3 scripts/configure.py set model A1 mode local printer_ip 192.168.1.100 serial 01P00A000000000
printf '%s' "$ACCESS_CODE" | python3 scripts/configure.py secret access_code
python3 scripts/configure.py show
```

See [references/setup.md](../references/setup.md) for all keys.
