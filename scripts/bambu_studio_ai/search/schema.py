"""One result shape for every model site, and the rule for which URLs a site may return."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

Site = Literal["makerworld", "printables"]
SortKey = Literal["downloads", "likes", "newest", "relevance"]

SITES: tuple[Site, ...] = ("makerworld", "printables")
SORT_KEYS: tuple[SortKey, ...] = ("downloads", "likes", "newest", "relevance")
SITE_NAMES: dict[Site, str] = {"makerworld": "MakerWorld", "printables": "Printables"}

#: Hosts a result's model page may live on. Anything else is dropped, so an ad or a
#: redirect can never be shown to the user as a model from one of these sites.
SITE_HOSTS: dict[Site, frozenset[str]] = {
    "makerworld": frozenset({"makerworld.com"}),
    "printables": frozenset({"www.printables.com", "printables.com"}),
}


@dataclass(frozen=True)
class ModelResult:
    """A model found on one site, with the numbers people use to choose between them."""

    site: Site
    id: str
    """The site's own model id (digits)."""
    title: str
    url: str
    """Public model page, always on one of :data:`SITE_HOSTS` for ``site``."""
    author: str
    license: str
    """Short licence name, e.g. ``"CC-BY-NC-SA"`` or ``"Standard Digital File License"``;
    empty when the site gives none."""
    likes: int | None
    downloads: int | None
    prints: int | None
    """Prints reported on MakerWorld, or makes posted on Printables."""
    published: str
    """First publication time as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC), or empty."""
    thumbnail: str
    """Cover image URL, or empty."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


@dataclass(frozen=True)
class SiteFailure:
    """A site that could not be searched, and why."""

    site: Site
    reason: str


@dataclass(frozen=True)
class SearchReport:
    """What one search found, and which sites could not be asked."""

    results: tuple[ModelResult, ...]
    failed_sites: tuple[SiteFailure, ...]
    sites: tuple[Site, ...] = SITES
    """The sites that were searched (including the failed ones)."""

    @property
    def all_failed(self) -> bool:
        """True when no site answered, so an empty result says nothing about the query."""
        return len(self.failed_sites) == len(self.sites)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "sites": list(self.sites),
            "results": [result.to_dict() for result in self.results],
            "failed_sites": [asdict(failure) for failure in self.failed_sites],
        }


def is_site_url(site: Site, url: str) -> bool:
    """Whether ``url`` is an https page on one of ``site``'s own hosts (default port)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.hostname in SITE_HOSTS[site]
        and port is None
        and parts.username is None
    )
