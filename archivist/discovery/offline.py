"""Offline discovery — deterministic stand-in signals.

Discovery touches four external services, all of them rate limited and two of
them paid. Offline mode fabricates a plausible, *varied* signal set so the whole
autonomous loop — harvest, measure, screen, score, correlate, judge — can be run
in tests, in CI and in a demo without a single API key.

The numbers are synthetic and every signal it produces is labelled ``offline``
so nothing here can be mistaken for a real measurement.
"""

from __future__ import annotations

import math
import random
from typing import Any

from .competition import CompetitionReport
from .google_trends import InterestSeries, RisingQuery, TrendPoint
from .reddit import RedditHeat

# Object/practice/place topics — the shape of thing that actually wears well.
POOL = [
    ("cold plunge culture", "rising"), ("mechanical keyboard collecting", "rising"),
    ("urban foraging", "rising"), ("analogue photography revival", "rising"),
    ("cargo bike logistics", "rising"), ("sourdough hydration charts", "flat"),
    ("night train travel", "rising"), ("brutalist bus shelters", "rising"),
    ("competitive pigeon racing", "flat"), ("deep sea salvage", "rising"),
    ("tide clock making", "rising"), ("radio direction finding", "flat"),
    ("industrial rope access", "rising"), ("mushroom identification", "declining"),
    ("lighthouse automation", "flat"), ("cassette tape mastering", "declining"),
    ("harbour dredging", "flat"), ("desert seed banking", "rising"),
    ("glacier monitoring stations", "rising"), ("municipal water infrastructure", "flat"),
]

RISING_SUFFIXES = ["kit", "gear", "starter guide", "documentary", "archive", "society", "meetup", "records"]


def _shape(kind: str, rng: random.Random, length: int = 90) -> list[float]:
    """A believable 90-day Trends series with the requested trajectory."""
    base = rng.uniform(8, 30)
    out: list[float] = []
    for index in range(length):
        progress = index / max(1, length - 1)
        if kind == "rising":
            level = base * (1 + 2.6 * progress ** 1.7)
        elif kind == "declining":
            level = base * (1.9 - 1.1 * progress)
        else:
            level = base * (1 + 0.15 * math.sin(progress * 7))
        noise = rng.uniform(-0.13, 0.13) * level
        out.append(round(max(0.0, min(100.0, level + noise)), 1))
    return out


class OfflineSignals:
    """Drop-in replacement for the four live sources."""

    name = "offline"

    def __init__(self, *, seed: int = 0, geo: str = "US"):
        self.seed = seed
        self.geo = geo
        self.last_error = ""

    def _rng(self, key: str) -> random.Random:
        return random.Random(f"{self.seed}|{key}")

    # -- google trends ----------------------------------------------------
    def trending_now(self, limit: int = 25) -> list[dict[str, Any]]:
        rng = self._rng("trending")
        picks = rng.sample(POOL, k=min(limit, len(POOL)))
        return [
            {
                "title": topic,
                "traffic": rng.choice([2000, 5000, 10000, 20000, 50000]),
                "traffic_label": "[offline]",
                "news": [f"[offline] context for {topic}"],
                "link": "offline://trends",
            }
            for topic, _kind in picks
        ]

    def interest_over_time(self, keyword: str, timeframe: str | None = None) -> InterestSeries:
        rng = self._rng(f"series|{keyword}")
        kind = next((k for topic, k in POOL if topic == keyword), rng.choice(["rising", "flat", "declining"]))
        values = _shape(kind, rng)
        return InterestSeries(
            keyword=keyword,
            points=[TrendPoint(time=f"day {index + 1}", value=value) for index, value in enumerate(values)],
            ok=True,
        )

    def rising_queries(self, keyword: str, limit: int = 10) -> list[RisingQuery]:
        rng = self._rng(f"rising|{keyword}")
        head = keyword.split()[0]
        rows = [
            RisingQuery(query=f"{head} {suffix}", value=rng.choice([90, 140, 250, 400, 5000]))
            for suffix in rng.sample(RISING_SUFFIXES, k=min(limit, len(RISING_SUFFIXES)))
        ]
        for row in rows:
            row.breakout = row.value >= 5000
        return rows

    def check(self) -> tuple[bool, str]:
        return True, "ok — offline discovery generator"

    # -- reddit -----------------------------------------------------------
    def heat(self, query: str, *, limit: int = 50) -> RedditHeat:
        rng = self._rng(f"reddit|{query}")
        posts = rng.randint(3, 60)
        avg_engagement = rng.choice([25, 90, 300, 900, 2500])
        return RedditHeat(
            query=query,
            posts=posts,
            avg_score=avg_engagement * 0.7,
            avg_comments=avg_engagement * 0.15,
            avg_engagement=avg_engagement,
            subreddits=[f"r/offline{index}" for index in range(rng.randint(1, 8))],
            recent_share=round(rng.uniform(0.2, 0.9), 2),
            heat=round(min(100.0, 12 + posts * 0.9 + math.log10(1 + avg_engagement) * 9), 1),
            top=[{"title": f"[offline] {query}", "score": avg_engagement, "comments": 0,
                  "subreddit": "offline", "url": "offline://reddit"}],
        )

    def hot(self, subreddit: str = "all", *, limit: int = 50):
        return []

    # -- competition ------------------------------------------------------
    def competition(self, topic: str) -> CompetitionReport:
        rng = self._rng(f"competition|{topic}")
        results_seen = 30
        listings = rng.randint(0, 22)
        report = CompetitionReport(
            topic=topic,
            listings=listings,
            marketplaces=["Redbubble", "Etsy"][: max(1, listings // 8)],
            results_seen=results_seen,
            design_hits=rng.randint(0, 20),
            examples=["offline://listing"],
        )
        report.competition = round(min(100.0, 100.0 * listings / results_seen * 0.8), 1)
        return report


def market_truth_rehearsal(topic: str):
    """A Market Truth verdict for offline rehearsal — labelled as exactly that.

    Offline mode exists so the whole chain can be exercised without a network or
    a credit. That must not become a way to launder an unproven topic into a
    passed audit, so the verdict says plainly where it came from: no rows were
    fetched, no auditor read anything, and this is not evidence the topic is
    trending or that anyone wants it.
    """
    from .truth import MarketTruth

    subject = " ".join(str(topic).split()) or "rehearsal subject"
    verdict = MarketTruth(topic=subject, passed=True, source="offline-rehearsal")
    verdict.failure = ""
    verdict.reason = (
        "offline rehearsal: no public evidence was fetched and no auditor read anything. "
        "This verdict exercises the chain; it proves nothing about the market."
    )
    verdict.exact_intent = f"rehearsal stand-in for '{subject}' — not an audited meaning"
    verdict.ambiguity = "low"
    verdict.buyer_identity = f"rehearsal audience for {subject}"
    verdict.why_they_care = f"rehearsal: the {subject} carries the load and wear of its own use"
    verdict.why_they_would_wear_it = "rehearsal: identification with a specific made object"
    verdict.nameable_symbol = subject
    verdict.confidence = 0.0
    verdict.independent_domains = []
    verdict.evidence = []
    return verdict
