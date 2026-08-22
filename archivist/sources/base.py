from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImageResult:
    """One search hit, before it has been downloaded or judged."""

    image_url: str
    title: str = ""
    page_url: str = ""
    thumbnail: str = ""
    width: int = 0
    height: int = 0
    source: str = ""
    attribution: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


class Source:
    """Interface every reference source implements."""

    name: str = "source"
    requires_key: bool = False

    def search(self, query: str, limit: int = 6) -> list[ImageResult]:  # pragma: no cover - interface
        raise NotImplementedError

    def check(self) -> tuple[bool, str]:
        """Connectivity self-test used by the Gradio connection tab."""
        try:
            results = self.search("archival document photograph", limit=1)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        if not results:
            return False, "reachable but returned no results"
        return True, f"ok — sample: {results[0].image_url[:80]}"
