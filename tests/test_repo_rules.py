"""Repository rules from docs/CONVENTIONS.md that a test can enforce."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_LINES = 400

# Files written before the 400-line rule, with the size they may not grow past.
# Shrink an entry when you split a file; delete it once the file is under the limit.
LEGACY_LIMITS = {
    "scripts/generate.py": 1235,
    "scripts/analyze.py": 866,
    "scripts/slice.py": 584,
    "scripts/preview.py": 457,
    "scripts/parametric.py": 453,
}


def _python_files():
    for folder in ("scripts", "tests"):
        yield from (ROOT / folder).rglob("*.py")


def test_python_files_stay_under_400_lines():
    too_long = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > LEGACY_LIMITS.get(rel, MAX_LINES):
            too_long.append(f"{rel}: {lines} lines (limit {LEGACY_LIMITS.get(rel, MAX_LINES)})")
    assert not too_long, "Split these files by responsibility:\n" + "\n".join(too_long)


def test_legacy_allowlist_only_shrinks():
    stale = []
    for rel, limit in LEGACY_LIMITS.items():
        path = ROOT / rel
        if not path.exists():
            stale.append(f"{rel}: file is gone, remove it from LEGACY_LIMITS")
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines <= MAX_LINES:
            stale.append(f"{rel}: now {lines} lines, remove it from LEGACY_LIMITS")
        elif lines < limit:
            stale.append(f"{rel}: now {lines} lines, lower its limit from {limit} to {lines}")
    assert not stale, "\n".join(stale)


def test_text_files_are_opened_as_utf8():
    """open() without encoding uses the ANSI code page on Windows and breaks on the first '→'.

    Ruff's unspecified-encoding rule is still a preview rule, so it runs here rather than in
    the main lint config.
    """
    import shutil
    import subprocess
    import sys

    ruff = shutil.which("ruff") or str(Path(sys.executable).with_name("ruff"))
    result = subprocess.run(
        [ruff, "check", "--preview", "--select", "PLW1514", "--output-format", "concise", "scripts", "tests"],
        cwd=ROOT, capture_output=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, "Pass encoding='utf-8' to these calls:\n" + result.stdout
