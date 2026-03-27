#!/usr/bin/env python3
"""
kisssub-search: status module
Query qBittorrent download status via Web API.

Usage:
    python3 status.py
    python3 status.py --hash <info_hash>
    python3 status.py --json

Environment variables:
    QB_HOST     qBittorrent API address (default: http://localhost:8080)
    QB_USER     username (default: admin)
    QB_PASS     password (required)

Standalone module, no internal dependencies.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile


def curl_run(args: list) -> subprocess.CompletedProcess:
    """Run curl command, cross-platform."""
    if platform.system() == "Windows":
        return subprocess.run(args, capture_output=True, text=True, shell=True)
    return subprocess.run(args, capture_output=True, text=True)


def qb_login(host: str, user: str, password: str, cookie_file: str) -> bool:
    """Login to qBittorrent and save session cookie."""
    result = curl_run([
        "curl", "-s", "-c", cookie_file,
        f"{host}/api/v2/auth/login",
        "-d", f"username={user}&password={password}"
    ])
    return result.stdout.strip() == "Ok."


def qb_get_torrents(host: str, cookie_file: str, info_hash: str = None) -> list:
    """Fetch torrent list from qBittorrent."""
    url = f"{host}/api/v2/torrents/info"
    if info_hash:
        url += f"?hashes={info_hash}"
    result = curl_run(["curl", "-s", "-b", cookie_file, url])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Error: invalid response from qBittorrent", file=sys.stderr)
        return []


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.1f} {units[i]}"


def format_eta(seconds: int) -> str:
    """Format ETA seconds to human readable."""
    if seconds >= 8640000 or seconds < 0:
        return "∞"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"


STATE_MAP = {
    "downloading": "⬇️  Downloading",
    "uploading": "⬆️  Seeding",
    "stalledDL": "⏳ Stalled (DL)",
    "stalledUP": "⏳ Stalled (Seed)",
    "pausedDL": "⏸️  Paused",
    "pausedUP": "⏸️  Paused (Seed)",
    "queuedDL": "🔜 Queued",
    "metaDL": "🔍 Getting metadata",
    "error": "❌ Error",
    "missingFiles": "⚠️  Missing files",
    "checkingDL": "🔄 Checking",
    "checkingUP": "🔄 Checking",
    "forcedDL": "⬇️  Force DL",
    "forcedUP": "⬆️  Force Seed",
    "completed": "✅ Completed",
}


def display_torrents(torrents: list, output_json: bool = False):
    """Display torrent status."""
    if output_json:
        print(json.dumps(torrents, ensure_ascii=False, indent=2))
        return

    if not torrents:
        print("No active downloads.")
        return

    for t in torrents:
        state = STATE_MAP.get(t["state"], t["state"])
        progress = t["progress"] * 100
        size = format_size(t["total_size"])
        dl_speed = format_size(t["dlspeed"]) + "/s"
        up_speed = format_size(t["upspeed"]) + "/s"
        eta = format_eta(t["eta"])
        name = t["name"][:70]

        print(f"\n📦 {name}")
        print(f"   State: {state}  |  Progress: {progress:.1f}%  |  Size: {size}")
        print(f"   DL: {dl_speed}  |  UP: {up_speed}  |  ETA: {eta}")
        print(f"   Seeds: {t['num_seeds']}  |  Peers: {t['num_leechs']}")
        print(f"   Path: {t['save_path']}")
        print(f"   Hash: {t['hash']}")


def main():
    parser = argparse.ArgumentParser(description="Check qBittorrent download status")
    parser.add_argument("--hash", help="Filter by info hash")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--host", help="qBittorrent API host")
    parser.add_argument("--user", help="qBittorrent username")
    parser.add_argument("--password", help="qBittorrent password")
    args = parser.parse_args()

    host = args.host or os.environ.get("QB_HOST", "http://localhost:8080")
    user = args.user or os.environ.get("QB_USER", "admin")
    password = args.password or os.environ.get("QB_PASS", "")

    if not password:
        print("Error: qBittorrent password required. Set QB_PASS or use --password", file=sys.stderr)
        sys.exit(1)

    # Login
    if platform.system() == "Windows":
        cookie_file = os.path.join(tempfile.gettempdir(), "qb_cookie_status.txt")
    else:
        cookie_file = "/tmp/qb_cookie_kisssub_status.txt"

    if not qb_login(host, user, password, cookie_file):
        print("Error: failed to login to qBittorrent", file=sys.stderr)
        sys.exit(1)

    torrents = qb_get_torrents(host, cookie_file, args.hash)
    display_torrents(torrents, output_json=args.json)


if __name__ == "__main__":
    main()
