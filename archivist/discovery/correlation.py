"""Correlation — which discovered topics are actually the same wave.

Two things are computed:

* **timeline correlation** — Pearson r between two topics' Google Trends series.
  Topics that rise together are one cultural movement, and a collection built
  from a correlated family reads as deliberate instead of scattered.
* **semantic overlap** — shared tokens and shared rising queries, which catches
  co-movement that the timelines are too short or too noisy to show.

The two are blended, then a threshold groups topics into families named after
the strongest member.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

from .models import TopicOpportunity

STOPWORDS = {"the", "and", "for", "with", "from", "that", "this", "you", "your", "how", "why", "new"}


def pearson(a: list[float], b: list[float]) -> float:
    """Pearson r over the overlapping tail of two series (0.0 when undefined)."""
    length = min(len(a), len(b))
    if length < 6:
        return 0.0
    x, y = a[-length:], b[-length:]
    mean_x, mean_y = sum(x) / length, sum(y) / length
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
    var_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
    if var_x == 0 or var_y == 0:
        return 0.0
    return round(cov / (var_x * var_y), 3)


def _tokens(text: str) -> set[str]:
    words = {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 2}
    return words - STOPWORDS


def semantic_overlap(a: TopicOpportunity, b: TopicOpportunity) -> float:
    """0..1 shared vocabulary.

    Topic phrases are compared by containment — "analogue photography revival"
    and "analogue photography gear" are the same subject even though Jaccard
    over four-word sets would call them distant. Rising queries, which are long
    and noisy lists, are compared by Jaccard.
    """
    topic_a, topic_b = _tokens(a.topic), _tokens(b.topic)
    containment = 0.0
    if topic_a and topic_b:
        containment = len(topic_a & topic_b) / min(len(topic_a), len(topic_b))

    queries_a = {token for query in a.rising_queries for token in _tokens(query)}
    queries_b = {token for query in b.rising_queries for token in _tokens(query)}
    jaccard = 0.0
    if queries_a and queries_b:
        jaccard = len(queries_a & queries_b) / len(queries_a | queries_b)

    return round(max(containment, jaccard), 3)


def _differences(series: list[float]) -> list[float]:
    """Week-on-week change. Correlating raw levels just proves both went up."""
    return [second - first for first, second in zip(series, series[1:])]


def affinity(a: TopicOpportunity, b: TopicOpportunity) -> float:
    """Blended 0..1 relatedness — co-movement first, shared vocabulary second.

    Correlation is measured on first differences, so two unrelated topics that
    merely happen to be rising do not read as the same wave; and a link needs
    either some shared vocabulary or near-lockstep movement, which stops a whole
    discovery cycle collapsing into one family.
    """
    words = semantic_overlap(a, b)
    if not a.timeline or not b.timeline:
        return words

    shape = max(0.0, pearson(_differences(a.timeline), _differences(b.timeline)))
    if words >= 0.34:
        # Clearly the same subject; the timelines can only strengthen the link.
        return round(max(words, 0.55 * shape + 0.45 * words), 3)
    if shape >= 0.75:
        return round(shape, 3)          # moving in lockstep is a link on its own
    if words < 0.05:
        return 0.0                      # unrelated words and merely-both-rising
    return round(0.55 * shape + 0.45 * words, 3)


def correlate(
    opportunities: Iterable[TopicOpportunity],
    *,
    threshold: float = 0.45,
    max_links: int = 4,
    max_family: int = 5,
) -> dict[str, list[str]]:
    """Annotate each opportunity with its correlates and group them into families.

    Returns ``{family_name: [topic, ...]}``. Single-topic families are kept —
    a lone strong signal is still a collection of one.
    """
    items = list(opportunities)
    for item in items:
        item.correlated_with = []
        item.family = ""

    pairs: list[tuple[float, TopicOpportunity, TopicOpportunity]] = []
    for index, first in enumerate(items):
        for second in items[index + 1 :]:
            score = affinity(first, second)
            if score >= threshold:
                pairs.append((score, first, second))

    for score, first, second in sorted(pairs, key=lambda row: -row[0]):
        if len(first.correlated_with) < max_links and second.topic not in first.correlated_with:
            first.correlated_with.append(second.topic)
        if len(second.correlated_with) < max_links and first.topic not in second.correlated_with:
            second.correlated_with.append(first.topic)

    # Families form around leaders rather than by transitive closure: chaining
    # A~B~C~D collapses a whole cycle into one meaningless "family", which is
    # exactly what you do not want when the families become collections.
    by_topic = {item.topic: item for item in items}
    linked: dict[str, list[tuple[float, str]]] = {item.topic: [] for item in items}
    for score, first, second in pairs:
        linked[first.topic].append((score, second.topic))
        linked[second.topic].append((score, first.topic))

    families: dict[str, list[str]] = {}
    claimed: set[str] = set()
    for leader in sorted(items, key=lambda item: -item.overall):
        if leader.topic in claimed:
            continue
        members = [leader]
        claimed.add(leader.topic)
        for _score, topic in sorted(linked[leader.topic], key=lambda row: -row[0]):
            if topic in claimed or len(members) >= max_family:
                continue
            claimed.add(topic)
            members.append(by_topic[topic])

        name = leader.topic if len(members) == 1 else f"{leader.topic} family"
        for member in members:
            member.family = name
        families[name] = [member.topic for member in sorted(members, key=lambda i: -i.overall)]
    return families
