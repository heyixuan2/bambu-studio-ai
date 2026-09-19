"""The MakerWorld and Printables adapters, against recorded responses."""

import pytest
import requests

from bambu_studio_ai.search import ModelResult, SiteError, is_site_url, makerworld, printables
from bambu_studio_ai.search.parsing import text, utc_timestamp
from search_fakes import install, load


@pytest.fixture
def sites(monkeypatch):
    return install(monkeypatch)


def makerworld_fixture():
    return load("makerworld_phone_stand.json")


def printables_fixture():
    return load("printables_phone_stand.json")


# --- MakerWorld ----------------------------------------------------------------------

def test_makerworld_hit_maps_to_a_public_model_page():
    first = makerworld.parse_response(makerworld_fixture())[0]
    assert first == ModelResult(
        site="makerworld",
        id="1087279",
        title="Small smartphone stand - print in place design",  # double spaces collapsed
        url="https://makerworld.com/en/models/1087279-small-smartphone-stand-print-in-place-design",
        author="mgm86",
        license="Standard Digital File License",
        likes=20203,
        downloads=78580,
        prints=65802,
        published="2025-02-08T18:49:02Z",
        thumbnail="https://makerworld.bblmw.com/makerworld/model/US9ed59c39f449a5/design/03f80702c023e3a0.jpg",
    )


def test_makerworld_creative_commons_licence_is_spelled_like_printables():
    by_id = {r.id: r for r in makerworld.parse_response(makerworld_fixture())}
    assert by_id["127277"].license == "CC-BY-NC-SA"


def test_makerworld_request_is_one_get_with_an_honest_user_agent(sites):
    results = makerworld.search_makerworld("phone stand", limit=5, sort="downloads", timeout=10)
    assert len(results) == 5
    [(method, url, params, headers, timeout)] = sites.calls
    assert (method, url) == ("GET", makerworld.ENDPOINT)
    assert params == {"keyword": "phone stand", "limit": 5, "offset": 0, "orderBy": "downloadCount"}
    assert "github.com/heyixuan2/bambu-studio-ai" in headers["User-Agent"]
    assert timeout == 10


@pytest.mark.parametrize(("sort", "order_by"), [
    ("downloads", "downloadCount"), ("likes", "likeCount"),
    ("newest", "newUploads"), ("relevance", "score"),
])
def test_makerworld_sort_uses_the_services_own_ordering(sites, sort, order_by):
    makerworld.search_makerworld("vase", limit=3, sort=sort, timeout=10)
    assert sites.calls[0][2]["orderBy"] == order_by


def test_makerworld_skips_nsfw_and_malformed_hits():
    document = makerworld_fixture()
    document["hits"][0]["nsfw"] = True
    document["hits"][1]["id"] = "../../1"
    document["hits"][2]["title"] = None
    document["hits"].append("not an object")
    ids = [r.id for r in makerworld.parse_response(document)]
    assert ids == ["127277", "93143"]


def test_makerworld_slug_cannot_change_the_page_host():
    document = makerworld_fixture()
    document["hits"][0]["slug"] = "x/../../@evil.example?#"
    [first, *_] = makerworld.parse_response(document)
    assert is_site_url("makerworld", first.url)
    assert first.url.startswith("https://makerworld.com/en/models/1087279-x%2F..%2F..%2F%40evil.example")


def test_makerworld_blocked_keyword_is_a_site_failure():
    document = makerworld_fixture()
    document.update(keywordBlock=True, hits=[], blockedMessage="Sensitive keyword")
    with pytest.raises(SiteError, match="blocks this search term: Sensitive keyword"):
        makerworld.parse_response(document)


def test_makerworld_response_without_hits_is_a_site_failure():
    with pytest.raises(SiteError, match="unexpected response"):
        makerworld.parse_response({"code": 1, "error": "Internal error"})


# --- Printables ----------------------------------------------------------------------

def test_printables_item_maps_to_a_public_model_page():
    first = printables.parse_response(printables_fixture())[0]
    assert first == ModelResult(
        site="printables",
        id="187125",
        title="Phone Stand",
        url="https://www.printables.com/model/187125-phone-stand",
        author="PlatinumStars",
        license="CC-BY-NC",
        likes=11358,
        downloads=86047,
        prints=744,
        published="2025-06-03T07:38:44Z",
        thumbnail="https://media.printables.com/media/prints/187125/images/"
                  "1744516_d3dcf9f7-b0e5-4579-99f1-87e23bc610d6/img_5985.jpg",
    )


