"""Printables search through its public GraphQL API (the one printables.com itself uses).

No key is needed. The schema isn't published and introspection is off, so the query
below asks only for fields verified against the live API on 2026-09-19.
"""

from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote

from bambu_studio_ai.search import transport
from bambu_studio_ai.search.parsing import (
    count,
    mapping,
    mappings,
    model_id,
    page_url,
    text,
    utc_timestamp,
)
from bambu_studio_ai.search.schema import ModelResult, SortKey
from bambu_studio_ai.search.transport import SiteError

ENDPOINT = "https://api.printables.com/graphql/"  # the trailing slash is required
MODEL_PAGE = "https://www.printables.com/model/"
MEDIA = "https://media.printables.com/"

#: ``SearchChoicesEnum`` values. There is no download or like ordering, so both ask for
#: "popular" and the merged list is then sorted by the actual numbers.
ORDERING: dict[SortKey, str] = {
    "downloads": "popular",
    "likes": "popular",
    "newest": "latest",
    "relevance": "best_match",
}

QUERY = """
query SearchModels($query: String!, $limit: Int!, $ordering: SearchChoicesEnum) {
  searchPrints2(query: $query, printType: print, limit: $limit, ordering: $ordering) {
    items {
      id name slug nsfw likesCount downloadCount makesCount datePublished
      license { name abbreviation }
      user { publicUsername handle }
      image { filePath }
    }
  }
}
"""


def search_printables(
    query: str, *, limit: int, sort: SortKey, timeout: float
) -> list[ModelResult]:
    """Ask Printables for up to ``limit`` models matching ``query``, best first by ``sort``.

    Raises:
        SiteError: the API could not be reached or rejected the query.
    """
    payload = {
        "operationName": "SearchModels",
        "query": QUERY,
        "variables": {"query": query, "limit": limit, "ordering": ORDERING[sort]},
    }
    document = transport.post_json(ENDPOINT, payload=payload, timeout=timeout)
    results = parse_response(document)[:limit]
    # Printables drops words its index can't match (e.g. the two-character Chinese
    # word 花瓶, "vase") and then returns its whole catalogue, most popular first
    # (seen 2026-09-19). Those would outrank every real match, so if no result even
    # mentions the query, treat it as no match.
    return results if mentions_query(query, results) else []


def mentions_query(query: str, results: list[ModelResult]) -> bool:
    """Whether any result's title or page URL contains a word of ``query``."""
    words = query.casefold().split()
    pages = [f"{result.title} {result.url}".casefold() for result in results]
    return any(word in page for word in words for page in pages)


def parse_response(document: object) -> list[ModelResult]:
    """Turn a ``searchPrints2`` response into results, skipping models flagged NSFW.

    Raises:
        SiteError: the response carries GraphQL errors or no search data.
    """
    body = mapping(document)
    errors = mappings(body.get("errors"))
    if errors:
        raise SiteError(f"Printables rejected the query: {text(errors[0].get('message'))[:200]}")
    found = mapping(mapping(body.get("data")).get("searchPrints2"))
    if "items" not in found:
        raise SiteError("unexpected response from Printables (no search items)")
    items = (item for item in mappings(found.get("items")) if item.get("nsfw") is not True)
    return [result for result in map(_to_result, items) if result is not None]


def _to_result(item: Mapping[str, object]) -> ModelResult | None:
    identifier = model_id(item.get("id"))
    title = text(item.get("name"))
    if not identifier or not title:
        return None
    user = mapping(item.get("user"))
    licence = mapping(item.get("license"))
    return ModelResult(
        site="printables",
        id=identifier,
        title=title,
        url=page_url(MODEL_PAGE, identifier, item.get("slug")),
        author=text(user.get("publicUsername")) or text(user.get("handle")),
        license=text(licence.get("abbreviation")) or text(licence.get("name")),
        likes=count(item.get("likesCount")),
        downloads=count(item.get("downloadCount")),
        prints=count(item.get("makesCount")),
        published=utc_timestamp(item.get("datePublished")),
        thumbnail=_thumbnail(mapping(item.get("image")).get("filePath")),
    )


def _thumbnail(file_path: object) -> str:
    path = text(file_path).lstrip("/")
    return MEDIA + quote(path) if path else ""
