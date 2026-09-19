"""Search every enabled site at once and merge the answers into one ranked list."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Protocol

from bambu_studio_ai.search import makerworld, printables
from bambu_studio_ai.search.schema import (
    SITE_NAMES,
    SITES,
    SORT_KEYS,
    ModelResult,
    SearchReport,
    Site,
    SiteFailure,
    SortKey,
    is_site_url,
)
from bambu_studio_ai.search.transport import SiteError

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 5
MAX_LIMIT = 50
DEFAULT_TIMEOUT_S = 10.0


class SiteSearch(Protocol):
    """One site's adapter: returns up to ``limit`` results, best first, or raises SiteError."""

    def __call__(
        self, query: str, *, limit: int, sort: SortKey, timeout: float
    ) -> list[ModelResult]:
        """Search the site."""
        ...


ADAPTERS: dict[Site, SiteSearch] = {
    "makerworld": makerworld.search_makerworld,
    "printables": printables.search_printables,
}

_SORT_VALUE: dict[SortKey, Callable[[ModelResult], tuple[int | str, ...]]] = {
    "downloads": lambda r: (_number(r.downloads), _number(r.likes)),
    "likes": lambda r: (_number(r.likes), _number(r.downloads)),
    "newest": lambda r: (r.published,),
}


def search(
    query: str,
    *,
    sites: Sequence[Site] = SITES,
    limit: int = DEFAULT_LIMIT,
    sort: SortKey = "downloads",
    timeout: float = DEFAULT_TIMEOUT_S,
) -> SearchReport:
    """Search ``sites`` in parallel and return the best ``limit`` models overall.

    Each site is asked once for ``limit`` results and gets ``timeout`` seconds to
    answer. A site that fails or times out is listed in ``failed_sites`` and the others
    are still returned. Results whose page is not on the site's own domain are dropped.

    Args:
        query: What to look for, e.g. ``"phone stand"``.
        sites: Which sites to ask, from :data:`SITES`.
        limit: Total number of results to return (1 to :data:`MAX_LIMIT`).
        sort: ``downloads``, ``likes`` or ``newest`` sort the merged list by that
            number; ``relevance`` keeps each site's own order and alternates between
            sites, because the sites' relevance scores can't be compared.
        timeout: Seconds each site gets to answer.

    Raises:
        ValueError: the query is empty, or a site, sort or limit is not supported.
    """
    query = " ".join(query.split())
    chosen = tuple(dict.fromkeys(sites))
    unknown = [site for site in chosen if site not in SITES]
    if not query:
        raise ValueError("the search query is empty")
    if not chosen or unknown:
        raise ValueError(f"sites must be chosen from {', '.join(SITES)}")
    if sort not in SORT_KEYS:
        raise ValueError(f"sort must be one of {', '.join(SORT_KEYS)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")

    found, failures = _ask_sites(query, chosen, limit=limit, sort=sort, timeout=timeout)
    ranked = _dedupe(_rank(found, sort))
    return SearchReport(results=tuple(ranked[:limit]), failed_sites=failures, sites=chosen)


def _ask_sites(
    query: str, sites: tuple[Site, ...], *, limit: int, sort: SortKey, timeout: float
) -> tuple[dict[Site, list[ModelResult]], tuple[SiteFailure, ...]]:
    executor = ThreadPoolExecutor(max_workers=len(sites), thread_name_prefix="model-search")
    try:
        futures: dict[Site, Future[list[ModelResult]]] = {
            site: executor.submit(ADAPTERS[site], query, limit=limit, sort=sort, timeout=timeout)
            for site in sites
        }
        done, _ = wait(futures.values(), timeout=timeout)
    finally:
        # Don't wait for a site that is still talking: its own request timeout ends it.
        executor.shutdown(wait=False, cancel_futures=True)

    found: dict[Site, list[ModelResult]] = {}
    failures: list[SiteFailure] = []
    for site, future in futures.items():
        if future not in done:
            failures.append(SiteFailure(site, f"no answer within {timeout:g} s"))
            continue
        outcome = _outcome(site, future)
        if isinstance(outcome, SiteFailure):
            failures.append(outcome)
        else:
            found[site] = _on_site(site, outcome)[:limit]
    return found, tuple(failures)


def _outcome(site: Site, future: Future[list[ModelResult]]) -> list[ModelResult] | SiteFailure:
    try:
        return future.result()
    except SiteError as exc:
        return SiteFailure(site, str(exc))
    except Exception as exc:
        # A bug in one adapter must not hide the other site's results; log it in full.
        logger.exception("%s search failed unexpectedly", SITE_NAMES[site])
        return SiteFailure(site, f"unexpected error ({type(exc).__name__})")


def _on_site(site: Site, results: Iterable[ModelResult]) -> list[ModelResult]:
    kept: list[ModelResult] = []
    for result in results:
        if result.site == site and is_site_url(site, result.url):
            kept.append(result)
        else:
            logger.warning("dropped a %s result not hosted there: %s", SITE_NAMES[site], result.url)
    return kept


def _rank(found: Mapping[Site, list[ModelResult]], sort: SortKey) -> list[ModelResult]:
    if sort == "relevance":
        longest = max((len(results) for results in found.values()), default=0)
        return [
            results[rank]
            for rank in range(longest)
            for results in found.values()
            if rank < len(results)
        ]
    merged = [result for results in found.values() for result in results]
    return sorted(merged, key=_SORT_VALUE[sort], reverse=True)


def _dedupe(results: Iterable[ModelResult]) -> list[ModelResult]:
    seen: set[tuple[str, str]] = set()
    unique: list[ModelResult] = []
    for result in results:
        key = (result.site, result.id)
        if key not in seen:
            seen.add(key)
            unique.append(result)
    return unique


def _number(value: int | None) -> int:
    return -1 if value is None else value
