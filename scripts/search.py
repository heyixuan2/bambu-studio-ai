#!/usr/bin/env python3
"""
Search MakerWorld and Printables for ready-made 3D models.

Both sites are searched in parallel through their own public search APIs, and the
results come with author, licence, downloads and likes. Only the query text is sent;
nothing is downloaded (the user opens the link and downloads from the site).

Usage:
  python3 scripts/search.py "phone stand"
  python3 scripts/search.py "vase" --source makerworld --limit 10
  python3 scripts/search.py "cable clip" --sort likes --json

Exit codes: 0 the search ran (even with no results) · 1 every site failed ·
2 bad arguments.
"""

import argparse
import json
import sys

from bambu_studio_ai.search import DEFAULT_LIMIT, MAX_LIMIT, SITE_NAMES, SITES, SORT_KEYS, search
from common import use_utf8_stdio

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

REMOVED_SOURCES = ("thangs", "thingiverse")
REMOVED_MESSAGE = """\
`--source {source}` was removed in v2.1.

Model search now asks each site's own search API instead of a web search engine,
which returned ads and pages from other sites. Thingiverse's API needs every user to
register their own OAuth app, and Thangs has no public API, so neither is searched
for now. Search MakerWorld and Printables instead:

  python3 scripts/search.py "<query>"                  # both sites
  python3 scripts/search.py "<query>" --source printables
"""

AGENT_HINT = ("➡️ Show the user these options (title, site, licence, link) and let them pick; "
              "they download the file from the site themselves.")


def limit_value(text):
    """argparse type for --limit: an int from 1 to MAX_LIMIT."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not 1 <= value <= MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_LIMIT}")
    return value


def build_parser():
    parser = argparse.ArgumentParser(
        description="Search MakerWorld and Printables for 3D models to print.",
        epilog="Only the query is sent, to api.bambulab.com (MakerWorld) and "
               "api.printables.com. Nothing is downloaded.",
    )
    parser.add_argument("query", help="what to look for, e.g. 'phone stand'")
    parser.add_argument("--source", "-s", default="all", choices=["all", *SITES, *REMOVED_SOURCES],
                        metavar="{all," + ",".join(SITES) + "}",
                        help="site to search (default: all)")
    parser.add_argument("--limit", "-l", type=limit_value, default=DEFAULT_LIMIT,
                        help=f"total number of results across all sites, not per site "
                             f"(1-{MAX_LIMIT}, default {DEFAULT_LIMIT})")
    parser.add_argument("--sort", choices=SORT_KEYS, default="downloads",
                        help="downloads (default), likes, newest, or relevance "
                             "(each site's own ranking, alternating between sites)")
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    return parser


def format_result(number, result):
    stats = [SITE_NAMES[result.site]]
    if result.author:
        stats.append(f"by {result.author}")
    if result.downloads is not None:
        stats.append(f"{result.downloads:,} downloads")
    if result.likes is not None:
        stats.append(f"{result.likes:,} likes")
    stats.append(result.license or "licence not stated")
    return f"{number:>2}. {result.title}\n    {' · '.join(stats)}\n    {result.url}"


def print_human(query, report, sort):
    names = " and ".join(SITE_NAMES[site] for site in report.sites)
    if not report.results:
        if not report.all_failed:
            print(f'No models found for "{query}" on {names}. Try fewer or different words, or English terms.')
        return
    print(f'🔍 {len(report.results)} models for "{query}" on {names}, by {sort}:\n')
    for number, result in enumerate(report.results, 1):
        print(format_result(number, result))
    print()
    print(AGENT_HINT)


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.source in REMOVED_SOURCES:
        print(REMOVED_MESSAGE.format(source=args.source), file=sys.stderr)
        return EXIT_USAGE
    sites = SITES if args.source == "all" else (args.source,)
    try:
        report = search(args.query, sites=sites, limit=args.limit, sort=args.sort)
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return EXIT_USAGE

    for failure in report.failed_sites:
        print(f"⚠️ {SITE_NAMES[failure.site]} could not be searched: {failure.reason}", file=sys.stderr)
    if report.all_failed:
        print("❌ Search failed on every site; check the internet connection and try again.", file=sys.stderr)

    query = " ".join(args.query.split())
    if args.json:
        print(json.dumps({"schema": 1, "query": query, "sort": args.sort, **report.to_dict()},
                         ensure_ascii=False))
    else:
        print_human(query, report, args.sort)
    return EXIT_FAILED if report.all_failed else EXIT_OK


if __name__ == "__main__":
    use_utf8_stdio()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
