"""
github_updater.py — GitHub-Exclusive Release & In-App Auto-Update Module
Directly connects to https://github.com/Biggdoqq/StoryDownlaod to check for updates,
fetch release notes / changelogs, and stream installer assets with live progress.
"""

import os
import sys
import time
import re
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Callable

GITHUB_REPO = "Biggdoqq/StoryDownlaod"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/Biggdoqq/StoryDownlaod/releases"
GITHUB_RAW_VERSION = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HongguoDownloader/1.0",
    "Accept": "application/vnd.github.v3+json"
}


def parse_version_tuple(v_str: str) -> tuple:
    """Parse version string like 'v1.0.8' or '1.0.8' into numerical tuple (1, 0, 8)."""
    if not v_str:
        return (0,)
    clean = re.sub(r"^[vV]", "", v_str.strip())
    parts = re.findall(r"\d+", clean)
    return tuple(map(int, parts)) if parts else (0,)


def check_github_release(current_version: str = "1.0.7") -> Dict[str, Any]:
    """
    Check if a newer version is published on GitHub (Biggdoqq/StoryDownlaod).
    Returns:
    {
        "has_update": bool,
        "current_version": str,
        "latest_version": str,
        "release_title": str,
        "changelog": str,
        "download_url": str,
        "asset_name": str,
        "asset_size": int,
        "published_at": str,
        "html_url": str,
        "error": str
    }
    """
    res = {
        "has_update": False,
        "current_version": current_version,
        "latest_version": current_version,
        "release_title": "",
        "changelog": "",
        "download_url": "",
        "asset_name": "",
        "asset_size": 0,
        "published_at": "",
        "html_url": GITHUB_RELEASES_PAGE,
        "error": ""
    }

    try:
        resp = requests.get(GITHUB_API_LATEST, headers=HEADERS, timeout=8)
        
        # 1. Standard GitHub REST API
        if resp.status_code == 200:
            data = resp.json()
            tag_name = data.get("tag_name", "").strip()
            clean_latest = re.sub(r"^[vV]", "", tag_name)
            
            res["latest_version"] = clean_latest or current_version
            res["release_title"] = data.get("name") or f"Release {tag_name}"
            res["changelog"] = data.get("body") or "Performance enhancements & bug fixes."
            res["published_at"] = data.get("published_at", "")
            res["html_url"] = data.get("html_url") or GITHUB_RELEASES_PAGE

            # Locate setup installer asset (.exe)
            assets = data.get("assets", [])
            for asset in assets:
                name = asset.get("name", "")
                if name.lower().endswith(".exe"):
                    res["download_url"] = asset.get("browser_download_url", "")
                    res["asset_name"] = name
                    res["asset_size"] = asset.get("size", 0)
                    break
            
            # If no .exe found, check for .zip or fallback to html_url
            if not res["download_url"] and assets:
                res["download_url"] = assets[0].get("browser_download_url", "")
                res["asset_name"] = assets[0].get("name", "")
                res["asset_size"] = assets[0].get("size", 0)
            
            if not res["download_url"]:
                res["download_url"] = res["html_url"]

            # Compare version
            res["has_update"] = parse_version_tuple(clean_latest) > parse_version_tuple(current_version)
            return res

        # 2. Fallback: Check raw version.json if API is rate-limited or no release created yet
        try:
            raw_resp = requests.get(GITHUB_RAW_VERSION, headers=HEADERS, timeout=5)
            if raw_resp.status_code == 200:
                raw_data = raw_resp.json()
                clean_latest = raw_data.get("latest_version", "").strip()
                if clean_latest:
                    res["latest_version"] = clean_latest
                    res["release_title"] = raw_data.get("release_title", f"Release v{clean_latest}")
                    res["changelog"] = raw_data.get("changelog", "")
                    res["download_url"] = raw_data.get("download_url", "")
                    res["has_update"] = parse_version_tuple(clean_latest) > parse_version_tuple(current_version)
                    return res
        except Exception:
            pass

        if resp.status_code == 404:
            res["error"] = "No releases published yet on GitHub repository."
        elif resp.status_code == 403:
            res["error"] = "GitHub API rate limit exceeded. Please try again later."
        else:
            res["error"] = f"GitHub returned status code: {resp.status_code}"

    except Exception as e:
        res["error"] = str(e)

    return res


def download_github_asset(
    url: str,
    dest_path: str | Path,
    progress_callback: Optional[Callable[[int, int, int, float], None]] = None,
    cancel_flag: Optional[Callable[[], bool]] = None
) -> bool:
    """
    Download release asset (.exe) from GitHub with chunk streaming,
    live percentage calculation, and transfer speed (KB/s).
    progress_callback(downloaded_bytes, total_bytes, percent, speed_kb)
    """
    if not url:
        return False

    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest.with_suffix(".tmp")

    try:
        session = requests.Session()
        with session.get(url, headers=HEADERS, stream=True, allow_redirects=True, timeout=30) as r:
            r.raise_for_status()
            total_bytes = int(r.headers.get("content-length", 0))

            downloaded = 0
            start_time = time.time()
            last_speed_time = start_time
            last_speed_bytes = 0
            speed_kb = 0.0

            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if cancel_flag and cancel_flag():
                        f.close()
                        if tmp_path.exists():
                            tmp_path.unlink()
                        return False

                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)

                        now = time.time()
                        if now - last_speed_time >= 0.5:
                            bytes_diff = downloaded - last_speed_bytes
                            time_diff = max(now - last_speed_time, 0.001)
                            speed_kb = (bytes_diff / 1024) / time_diff
                            last_speed_time = now
                            last_speed_bytes = downloaded

                        pct = int((downloaded / total_bytes) * 100) if total_bytes > 0 else 0
                        if progress_callback:
                            progress_callback(downloaded, total_bytes, pct, speed_kb)

        # Atomic rename once complete
        if tmp_path.exists():
            if dest.exists():
                dest.unlink()
            tmp_path.rename(dest)
            return True

    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        return False

    return False
