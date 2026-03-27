#!/usr/bin/env python3
"""
kisssub-search: download module
Add magnet/torrent downloads to qBittorrent via Web API.

Usage:
    python3 download.py --hash <info_hash>
    python3 download.py --magnet "magnet:?xt=urn:btih:xxx"
    python3 download.py --torrent /path/to/file.torrent
    python3 download.py --hash <info_hash> --savepath /data/anime

Environment variables:
    QB_HOST     qBittorrent API address (default: http://localhost:8080)
    QB_USER     username (default: admin)
    QB_PASS     password (required)
    QB_SAVEPATH default save path (default: ~/Downloads)

Standalone module, no internal dependencies.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile


TORRENT_DL_BASE = "http://v2.uploadbt.com/?r=down&hash="


def get_default_savepath() -> str:
    """Get platform-appropriate default download directory."""
    if platform.system() == "Windows":
        return os.path.join(os.path.expanduser("~"), "Downloads")
    return os.path.join(os.path.expanduser("~"), "Downloads")


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


def qb_add_torrent_file(host: str, cookie_file: str, torrent_path: str, savepath: str) -> bool:
    """Add a .torrent file to qBittorrent."""
    args = [
        "curl", "-s", "-b", cookie_file,
        f"{host}/api/v2/torrents/add",
        "-F", f"torrents=@{torrent_path}",
    ]
    if savepath:
        args += ["-F", f"savepath={savepath}"]
    result = curl_run(args)
    return result.stdout.strip() == "Ok."


def qb_add_magnet(host: str, cookie_file: str, magnet: str, savepath: str) -> bool:
    """Add a magnet link to qBittorrent."""
    data = f"urls={magnet}"
    if savepath:
        data += f"&savepath={savepath}"
    result = curl_run([
        "curl", "-s", "-b", cookie_file,
        f"{host}/api/v2/torrents/add",
        "-d", data,
    ])
    return result.stdout.strip() == "Ok."


def download_torrent_file(info_hash: str) -> str:
    """Download .torrent file from kisssub to temp dir. Returns file path."""
    url = f"{TORRENT_DL_BASE}{info_hash}"
    if platform.system() == "Windows":
        tmp_dir = tempfile.gettempdir()
    else:
        tmp_dir = "/tmp"
    torrent_path = os.path.join(tmp_dir, f"{info_hash}.torrent")

    result = curl_run([
        "curl", "-s", "--max-time", "15",
        "-o", torrent_path, url
    ])
    if result.returncode != 0:
        print(f"Error: failed to download torrent file", file=sys.stderr)
        return ""

    # Verify it's actually a torrent file
    if os.path.getsize(torrent_path) < 100:
        print(f"Error: downloaded file too small, might not be a valid torrent", file=sys.stderr)
        return ""

    return torrent_path


def main():
    parser = argparse.ArgumentParser(description="Add download to qBittorrent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--hash", help="Info hash (will download .torrent from kisssub)")
    group.add_argument("--magnet", help="Magnet link")
    group.add_argument("--torrent", help="Local .torrent file path")
    parser.add_argument("--savepath", help="Save directory")
    parser.add_argument("--host", help="qBittorrent API host")
    parser.add_argument("--user", help="qBittorrent username")
    parser.add_argument("--password", help="qBittorrent password")
    args = parser.parse_args()

    host = args.host or os.environ.get("QB_HOST", "http://localhost:8080")
    user = args.user or os.environ.get("QB_USER", "admin")
    password = args.password or os.environ.get("QB_PASS", "")
    savepath = args.savepath or os.environ.get("QB_SAVEPATH", get_default_savepath())

    if not password:
        print("Error: qBittorrent password required. Set QB_PASS or use --password", file=sys.stderr)
        sys.exit(1)

    # Login
    if platform.system() == "Windows":
        cookie_file = os.path.join(tempfile.gettempdir(), "qb_cookie.txt")
    else:
        cookie_file = "/tmp/qb_cookie_kisssub.txt"

    if not qb_login(host, user, password, cookie_file):
        print("Error: failed to login to qBittorrent", file=sys.stderr)
        sys.exit(1)

    # Add download
    if args.hash:
        print(f"Downloading .torrent for hash: {args.hash}")
        torrent_path = download_torrent_file(args.hash)
        if not torrent_path:
            sys.exit(1)
        success = qb_add_torrent_file(host, cookie_file, torrent_path, savepath)
        method = "torrent file"

    elif args.magnet:
        success = qb_add_magnet(host, cookie_file, args.magnet, savepath)
        method = "magnet link"

    elif args.torrent:
        if not os.path.isfile(args.torrent):
            print(f"Error: torrent file not found: {args.torrent}", file=sys.stderr)
            sys.exit(1)
        success = qb_add_torrent_file(host, cookie_file, args.torrent, savepath)
        method = "torrent file"

    if success:
        print(f"✅ Download added successfully via {method}")
        print(f"   Save path: {savepath}")
        if args.hash:
            print(f"   Hash: {args.hash}")
    else:
        print(f"❌ Failed to add download", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
