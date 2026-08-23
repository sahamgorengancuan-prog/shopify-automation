"""DuckDuckGo image search — broad, archival, weird, and no API key required.

Uses the ``ddgs`` package when it is installed (it tracks endpoint changes) and
otherwise talks to the public i.js endpoint directly with a vqd token.
"""

from __future__ import annotations

import re
import time
import urllib.parse

from .. import http
from .base import ImageResult, Source

VQD_PATTERNS = (
    re.compile(r'vqd="([^"]+)"'),
    re.compile(r"vqd=([\d-]+)&"),
    re.compile(r'vqd=&quot;([^&]+)&quot;'),
)


class DuckDuckGoImages(Source):
    name = "duckduckgo"

    def __init__(self, *, user_agent: str = http.DEFAULT_UA, timeout: int = 45, safesearch: str = "moderate"):
        self.user_agent = user_agent
        self.timeout = timeout
        self.safesearch = safesearch
        self._vqd_cache: dict[str, tuple[str, float]] = {}

    # -- ddgs path --------------------------------------------------------
    def _search_library(self, query: str, limit: int) -> list[ImageResult]:
        try:
            from ddgs import DDGS  # type: ignore
        except Exception:
            try:
                from duckduckgo_search import DDGS  # type: ignore
            except Exception:
                return []
        try:
            with DDGS() as client:
                rows = list(client.images(query, max_results=limit, safesearch=self.safesearch))
        except Exception:
            return []
        return [
            ImageResult(
                image_url=row.get("image", ""),
                title=row.get("title", ""),
                page_url=row.get("url", ""),
                thumbnail=row.get("thumbnail", ""),
                width=int(row.get("width") or 0),
                height=int(row.get("height") or 0),
                source=self.name,
                attribution=row.get("source", ""),
            )
            for row in rows
            if row.get("image")
        ]

    # -- direct path ------------------------------------------------------
    def _vqd(self, query: str) -> str:
        cached = self._vqd_cache.get(query)
        if cached and time.time() - cached[1] < 600:
            return cached[0]
        status, content = http.request(
            "POST",
            "https://duckduckgo.com/",
            data=urllib.parse.urlencode({"q": query}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
            user_agent=self.user_agent,
            retries=2,
        )
        if status >= 400:
            raise http.HttpError(f"duckduckgo token request -> HTTP {status}", status)
        text = content.decode("utf-8", "replace")
        for pattern in VQD_PATTERNS:
            match = pattern.search(text)
            if match:
                token = match.group(1)
                self._vqd_cache[query] = (token, time.time())
                return token
        raise http.HttpError("duckduckgo: could not extract vqd token")

    def _search_direct(self, query: str, limit: int) -> list[ImageResult]:
        token = self._vqd(query)
        payload = http.get_json(
            "https://duckduckgo.com/i.js",
            params={
                "l": "us-en",
                "o": "json",
                "q": query,
                "vqd": token,
                "f": ",,,",
                "p": "1",
                "v7exp": "a",
            },
            headers={
                "Referer": "https://duckduckgo.com/",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            timeout=self.timeout,
            user_agent=self.user_agent,
            retries=2,
        )
        rows = payload.get("results", []) if isinstance(payload, dict) else []
        results: list[ImageResult] = []
        for row in rows[:limit]:
            image_url = row.get("image") or ""
            if not image_url:
                continue
            results.append(
                ImageResult(
                    image_url=image_url,
                    title=row.get("title", ""),
                    page_url=row.get("url", ""),
                    thumbnail=row.get("thumbnail", ""),
                    width=int(row.get("width") or 0),
                    height=int(row.get("height") or 0),
                    source=self.name,
                    attribution=row.get("source", ""),
                )
            )
        return results

    def search(self, query: str, limit: int = 6) -> list[ImageResult]:
        results = self._search_library(query, limit)
        if results:
            return results
        return self._search_direct(query, limit)


# --- text search ---------------------------------------------------------
# Used by discovery to measure how crowded a topic already is on the apparel
# marketplaces. Separate from image search because it has a different endpoint
# and a different failure mode.

HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'(?:.*?<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>)?',
    re.DOTALL,
)
_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    import html as html_module

    return html_module.unescape(_TAGS.sub("", text or "")).strip()


class DuckDuckGoText:
    """Plain web search — returns (title, url, snippet) rows."""

    name = "duckduckgo_text"

    def __init__(self, *, user_agent: str = http.DEFAULT_UA, timeout: int = 45, request_delay: float = 0.8):
        self.user_agent = user_agent
        self.timeout = timeout
        self.request_delay = request_delay
        self.last_error = ""

    def _library(self, query: str, limit: int) -> list[dict[str, str]]:
        try:
            from ddgs import DDGS  # type: ignore
        except Exception:
            try:
                from duckduckgo_search import DDGS  # type: ignore
            except Exception:
                return []
        try:
            with DDGS() as client:
                rows = list(client.text(query, max_results=limit))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []
        return [
            {
                "title": row.get("title", ""),
                "url": row.get("href") or row.get("url", ""),
                "snippet": row.get("body", ""),
            }
            for row in rows
        ]

    def _html(self, query: str, limit: int) -> list[dict[str, str]]:
        time.sleep(self.request_delay)
        status, content = http.request(
            "POST",
            HTML_ENDPOINT,
            data=urllib.parse.urlencode({"q": query}).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
            user_agent=self.user_agent,
            retries=2,
        )
        if status >= 400:
            raise http.HttpError(f"duckduckgo html -> HTTP {status}", status)
        body = content.decode("utf-8", "replace")
        rows: list[dict[str, str]] = []
        for match in _RESULT.finditer(body):
            href = match.group("href")
            # DDG wraps outbound links: /l/?uddg=<encoded target>
            if "uddg=" in href:
                href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
            rows.append({
                "title": _clean(match.group("title")),
                "url": href,
                "snippet": _clean(match.group("snippet") or ""),
            })
            if len(rows) >= limit:
                break
        return rows

    def search(self, query: str, limit: int = 30) -> list[dict[str, str]]:
        rows = self._library(query, limit)
        if rows:
            return rows
        try:
            return self._html(query, limit)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []

    def check(self) -> tuple[bool, str]:
        rows = self.search("archival design", limit=3)
        if rows:
            return True, f"ok — {len(rows)} results, first: {rows[0]['url'][:60]}"
        return False, self.last_error or "reachable but returned no results"
