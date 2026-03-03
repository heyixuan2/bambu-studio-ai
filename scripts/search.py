#!/usr/bin/env python3
"""
Bambu Studio AI — Model Search
Searches 3D model repositories via DuckDuckGo.

Usage:
  python3 scripts/search.py "pikachu"
  python3 scripts/search.py "vase" --source makerworld --limit 5
  python3 scripts/search.py "gear" --source all

Sources: MakerWorld, Printables, Thingiverse, Thangs
Requires: pip install ddgs
"""

import argparse, json, os, re, sys

SOURCES = {
    "makerworld": {
        "site": "makerworld.com",
        "url_pattern": r"makerworld\.com/en/models/(\d+)",
        "display": "MakerWorld (Bambu Lab)"
    },
    "printables": {
        "site": "printables.com/model",
        "url_pattern": r"printables\.com/model/(\d+)",
        "display": "Printables (Prusa)"
    },
    "thingiverse": {
        "site": "thingiverse.com/thing",
        "url_pattern": r"thingiverse\.com/thing:(\d+)",
        "display": "Thingiverse"
    },
    "thangs": {
        "site": "thangs.com",
        "url_pattern": r"thangs\.com/.+/(\d+)",
        "display": "Thangs"
    }
}


def _web_search(query, site=None, limit=5):
    """Search via DuckDuckGo (ddgs package)."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            print("⚠️ Install search backend: pip install ddgs")
            return []

    search_q = f"site:{site} {query}" if site else query
    try:
        raw = DDGS().text(search_q, max_results=limit)
        return [{"url": r["href"], "title": r["title"]} for r in raw if r.get("href")]
    except Exception as e:
        print(f"⚠️ Search failed: {e}")
        return []


def search(query, source="all", limit=5):
    """Search 3D model repositories."""
    results = []

    if source == "all":
        sources_to_search = SOURCES.items()
    elif source in SOURCES:
        sources_to_search = [(source, SOURCES[source])]
    else:
        print(f"❌ Unknown source: {source}. Choose: {', '.join(SOURCES.keys())}, all")
        return []

    for name, config in sources_to_search:
        raw = _web_search(f"{query} 3D printable model", site=config["site"], limit=limit)
        for r in raw:
            id_match = re.search(config["url_pattern"], r["url"])
            model_id = id_match.group(1) if id_match else ""
            results.append({
                "source": config["display"],
                "source_key": name,
                "name": r["title"],
                "url": r["url"],
                "id": model_id,
            })

    return results


def print_results(results):
    """Pretty-print search results."""
    if not results:
        print("❌ No models found. Try different keywords.")
        return

    print(f"\n🔍 Found {len(results)} models:\n")
    for i, r in enumerate(results, 1):
        print(f"  {i}. [{r['source']}] {r['name']}")
        print(f"     {r['url']}")
        print()

    print("💡 To use a model:")
    print("   1. Download the STL/OBJ from the link above")
    print("   2. Run: python3 scripts/analyze.py <file> --height 80 --orient --repair")
    print("   3. For multi-color: python3 scripts/colorize.py <file.glb> --palette bambu")


def main():
    parser = argparse.ArgumentParser(
        description="Search 3D model repositories (MakerWorld, Printables, Thingiverse, Thangs)")
    parser.add_argument("query", help="Search query (e.g. 'pikachu', 'gear box')")
    parser.add_argument("--source", "-s", default="all",
                       choices=["all"] + list(SOURCES.keys()),
                       help="Source (default: all)")
    parser.add_argument("--limit", "-l", type=int, default=5,
                       help="Max results per source (default: 5)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    results = search(args.query, args.source, args.limit)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_results(results)


if __name__ == "__main__":
    main()
