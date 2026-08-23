"""How crowded is this topic already?

A rising trend that ten thousand sellers already print is worth less than a
smaller one nobody has touched. Competition is measured two ways:

* **listing density** — of the top web results for `"<topic>" t shirt`, how many
  are live marketplace listings (Redbubble, Etsy, TeePublic, Amazon Merch, …);
* **design saturation** — how many existing shirt designs show up in image search.

Both are proxies, and they are labelled as proxies: no marketplace publishes a
"how many sellers are on this niche" number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

MARKETPLACES = {
    "redbubble.com": "Redbubble",
    "etsy.com": "Etsy",
    "teepublic.com": "TeePublic",
    "society6.com": "Society6",
    "zazzle.com": "Zazzle",
    "spreadshirt.com": "Spreadshirt",
    "threadless.com": "Threadless",
    "amazon.com": "Amazon",
    "displate.com": "Displate",
    "printful.com": "Printful",
    "teespring.com": "Spring",
    "spring.by": "Spring",
    "customink.com": "CustomInk",
    "shopify.com": "Shopify store",
    "merchbar.com": "Merchbar",
}

SHIRT_WORDS = re.compile(r"\b(t[- ]?shirt|tee|hoodie|sweatshirt|apparel|merch)\b", re.I)


@dataclass
class CompetitionReport:
    topic: str
    listings: int = 0
    marketplaces: list[str] = field(default_factory=list)
    results_seen: int = 0
    design_hits: int = 0
    competition: float = 0.0     # 0..100, higher = more crowded
    examples: list[str] = field(default_factory=list)
    ok: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "listings": self.listings, "results_seen": self.results_seen,
            "marketplaces": self.marketplaces, "design_hits": self.design_hits,
            "competition": round(self.competition, 1), "ok": self.ok, "error": self.error,
        }

    @property
    def gap(self) -> float:
        """0..10 — how much room is left. The scorer wants a gap, not a crowd."""
        return round(max(0.0, 10.0 - self.competition / 10.0), 2)


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def measure(
    topic: str,
    text_source,
    image_source=None,
    *,
    results: int = 30,
    image_results: int = 20,
) -> CompetitionReport:
    """Count marketplace listings and existing shirt designs for a topic."""
    report = CompetitionReport(topic=topic)
    query = f'"{topic}" t shirt'

    try:
        rows = text_source.search(query, limit=results)
    except Exception as exc:
        report.ok = False
        report.error = f"{type(exc).__name__}: {exc}"
        return report

    report.results_seen = len(rows)
    seen_markets: list[str] = []
    for row in rows:
        domain = _domain(row.get("url", ""))
        market = next((name for host, name in MARKETPLACES.items() if domain.endswith(host)), "")
        text = f"{row.get('title', '')} {row.get('snippet', '')}"
        if market and SHIRT_WORDS.search(text):
            report.listings += 1
            if market not in seen_markets:
                seen_markets.append(market)
            if len(report.examples) < 5:
                report.examples.append(row.get("url", "")[:120])
    report.marketplaces = seen_markets

    if image_source is not None:
        try:
            hits = image_source.search(f"{topic} t shirt design", limit=image_results)
            report.design_hits = len(hits)
        except Exception:
            report.design_hits = 0  # not fatal; listing density already answered

    # Density of the visible market, plus a smaller weight for how many designs
    # already exist, plus a penalty for being spread across many marketplaces.
    density = report.listings / max(1, report.results_seen)
    saturation = report.design_hits / max(1, image_results)
    spread = min(1.0, len(report.marketplaces) / 5.0)
    report.competition = round(
        100.0 * min(1.0, 0.62 * density + 0.23 * saturation + 0.15 * spread), 1
    )
    if not rows:
        report.error = "no search results — competition could not be measured"
        report.ok = False
    return report
