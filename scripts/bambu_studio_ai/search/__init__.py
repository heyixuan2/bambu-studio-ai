"""Search MakerWorld and Printables for ready-made 3D models.

Both sites are asked in parallel through their own public search APIs; results come
back in one shape (:class:`ModelResult`) with licence and popularity numbers, so an
agent can show the user real options. Only the query text is sent. Nothing is
downloaded: the user opens the link and downloads from the site.
"""

from bambu_studio_ai.search.core import DEFAULT_LIMIT, DEFAULT_TIMEOUT_S, MAX_LIMIT, search
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
from bambu_studio_ai.search.transport import USER_AGENT, SiteError

__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_TIMEOUT_S",
    "MAX_LIMIT",
    "SITES",
    "SITE_NAMES",
    "SORT_KEYS",
    "USER_AGENT",
    "ModelResult",
    "SearchReport",
    "Site",
    "SiteError",
    "SiteFailure",
    "SortKey",
    "is_site_url",
    "search",
]
