"""Pexels — contemporary photography, cinematic light, clean textures.

Pexels licences require attribution to the photographer, so it is captured on
every reference and carried into the reference board.
"""

from __future__ import annotations

from .. import http
from .base import ImageResult, Source

API = "https://api.pexels.com/v1/search"


class PexelsImages(Source):
    name = "pexels"
    requires_key = True

    def __init__(self, *, api_key: str, timeout: int = 45):
        self.api_key = api_key
        self.timeout = timeout

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": self.api_key}

    def search(self, query: str, limit: int = 6) -> list[ImageResult]:
        if not self.api_key:
            return []
        payload = http.get_json(
            API,
            params={"query": query, "per_page": max(1, min(30, limit)), "orientation": "portrait"},
            headers=self.headers,
            timeout=self.timeout,
            retries=2,
        )
        results: list[ImageResult] = []
        for photo in payload.get("photos", [])[:limit]:
            src = photo.get("src", {})
            image_url = src.get("large2x") or src.get("large") or src.get("original", "")
            if not image_url:
                continue
            photographer = photo.get("photographer", "unknown")
            results.append(
                ImageResult(
                    image_url=image_url,
                    title=photo.get("alt") or query,
                    page_url=photo.get("url", ""),
                    thumbnail=src.get("medium", ""),
                    width=int(photo.get("width") or 0),
                    height=int(photo.get("height") or 0),
                    source=self.name,
                    attribution=f"Photo by {photographer} on Pexels",
                    extra={"photographer_url": photo.get("photographer_url", "")},
                )
            )
        return results

    def check(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "PEXELS_API_KEY not set"
        try:
            payload = http.get_json(
                API, params={"query": "archive", "per_page": 1}, headers=self.headers,
                timeout=self.timeout, retries=1,
            )
        except http.HttpError as exc:
            return False, str(exc)
        total = payload.get("total_results", 0)
        return True, f"ok — key accepted, {total} results for a probe query"
