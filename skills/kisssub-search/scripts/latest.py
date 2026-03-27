#!/usr/bin/env python3
"""
kisssub-search: latest module
Fetch latest anime resources from kisssub.org via RSS feed.

Usage:
    python3 latest.py
    python3 latest.py --limit 5
    python3 latest.py --json

Standalone module, no internal dependencies.
"""

import argparse
import json
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET


KISSSUB_RSS_URL = "https://www.kisssub.org/rss.xml"
TORRENT_BASE = "http://v2.uploadbt.com/?r=down&hash="


def fetch_rss(url: str) -> str:
    """Fetch RSS content via curl (cross-platform)."""
    cmd = ["curl", "-s", "--max-time", "15", url]
    if platform.system() == "Windows":
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    else:
        result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: failed to fetch {url}", file=sys.stderr)
        sys.exit(1)
    return result.stdout


def parse_rss(xml_text: str) -> list:
    """Parse RSS XML and return list of resource dicts."""
    results = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"Error: failed to parse RSS XML: {e}", file=sys.stderr)
        sys.exit(1)

    for item in root.findall(".//item"):
        title_el = item.find("title")
        link_el = item.find("link")
        author_el = item.find("author")
        pub_el = item.find("pubDate")
        cat_el = item.find("category")
        enc_el = item.find("enclosure")

        title = title_el.text.strip() if title_el is not None and title_el.text else ""
        link = link_el.text.strip() if link_el is not None and link_el.text else ""
        author = author_el.text.strip() if author_el is not None and author_el.text else ""
        pub_date = pub_el.text.strip() if pub_el is not None and pub_el.text else ""
        category = cat_el.text.strip() if cat_el is not None and cat_el.text else ""

        info_hash = ""
        torrent_url = ""
        if enc_el is not None:
            enc_url = enc_el.get("url", "")
            if "hash=" in enc_url:
                info_hash = enc_url.split("hash=")[-1]
                torrent_url = f"{TORRENT_BASE}{info_hash}"

        magnet = f"magnet:?xt=urn:btih:{info_hash}" if info_hash else ""

        results.append({
            "title": title,
            "link": link,
            "author": author,
            "pub_date": pub_date,
            "category": category,
            "info_hash": info_hash,
            "magnet": magnet,
            "torrent_url": torrent_url,
        })

    return results


def display_results(results: list, output_json: bool = False):
    """Display results."""
    if output_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        print(f"[{i}] {r['title'][:80]}")
        print(f"    {r['author']}  |  {r['pub_date'][:20]}  |  {r['category']}")
        print(f"    Hash: {r['info_hash']}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Fetch latest resources from kisssub.org")
    parser.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    xml_text = fetch_rss(KISSSUB_RSS_URL)
    results = parse_rss(xml_text)
    results = results[:args.limit]
    display_results(results, output_json=args.json)


if __name__ == "__main__":
    main()
