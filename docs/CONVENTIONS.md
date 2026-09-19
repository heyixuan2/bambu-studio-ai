# Engineering conventions

These rules are what "senior-quality code" means in this repo. Every rule here is either enforced
by a CI gate or checked in code review; a rule that can't be checked doesn't belong in this file.

## 1. Layout

```
bambu-studio-ai/                 ← the repo root IS the skill (SKILL.md must stay here)
├── SKILL.md                     Agent playbook (≤ 300 lines). No implementation detail.
├── references/                  Loaded on demand by agents. Facts, procedures, formats.
├── assets/                      Data files agents/scripts read (printers.json, filament palette).
├── scripts/
│   ├── bambu_studio_ai/         The library. All logic lives here. Importable, typed, tested.
│   │   ├── cli/                 argparse wiring per command; no business logic
│   │   ├── generation/          providers/, download.py, postprocess.py
│   │   ├── mesh/                analyze.py, repair.py, orient.py, units.py, io.py
│   │   ├── cad/                 parametric helpers, CSG, code-CAD runner (build123d / manifold3d)
│   │   ├── color/               texture → palette → segmentation → export
│   │   ├── render/              previews (Blender backend + headless fallback)
│   │   ├── printer/             Bambu LAN read-only client, printer/AMS registry
│   │   ├── monitor/             print monitoring state machine
│   │   ├── search/              per-site adapters → common schema
│   │   ├── config.py            paths, settings, secrets (single source of truth)
│   │   └── _version.py
│   └── analyze.py, generate.py, …   Thin shims (≤ 15 lines): one sys.path insert, call main()
├── tests/                       pytest; unit + golden-file + CLI contract tests
├── evals/                       agent-behaviour evals (prompts + assertions), run in CI
└── docs/                        human docs (this file, ROADMAP, CHANGELOG, assets for README)
```

Why the package lives inside `scripts/`: agents run `python3 <skill>/scripts/analyze.py` by path with
no install step, and `npx skills add` copies the folder that contains `SKILL.md`. So the importable
code must ship next to the shims, and `SKILL.md` must stay at the repo root (a nested `SKILL.md`
breaks `git clone … ~/.claude/skills/bambu-studio-ai` and the Claude.ai zip upload). `pip install .`
still works for contributors (`pyproject` points `package-dir` at `scripts/`) and gives a `bsa`
console script. Each shim adds its own directory to `sys.path` in one line and calls `main()`.
Nothing else in the repo touches `sys.path`. Nothing that isn't needed at run time (dev notes,
example configs) lives in the repo root tree, because everything in it ships.

## 2. Python

- **Version:** 3.10+ (set by `bambulabs-api`). `from __future__ import annotations` in every module.
- **Formatting:** `ruff format`, line length 100. No manual alignment.
- **Linting:** `ruff check` with the full rule set in `pyproject.toml` (`E, W, F, I, N, UP, B, S,
  C4, SIM, RUF, ANN, D`), not the four error-only rules used today. Enforced on
  `scripts/bambu_studio_ai/` from day one; legacy scripts stay on the old rules until they are
  migrated (an explicit allowlist that only shrinks).
- **Types:** every public function and method is fully annotated. `pyright --strict` on `scripts/bambu_studio_ai/`.
  `Any` needs a comment saying why.
- **File size:** no source file over **400 lines** (`scripts/`, `tests/`). A file that grows past it
  is two responsibilities sharing a name; split it. Enforced by `tests/test_repo_rules.py`, with a
  legacy allowlist that only shrinks.
- **Docstrings:** one-line summary on every public module, class and function; Google style for
  anything with parameters an agent or contributor needs to understand. Don't restate the signature.
- **Naming:** PEP 8 throughout. Modules and functions `snake_case`, classes `CapWords`, constants
  `UPPER_SNAKE`. No abbreviations that aren't universal (`cfg` no, `config` yes; `mm` fine).
  Private helpers start with `_`. No `_tj`, `_nt`, `_sj`-style aliasing of stdlib modules.
