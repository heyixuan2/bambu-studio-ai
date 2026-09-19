"""references/model-specs.md shows the same numbers as assets/*.json."""

from datagen import model_specs


def test_generated_tables_are_present():
    text = model_specs.MODEL_SPECS.read_text(encoding="utf-8")
    for name in model_specs.TABLES:
        assert f"<!-- generated:{name} " in text and f"<!-- /generated:{name} -->" in text


def test_model_specs_matches_the_json():
    text = model_specs.MODEL_SPECS.read_text(encoding="utf-8")
    assert model_specs.render(text) == text, "run: python3 tests/datagen/model_specs.py --write"


def test_render_replaces_only_the_generated_block():
    stale = "intro\n<!-- generated:printers (x) -->\n| old |\n<!-- /generated:printers -->\noutro\n"
    fresh = model_specs.render(stale)
    assert fresh.startswith("intro\n<!-- generated:printers (x) -->\n| Model |")
    assert fresh.endswith("<!-- /generated:printers -->\noutro\n")
    assert "| old |" not in fresh
    assert "| H2D Pro | 350 × 320 × 325 |" in fresh
