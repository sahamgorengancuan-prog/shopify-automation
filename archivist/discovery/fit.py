"""How well a discovered topic fits the house — and how to score it when the
signal sources are only partly available.

Two ideas live here:

* **fit** — the house makes designs about built, measured, material things. A
  topic that is a shopping query, a celebrity or a generic aesthetic scores zero
  no matter how well it is trending.
* **adaptive scoring** — the standard opportunity score assumes every source
  answered. In the field they often do not (Trends throttles, Reddit 403s from a
  datacentre IP), so this reweights over the sources that *did* answer instead of
  punishing a topic for the network.
"""

from __future__ import annotations

import math

from .models import TopicOpportunity
from .scoring import competition_gap_score, growth_score

TARGET_PROFILE = (
    "ARCHIVIST apparel: real industrial, scientific, maritime, infrastructure, field-research, "
    "obsolete-technology and material-culture subjects transformed into quiet asymmetric abstraction. "
    "The visual mass is deliberately off-centre; empty garment space carries meaning. No document aesthetic."
)

# V10.1 §2.1: autonomous discovery may not start from a house-preferred list.
# The volume tool still exists, but as a diagnostic the caller supplies roots to
# — never as a seed pool that quietly decides what the bot is "interested in".
VOLUME_ROOTS: list[str] = []

# Things that are not designable subjects at all, whatever they score. This is
# hygiene, not taste: a shopping query has no object behind it, a person is not
# ours to print, and a bare aesthetic label names a mood rather than a thing.
QUERY_NOISE = [
    "near me", "open today", "how to", "what is", "for sale", "amazon",
    "template", "maker", "quiz", "standings", "celebrity", "portrait",
    "discount", "coupon", "cheap", "buy ", "reviews", "vs ", "net worth",
    "lyrics", "showtimes", "score", "results", "login", "download",
]

# A designable topic points at something with a physical referent. These are
# structural cues, deliberately not a taste profile: "society", "method" and
# "species" are as welcome as "instrument".
CONCRETE_CUES = [
    "instrument", "machine", "structure", "tool", "vessel", "station", "system",
    "material", "method", "technique", "craft", "species", "specimen", "record",
    "archive", "survey", "process", "equipment", "device", "practice", "society",
    "club", "guild", "workshop", "restoration", "collection", "fieldwork",
]


def topic_hygiene(topic: str, source: str = "") -> float:
    """0–10: is this a designable subject at all?

    V10.1 forbids the house from boosting its own preferred nouns here — that is
    how a curated aesthetic quietly became "discovery". This asks only whether a
    topic has a physical referent something could be drawn of. Whether anyone
    wants to wear it is decided later, by the Market Truth gate, on evidence.
    """
    lowered = f" {str(topic).lower().strip()} "
    if any(noise in lowered for noise in QUERY_NOISE):
        return 0.0
    words = lowered.split()
    if not words or len(lowered.strip()) < 3:
        return 0.0

    score = 5.0
    if any(cue in lowered for cue in CONCRETE_CUES):
        score += 1.6
    if 2 <= len(words) <= 5:
        score += 0.8            # a phrase is usually more specific than a bare word
    if any(character.isdigit() for character in lowered):
        score -= 1.0            # model numbers and dates are usually news, not subjects
    return round(max(0.0, min(10.0, score)), 2)


# Kept so older callers keep working; the boost they relied on is gone.
house_fit = topic_hygiene


def adaptive_score(opportunity: TopicOpportunity, fit: float) -> float:
    """Weighted over the sources that answered, not over the sources we wanted."""
    weighted: list[tuple[float, float]] = [(fit, 0.42)]
    answered = {signal.source for signal in opportunity.signals if signal.ok}

    if "google_trends" in answered:
        interest = min(10.0, opportunity.interest_mean / 4.0)
        demand = max(
            growth_score(opportunity.growth_3m, breakout=opportunity.breakout, momentum=opportunity.momentum),
            interest,
        )
        weighted.append((demand, 0.28))
    if "duckduckgo" in answered:
        weighted.append((competition_gap_score(opportunity.competition), 0.22))
    if answered & {"reddit", "x", "meta"}:
        social = min(10.0, opportunity.social_heat / 10.0)
        engagement = min(10.0, math.log10(1 + opportunity.avg_engagement) * 2.7)
        weighted.append((max(social, engagement), 0.18))

    weighted.append((min(10.0, len(opportunity.sources) * 2.5), 0.08))
    total_weight = sum(weight for _, weight in weighted)
    return round(sum(value * weight for value, weight in weighted) / total_weight, 2)
