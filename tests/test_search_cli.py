"""search.py: the command agents run, replayed against recorded site responses."""

import json
import os
import subprocess
import sys

import pytest
import requests

import search as search_cli
from search_fakes import install, load

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "search.py")


@pytest.fixture
def sites(monkeypatch):
    return install(monkeypatch)


def run_json(capsys, *args):
    code = search_cli.main([*args, "--json"])
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_help_explains_that_limit_is_the_total():
    r = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True,
                       encoding="utf-8", timeout=30)
    assert r.returncode == 0
    assert "total number of results across all sites, not per site" in r.stdout
    assert "{all,makerworld,printables}" in r.stdout
    assert "thangs" not in r.stdout and "thingiverse" not in r.stdout


def test_human_output_lists_what_the_user_needs_to_choose(sites, capsys):
    assert search_cli.main(["phone stand", "--limit", "5"]) == 0
    out = capsys.readouterr().out
    assert "1. Phone Stand\n" in out
    assert "Printables · by PlatinumStars · 86,047 downloads · 11,358 likes · CC-BY-NC" in out
    assert "https://www.printables.com/model/187125-phone-stand" in out
    assert "MakerWorld · by mgm86 · 78,580 downloads · 20,203 likes · Standard Digital File License" in out
    assert " 5. " in out and " 6. " not in out
    assert out.rstrip().splitlines()[-1].startswith("➡️ Show the user these options")


def test_json_is_one_document_on_stdout(sites, capsys):
    code, data, err = run_json(capsys, "phone stand", "-l", "3")
    assert code == 0
    assert data["query"] == "phone stand"
    assert data["sort"] == "downloads"
    assert data["failed_sites"] == []
    assert [r["site"] for r in data["results"]] == ["printables", "makerworld", "makerworld"]
    assert data["results"][0]["url"] == "https://www.printables.com/model/187125-phone-stand"
    assert data["results"][0]["license"] == "CC-BY-NC"
    assert err == ""


def test_partial_failure_is_exit_0_and_reported(sites, capsys):
    sites.makerworld = (503, {})
    code, data, err = run_json(capsys, "phone stand")
    assert code == 0
    assert data["failed_sites"] == [{"site": "makerworld", "reason": "HTTP 503"}]
    assert {r["site"] for r in data["results"]} == {"printables"}
    assert "MakerWorld could not be searched: HTTP 503" in err


def test_every_site_failing_is_exit_1_with_a_json_document(sites, capsys):
    sites.makerworld = requests.ConnectionError("offline")
    sites.printables = requests.ConnectionError("offline")
    code, data, err = run_json(capsys, "phone stand")
    assert code == 1
    assert data["results"] == []
    assert [f["site"] for f in data["failed_sites"]] == ["makerworld", "printables"]
    assert "failed on every site" in err


def test_every_site_failing_in_human_mode_is_exit_1(sites, capsys):
    sites.printables = requests.Timeout("slow")
    assert search_cli.main(["phone stand", "--source", "printables"]) == 1
    captured = capsys.readouterr()
    assert "Printables could not be searched: no answer within 10 s" in captured.err
    assert "No models found" not in captured.out


def test_no_results_is_exit_0(sites, capsys):
    sites.printables = (200, load("printables_empty.json"))
    code, data, _ = run_json(capsys, "xyznonexistentqq42", "--source", "printables")
    assert code == 0
    assert data["results"] == []
    assert data["failed_sites"] == []
    assert search_cli.main(["xyznonexistentqq42", "-s", "printables"]) == 0
    assert "No models found" in capsys.readouterr().out


def test_source_and_sort_reach_the_site(sites, capsys):
    code, data, _ = run_json(capsys, "vase", "-s", "makerworld", "--sort", "newest")
    assert code == 0
    assert data["sites"] == ["makerworld"]
    assert sites.calls_to("POST") == []
    assert sites.calls_to("GET")[0][2]["orderBy"] == "newUploads"


@pytest.mark.parametrize("source", ["thingiverse", "thangs"])
def test_removed_sources_explain_why_and_exit_2(sites, capsys, source):
    assert search_cli.main(["vase", "--source", source]) == 2
    err = capsys.readouterr().err
    assert f"`--source {source}` was removed" in err
    assert "OAuth" in err
    assert sites.calls == []


@pytest.mark.parametrize("args", [["vase", "--limit", "0"], ["vase", "--limit", "51"],
                                  ["vase", "--sort", "rating"], ["vase", "-s", "cults3d"]])
def test_bad_arguments_exit_2(sites, capsys, args):
    with pytest.raises(SystemExit) as exit_info:
        search_cli.main(args)
    assert exit_info.value.code == 2
    assert sites.calls == []


def test_blank_query_exits_2(sites, capsys):
    assert search_cli.main(["   ", "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "query is empty" in captured.err
