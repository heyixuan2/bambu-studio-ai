"""MakerWorld search through Bambu Lab's own search service.

This is the endpoint MakerWorld's website and app search with. It answers without a
login but is undocumented, so it can change without notice; Printables is searched
alongside so model search survives if it does. The skill uses it read-only and
sparingly: one request per search, no paging, no retries, and never for downloads,
which need a Bambu Lab login and stay with the user (see ``references/security.md``).
"""

from __future__ import annotations

from collections.abc import Mapping

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

ENDPOINT = "https://api.bambulab.com/v1/search-service/select/design2"
MODEL_PAGE = "https://makerworld.com/en/models/"

#: The service's own ``orderBy`` values. ``hotScore`` (trending) exists too.
ORDER_BY: dict[SortKey, str] = {
    "downloads": "downloadCount",
    "likes": "likeCount",
    "newest": "newUploads",
    "relevance": "score",
}


def search_makerworld(
    query: str, *, limit: int, sort: SortKey, timeout: float
) -> list[ModelResult]:
    """Ask MakerWorld for up to ``limit`` models matching ``query``, best first by ``sort``.

    Raises:
        SiteError: the service could not be reached, refused the query, or answered
            with something that isn't a search result.
    """
    params = {"keyword": query, "limit": limit, "offset": 0, "orderBy": ORDER_BY[sort]}
    document = transport.get_json(ENDPOINT, params=params, timeout=timeout)
    return parse_response(document)[:limit]


def parse_response(document: object) -> list[ModelResult]:
    """Turn a ``design2`` search response into results, skipping hits flagged NSFW.

    Raises:
        SiteError: the response has no hit list, or the keyword was blocked.
    """
    body = mapping(document)
    if body.get("keywordBlock") is True:
        detail = text(body.get("blockedMessage"))
        raise SiteError("MakerWorld blocks this search term" + (f": {detail}" if detail else ""))
    if "hits" not in body:
        raise SiteError("unexpected response from MakerWorld (no search hits)")
    hits = (hit for hit in mappings(body.get("hits")) if hit.get("nsfw") is not True)
    return [result for result in map(_to_result, hits) if result is not None]


def _to_result(hit: Mapping[str, object]) -> ModelResult | None:
    identifier = model_id(hit.get("id"))
    title = text(hit.get("title"))
    if not identifier or not title:
        return None
    creator = mapping(hit.get("designCreator"))
    cover = text(hit.get("cover"))
    return ModelResult(
        site="makerworld",
        id=identifier,
        title=title,
        url=page_url(MODEL_PAGE, identifier, hit.get("slug")),
        author=text(creator.get("name")) or text(creator.get("handle")),
        license=_license(hit.get("license")),
        likes=count(hit.get("likeCount")),
        downloads=count(hit.get("downloadCount")),
        prints=count(hit.get("printCount")),
        published=utc_timestamp(hit.get("createTime")),
        thumbnail=cover if cover.startswith("https://") else "",
    )


def _license(value: object) -> str:
    # MakerWorld writes Creative Commons licences without the "CC" ("BY-NC-SA");
    # Printables writes "CC-BY-NC-SA". Use one spelling so they read the same.
    name = text(value)
    return f"CC-{name}" if name.startswith("BY") else name