- **Imports:** stdlib / third-party / first-party groups, one import per line, sorted by ruff.
  No imports inside functions except to make an optional dependency optional, and then the
  `ImportError` handler must produce an actionable message.

## 3. Behaviour rules (the ones that bit us)

- **No work at import time.** No config reads, no `os.makedirs`, no network, no `sys.exit` in
  module scope. Modules expose functions; `main()` does the work.
- **No subprocess calls to sibling scripts.** `monitor.py` shelling out to `bambu.py status` is
  the anti-pattern. Import the function.
- **Optional dependencies are optional.** Blender, Bambu Studio, pymeshlab, an AI
  provider key: their absence degrades one feature with a clear message and never breaks another.
- **Every external call has a timeout.** HTTP, MQTT connect, subprocesses, Blender.
- **No swallowed exceptions.** `except Exception: pass` is banned (ruff `S110`/`BLE001`). Catch
  what you expect, log the rest with context, re-raise or return a typed failure.
- **Pure functions for logic, thin I/O at the edges.** Analysis, colour maths, prompt building,
  profile resolution: pure, unit-tested, no printing. Printing and file writing happen in the CLI
  layer.
- **Secrets never touch argv or logs.** Read from stdin, env, or the secrets file. Mask in output.

## 4. CLI contract (what agents depend on)

- One style: `kebab-case` flags (`--max-colors`, not `--max_colors`). Subcommands where a tool has
  more than one verb (`bambu status`, `generate text`). `--help` on everything, including the
  top level, and it must print help, not run.
- `--json` on every command that produces data. When `--json` is set, **stdout is exactly one JSON
  document** and every human message goes to stderr. Schemas are documented in
  `references/cli-reference.md` and covered by contract tests.
- Exit codes: `0` success · `1` operation failed · `2` bad arguments / missing configuration ·
  `3` optional dependency missing. Never `sys.exit()` inside library code.
- Output files: written next to the input unless `-o` is given; suffixes are a fixed vocabulary
  (`_scaled`, `_oriented`, `_repaired`, `_multicolor`, `_preview`) and every command that writes
  files ends with a machine-readable `output_file` (in `--json`) and a `➡️ Use this file:` line
  (human mode). Downloads, snapshots and logs go to the output dir (`BAMBU_OUTPUT_DIR`, default
  `./bambu-output/`).
- Human output is for humans: short, no walls of emoji. One emoji per line at most, and only in the
  CLI layer. Library code uses `logging`.

## 5. Tests

- Behaviour over smoke. A `--help` test is fine; it doesn't count as coverage of the command.
- Every bug fix ships with a regression test named after the bug.
- Geometry tests assert numbers (extents, volume, body count), not "file exists".
- No live network in unit tests. Provider backends are tested against recorded responses
  (`tests/fixtures/providers/*.json`); one opt-in `@pytest.mark.live` suite runs with real keys.
- Golden files for CLI `--json` output schemas.
- Agent evals (`evals/`) run against SKILL.md changes: realistic prompts, assertions on the files
  produced and the steps taken.

## 6. Docs

- `SKILL.md` describes *when and why*; `references/` describes *how*; code comments describe
  *why this way*. Nothing is documented twice.
- Every command line in the docs is checked against `--help` by a test. Every relative link is
  checked by a test. (Both exist today; keep them green.)
- Version lives in exactly one place (`scripts/bambu_studio_ai/_version.py`) and is propagated by a
  script; the test suite asserts they match.

## 7. Git

- Commit early and often: one logical change per commit, never a day's work in one blob. During a
  refactor, commit after each module lands green so any step can be reverted alone.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`), body
  says why. Squash noise before merging.
- `CHANGELOG.md` in Keep-a-Changelog format, updated in the same PR as the change.
- Tag every release (`vX.Y.Z`) and publish GitHub release notes. The skill's `metadata.version`
  matches the tag.
