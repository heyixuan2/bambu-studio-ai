#!/usr/bin/env python3
"""
Bambu Studio AI — Model Search
Searches 3D model repositories via web search aggregation.
Works without API keys — uses site-specific web search queries.

Usage:
  python3 search.py "pikachu"
  python3 search.py "vase" --source makerworld --limit 5
  python3 search.py "gear" --source all

Sources: MakerWorld, Printables, Thingiverse, Thangs
"""

import argparse, json, os, re, sys
import requests

TIMEOUT = (10, 30)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

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
    """Search via DuckDuckGo HTML (no API key needed)."""
    search_q = f"site:{site} {query}" if site else query
    url = "https://html.duckduckgo.com/html/"
    try:
        r = requests.post(url, data={"q": search_q, "b": ""},
                         headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        # Parse results from HTML
        results = []
        # Find all result links
        for match in re.finditer(r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.+?)</a>', r.text):
            href = match.group(1)
            title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
            if href and title and len(results) < limit:
                # Extract clean URL from DDG redirect
                clean_url = href
                if "uddg=" in href:
                    clean_url = re.search(r'uddg=([^&]+)', href)
                    if clean_url:
                        from urllib.parse import unquote
                        clean_url = unquote(clean_url.group(1))
                    else:
                        clean_url = href
                # Skip ads and non-matching URLs
                if "duckduckgo.com" in clean_url or "ad_domain" in clean_url or "bing.com/aclick" in clean_url:
                    continue
                results.append({"url": clean_url, "title": title})
        return results
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
            # Extract model ID from URL
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
    print("   2. Run: python3 analyze.py <file> --height 80 --orient --repair")
    print("   3. For multi-color: python3 colorize.py <file.glb> --palette bambu")


def main():
    parser = argparse.ArgumentParser(description="Search 3D model repositories (MakerWorld, Printables, Thingiverse, Thangs)")
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