def test_printables_request_is_one_graphql_post(sites):
    printables.search_printables("phone stand", limit=4, sort="newest", timeout=7)
    [(method, url, payload, headers, timeout)] = sites.calls
    assert (method, url) == ("POST", "https://api.printables.com/graphql/")
    assert payload["variables"] == {"query": "phone stand", "limit": 4, "ordering": "latest"}
    assert "searchPrints2" in payload["query"]
    assert "$ordering: SearchChoicesEnum" in payload["query"]  # a String variable is rejected
    assert headers["Content-Type"] == "application/json"
    assert "bambu-studio-ai" in headers["User-Agent"]
    assert timeout == 7


def test_printables_graphql_error_is_a_site_failure_with_the_reason(sites):
    sites.printables = (400, load("printables_bad_ordering.json"))
    with pytest.raises(SiteError, match="rejected the query: Variable '\\$ordering'"):
        printables.search_printables("phone stand", limit=5, sort="downloads", timeout=10)


def test_printables_no_matches_is_an_empty_list_not_a_failure():
    assert printables.parse_response(load("printables_empty.json")) == []


def test_printables_answer_to_a_query_it_ignored_is_no_match(sites):
    # Recorded: for 花瓶 ("vase") Printables returned its most popular models.
    sites.printables = (200, load("printables_query_ignored.json"))
    assert printables.search_printables("花瓶", limit=5, sort="downloads", timeout=10) == []
    kept = printables.search_printables("playable ocarina", limit=5, sort="downloads", timeout=10)
    assert len(kept) == 5  # one title mentions the query, so the answer is trusted


@pytest.mark.parametrize("query", ["phone-stand", "Phone stand!", "a phone stand (v2)", "x"])
def test_printables_matches_are_kept_whatever_the_punctuation(sites, query):
    assert len(printables.search_printables(query, limit=5, sort="downloads", timeout=10)) == 5


def test_printables_licence_falls_back_to_its_full_name():
    document = printables_fixture()
    item = document["data"]["searchPrints2"]["items"][0]
    item["license"] = {"name": "Standard Digital File License", "abbreviation": None}
    item["image"] = None
    first = printables.parse_response(document)[0]
    assert first.license == "Standard Digital File License"
    assert first.thumbnail == ""


# --- Transport ----------------------------------------------------------------------

@pytest.mark.parametrize(("answer", "reason"), [
    (requests.Timeout("read timed out"), "no answer within 10 s"),
    (requests.ConnectionError("Name or service not known"), "could not connect"),
    ((503, {"message": "busy"}), "HTTP 503"),
    ((429, {"message": "slow down"}), "HTTP 429"),
    ((200, "<html>Just a moment...</html>"), "not JSON"),
])
def test_transport_failures_become_short_reasons(sites, answer, reason):
    sites.makerworld = answer
    sites.printables = answer
    for adapter in (makerworld.search_makerworld, printables.search_printables):
        with pytest.raises(SiteError, match=reason):
            adapter("phone stand", limit=5, sort="downloads", timeout=10)


# --- Validation and parsing helpers -------------------------------------------------

@pytest.mark.parametrize(("site", "url", "ok"), [
    ("makerworld", "https://makerworld.com/en/models/1-a", True),
    ("printables", "https://www.printables.com/model/1-a", True),
    ("printables", "https://printables.com/model/1-a", True),
    ("printables", "https://www.bing.com/aclick?ld=e8&u=aHR0cHM6Ly93d3cuYW1hem9uLmNvbQ", False),
    ("makerworld", "https://www.printables.com/model/1-a", False),
    ("makerworld", "http://makerworld.com/en/models/1-a", False),
    ("makerworld", "https://makerworld.com.evil.example/en/models/1", False),
    ("makerworld", "https://makerworld.com@evil.example/en/models/1", False),
    ("makerworld", "https://makerworld.com:8443/en/models/1", False),
    ("makerworld", "javascript:alert(1)", False),
])
def test_only_the_sites_own_https_pages_are_accepted(site, url, ok):
    assert is_site_url(site, url) is ok


def test_text_strips_terminal_escape_sequences():
    assert text("Nice\x1b[2J  stand\n\t v2") == "Nice[2J stand v2"


@pytest.mark.parametrize(("raw", "expected"), [
    ("2025-02-08T18:49:02Z", "2025-02-08T18:49:02Z"),
    ("2025-06-03T07:38:44.615430+00:00", "2025-06-03T07:38:44Z"),
    ("2025-06-03T09:38:44+02:00", "2025-06-03T07:38:44Z"),
    ("yesterday", ""),
    (None, ""),
])
def test_publication_times_are_normalised_to_utc(raw, expected):
    assert utc_timestamp(raw) == expected

