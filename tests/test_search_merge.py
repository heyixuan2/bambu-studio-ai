"""search(): both sites in parallel, merged, de-duplicated, sorted, and failure-tolerant."""

import dataclasses
import threading

import pytest
import requests

from bambu_studio_ai.search import SiteError, SiteFailure, core, search
from search_fakes import install, load


@pytest.fixture
def sites(monkeypatch):
    return install(monkeypatch)


def summary(report):
    return [(r.site, r.id) for r in report.results]


def test_default_search_merges_both_sites_by_downloads(sites):
    report = search("phone stand")
    assert [r.downloads for r in report.results] == [86047, 78580, 78151, 67567, 62229]
    assert summary(report)[:2] == [("printables", "187125"), ("makerworld", "1087279")]
    assert report.failed_sites == ()
    assert len(sites.calls_to("GET")) == 1  # MakerWorld: one request per search
    assert len(sites.calls_to("POST")) == 1


def test_limit_is_the_total_across_sites(sites):
    report = search("phone stand", limit=3)
    assert len(report.results) == 3
    assert sites.calls_to("GET")[0][2]["limit"] == 3
    assert sites.calls_to("POST")[0][2]["variables"]["limit"] == 3


def test_more_than_either_site_alone_when_the_limit_allows(sites):
    report = search("phone stand", limit=10)
    assert len(report.results) == 10
    assert {r.site for r in report.results} == {"makerworld", "printables"}


def test_sort_by_likes(sites):
    likes = [r.likes for r in search("phone stand", sort="likes", limit=10).results]
    assert likes == sorted(likes, reverse=True)
    assert likes[0] == 20203


def test_sort_by_newest(sites):
    dates = [r.published for r in search("phone stand", sort="newest", limit=10).results]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-02-04T18:16:56Z"  # Printables "Geared Phone stand"


def test_relevance_keeps_each_sites_order_and_alternates(sites):
    report = search("phone stand", sort="relevance", limit=6)
    assert summary(report) == [
        ("makerworld", "1087279"), ("printables", "187125"),
        ("makerworld", "819327"), ("printables", "1161"),
        ("makerworld", "231863"), ("printables", "1202776"),
    ]
    assert sites.calls_to("GET")[0][2]["orderBy"] == "score"
    assert sites.calls_to("POST")[0][2]["variables"]["ordering"] == "best_match"


def test_one_site_only(sites):
    report = search("phone stand", sites=["printables"])
    assert {r.site for r in report.results} == {"printables"}
    assert sites.calls_to("GET") == []
    assert report.sites == ("printables",)


def test_same_model_returned_twice_is_listed_once(sites):
    document = load("makerworld_phone_stand.json")
    document["hits"].insert(1, dict(document["hits"][0]))
    sites.makerworld = (200, document)
    report = search("phone stand", sites=["makerworld"], limit=10)
    assert [r.id for r in report.results].count("1087279") == 1


def test_results_not_hosted_on_the_claimed_site_are_dropped(sites, monkeypatch):
    real = core.ADAPTERS["printables"]

    def with_an_ad(query, *, limit, sort, timeout):
        results = real(query, limit=limit, sort=sort, timeout=timeout)
        ad = dataclasses.replace(results[0], id="999", url="https://www.bing.com/aclick?u=amazon")
        stolen = dataclasses.replace(results[1], id="998", site="makerworld")
        return [ad, stolen, *results]

    monkeypatch.setitem(core.ADAPTERS, "printables", with_an_ad)
    report = search("phone stand", limit=20)
    urls = [r.url for r in report.results]
    assert not any("bing.com" in url for url in urls)
    assert {r.id for r in report.results}.isdisjoint({"999", "998"})
    assert len(report.results) == 10  # 5 + 5 genuine results survive
    # Checked before the per-site cut, so bad entries don't take a genuine result's place.
    only_printables = search("phone stand", sites=["printables"], limit=5)
    assert [r.id for r in only_printables.results] == ["187125", "1161", "1202776", "770146", "582465"]


def test_one_site_failing_leaves_the_other(sites):
    sites.printables = requests.Timeout("read timed out")
    report = search("phone stand")
    assert report.failed_sites == (SiteFailure("printables", "no answer within 10 s"),)
    assert {r.site for r in report.results} == {"makerworld"}
    assert len(report.results) == 5
    assert not report.all_failed


def test_every_site_failing_is_reported(sites):
    sites.makerworld = (503, {})
    sites.printables = requests.ConnectionError("offline")
    report = search("phone stand")
    assert report.results == ()
    assert [f.site for f in report.failed_sites] == ["makerworld", "printables"]
    assert report.failed_sites[0].reason == "HTTP 503"
    assert report.all_failed


def test_no_matches_is_not_a_failure(sites):
    sites.printables = (200, load("printables_empty.json"))
    report = search("xyznonexistentqq42", sites=["printables"])
    assert report.results == ()
    assert report.failed_sites == ()
    assert not report.all_failed


def test_popular_models_for_an_ignored_query_do_not_outrank_real_matches(sites):
    sites.printables = (200, load("printables_query_ignored.json"))  # DUMMY 13: 221,981 downloads
    report = search("花瓶")
    assert {r.site for r in report.results} == {"makerworld"}
    assert report.failed_sites == ()


def test_a_site_that_hangs_is_given_up_on_after_the_timeout(sites, monkeypatch):
    release = threading.Event()

    def hangs(query, *, limit, sort, timeout):
        release.wait(5)
        return []

    monkeypatch.setitem(core.ADAPTERS, "printables", hangs)
    try:
        report = search("phone stand", timeout=0.2)
    finally:
        release.set()
    assert report.failed_sites == (SiteFailure("printables", "no answer within 0.2 s"),)
    assert len(report.results) == 5


def test_a_bug_in_one_adapter_does_not_hide_the_other_site(sites, monkeypatch, caplog):
    def broken(query, *, limit, sort, timeout):
        raise KeyError("items")

    monkeypatch.setitem(core.ADAPTERS, "makerworld", broken)
    report = search("phone stand")
    assert report.failed_sites == (SiteFailure("makerworld", "unexpected error (KeyError)"),)
    assert {r.site for r in report.results} == {"printables"}
    assert "MakerWorld search failed unexpectedly" in caplog.text


def test_site_errors_carry_their_reason(sites, monkeypatch):
    def refuses(query, *, limit, sort, timeout):
        raise SiteError("MakerWorld blocks this search term")

    monkeypatch.setitem(core.ADAPTERS, "makerworld", refuses)
    report = search("phone stand")
    assert report.failed_sites[0].reason == "MakerWorld blocks this search term"


def test_report_to_dict_is_json_ready(sites):
    data = search("phone stand", limit=2).to_dict()
    assert data["sites"] == ["makerworld", "printables"]
    assert data["failed_sites"] == []
    assert set(data["results"][0]) == {
        "site", "id", "title", "url", "author", "license",
        "likes", "downloads", "prints", "published", "thumbnail",
    }


@pytest.mark.parametrize("kwargs", [
    {"query": "   "},
    {"query": "vase", "limit": 0},
    {"query": "vase", "limit": 51},
    {"query": "vase", "sites": ["thingiverse"]},
    {"query": "vase", "sites": []},
    {"query": "vase", "sort": "rating"},
])
def test_bad_arguments_are_rejected_before_any_request(sites, kwargs):
    with pytest.raises(ValueError):
        search(**kwargs)
    assert sites.calls == []
