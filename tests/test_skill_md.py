"""SKILL.md must stay valid under the Agent Skills spec (agentskills.io/specification)
so every compatible agent can load it, and every file it points to must exist."""

import os
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_MD = os.path.join(ROOT, "SKILL.md")
ALLOWED_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def _split():
    text = open(SKILL_MD, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    assert m, "SKILL.md must start with YAML frontmatter"
    return yaml.safe_load(m.group(1)), m.group(2)


def test_frontmatter_is_spec_compliant():
    fm, _ = _split()
    assert set(fm) <= ALLOWED_KEYS, f"non-spec keys: {set(fm) - ALLOWED_KEYS}"
    name = fm["name"]
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64
    assert name == "bambu-studio-ai"
    assert 0 < len(fm["description"]) <= 1024
    assert len(fm.get("compatibility", "")) <= 500
    meta = fm.get("metadata", {})
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in meta.items()), \
        "metadata must be a flat string→string map"


def test_version_in_sync():
    import common
    fm, _ = _split()
    pyproject = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    assert fm["metadata"]["version"] == common.__version__
    assert f'version = "{common.__version__}"' in pyproject


def test_body_fits_progressive_disclosure_budget():
    _, body = _split()
    assert len(body.splitlines()) < 500


@pytest.mark.parametrize("doc", ["SKILL.md"] + [
    os.path.join("references", f) for f in sorted(os.listdir(os.path.join(ROOT, "references")))
    if f.endswith(".md")
])
def test_relative_links_resolve(doc):
    path = os.path.join(ROOT, doc)
    text = open(path, encoding="utf-8").read()
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
        if re.match(r"[a-z]+://", target):
            continue
        resolved = os.path.normpath(os.path.join(os.path.dirname(path), target))
        assert os.path.exists(resolved), f"{doc}: broken link {target}"


def test_scripts_mentioned_in_skill_md_exist():
    _, body = _split()
    for script in set(re.findall(r"scripts/([\w./-]+?\.py)\b", body)):
        assert os.path.exists(os.path.join(ROOT, "scripts", script)), f"missing scripts/{script}"
    assert os.path.exists(os.path.join(ROOT, "scripts", "colorize", "__main__.py"))


def test_no_platform_specific_leftovers():
    _, body = _split()
    for word in ("openclaw", "clawhub", "heartbeat", "open -a", "osascript"):
        assert word not in body.lower(), f"agent/OS-specific leftover in SKILL.md: {word}"
