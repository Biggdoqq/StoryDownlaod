"""
API Client for Hongguo Downloader & Explorer
Endpoints provided by https://explorer.hongguodownloader.com
with automatic fallback to Cloudflare Worker mirrors.
"""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, List, Optional

BASE_URLS = [
    "https://explorer.hongguodownloader.com",
    "https://hongguo-explorer.aly201514.workers.dev",
]

BASE_URL = BASE_URLS[0]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://hongguodownloader.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}


class HongguoAPI:
    def __init__(self, session: Optional[requests.Session] = None, timeout: int = 25):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.timeout = timeout

        # Configure robust connection pooling & retries
        try:
            retries = Retry(
                total=2,
                connect=2,
                read=2,
                backoff_factor=0.3,
                status_forcelist=[500, 502, 503, 504],
                raise_on_status=False
            )
            adapter = HTTPAdapter(max_retries=retries, pool_connections=15, pool_maxsize=15)
            self.session.mount("https://", adapter)
            self.session.mount("http://", adapter)
        except Exception:
            pass

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[int] = None) -> requests.Response:
        """Fetch request with auto-failover across primary & backup endpoints."""
        t = timeout or self.timeout
        last_exc = None
        for base in BASE_URLS:
            url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
            try:
                resp = self.session.get(url, params=params, timeout=t)
                resp.raise_for_status()
                return resp
            except Exception as e:
                last_exc = e
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError("No API host available")

    def get_leaderboard(self, category: str = "all", size: int = 100) -> Dict[str, Any]:
        """
        Fetch leaderboard drama ranking.
        category: 'all', 'human', 'comic', 'ai'
        """
        params = {
            "board": "hot",
            "category": category,
            "size": size
        }
        resp = self._get("/leaderboard", params=params)
        return resp.json()

    def get_catalogue(
        self,
        page: int = 1,
        size: int = 48,
        sort: str = "newest",
        status: str = "",
        genre: str = "",
        q: str = ""
    ) -> Dict[str, Any]:
        """
        Browse or search the 40,000+ short-drama catalogue.
        sort: 'newest', 'popular', 'eps'
        status: '', 'completed', 'ongoing'
        genre: genre name or tag
        q: search query
        """
        params: Dict[str, Any] = {
            "page": page,
            "size": size,
            "sort": sort,
        }
        if status:
            params["status"] = status
        if genre:
            params["genre"] = genre
        if q:
            params["q"] = q

        resp = self._get("/explorer", params=params)
        return resp.json()

    def get_genres(self, limit: int = 60) -> List[Dict[str, Any]]:
        """
        Fetch available drama genres and categories.
        """
        params = {"limit": limit}
        try:
            resp = self._get("/genres", params=params, timeout=12)
            data = resp.json()
            return data.get("genres", [])
        except Exception:
            return []

    def get_stats(self) -> Dict[str, Any]:
        """
        Fetch live total drama stats.
        """
        try:
            resp = self._get("/explorer", params={"size": 1}, timeout=12)
            return resp.json()
        except Exception:
            return {"count": 0}

    def fetch_image_bytes(self, url: str) -> Optional[bytes]:
        """
        Fetch image data with proper Referer & headers.
        """
        if not url:
            return None
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                return resp.content
        except Exception:
            pass
        return None
