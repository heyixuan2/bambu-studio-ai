"""Smoke tests for search.py CLI."""

import json
import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "search.py")


def _run(args, expect_ok=True):
    r = subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True, text=True, timeout=30,
    )
    if expect_ok:
        assert r.returncode == 0, f"Exit {r.returncode}\nstderr: {r.stderr}\nstdout: {r.stdout}"
    return r


class TestHelp:
    def test_help(self):
        r = _run(["--help"])
        assert "search" in r.stdout.lower()


class TestDedup:
    def test_dedup_function(self):
        """Test the dedup function directly."""
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
        from search import _dedup_results

        results = [
            {"url": "https://makerworld.com/en/models/123", "name": "A", "source": "MW"},
            {"url": "https://makerworld.com/en/models/123?ref=thangs", "name": "A dup", "source": "Thangs"},
            {"url": "https://printables.com/model/456", "name": "B", "source": "Printables"},
        ]
        deduped = _dedup_results(results)
        assert len(deduped) == 2
        assert deduped[0]["name"] == "A"
        assert deduped[1]["name"] == "B"


_has_ddgs = True
try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        _has_ddgs = False

needs_ddgs = pytest.mark.skipif(not _has_ddgs, reason="ddgs/duckduckgo_search not installed")


@needs_ddgs
class TestJSONEmpty:
    def test_json_empty_returns_zero(self):
        """JSON mode should exit 0 even with no results (for scripting)."""
        r = _run(["xyznonexistent_query_42", "--json", "--limit", "1"])
        data = json.loads(r.stdout)
        assert isinstance(data, list)
