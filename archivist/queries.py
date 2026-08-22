"""Stage 2 — search query generation (sections 3 and 16).

Rules enforced here:
  * never search only the user's keyword;
  * every cluster (A..F) is represented;
  * queries must differ by more than a synonym — near-duplicates are dropped
    with a token-overlap check, which is what kills the classic
    "forensic image / forensic photos / forensic photography" failure mode.
"""

from __future__ import annotations

import random

from .models import Cluster, SearchQuery
from .trends import NicheLadder, keywords, topic_vocabulary

# {topic} is the raw topic, {term} a single content word, and the rest come from
# the vocabulary pools in trends.topic_vocabulary().
TEMPLATES: dict[Cluster, list[str]] = {
    Cluster.LITERAL: [
        "{topic}",
        "{topic} close up detail",
        "{term} equipment photograph",
        "{topic} in use documentary photograph",
        "{term} object study neutral background",
        "{topic} {medium}",
    ],
    Cluster.ARCHIVAL: [
        "{era} {topic} archival photograph",
        "{geography} state archive {term}",
        "declassified {term} document scan",
        "{topic} museum collection catalogue photograph",
        "vintage {term} institutional record",
        "{term} historical survey photograph {era}",
    ],
    Cluster.LANGUAGE: [
        "{term} scientific illustration plate",
        "brutalist graphic design {term}",
        "editorial photography {topic} magazine spread",
        "technical diagram {term} exploded view",
        "documentary photography {topic} black and white",
        "{institution} report cover design",
    ],
    Cluster.TEXTURE: [
        "photocopy degraded texture high contrast",
        "{medium} surface texture scan",
        "film grain black and white 35mm negative",
        "halftone dot print detail macro",
        "archival paper foxing stains texture",
        "scratched photographic emulsion damage",
    ],
    Cluster.TYPOGRAPHY: [
        "institutional document typography specimen",
        "condensed grotesk poster typography black and white",
        "monospaced typewriter form printed label",
        "government archive stamp and label typography",
        "scientific poster typography grid layout",
        "{era} technical manual page typography",
    ],
    Cluster.COMPOSITION: [
        "archival contact sheet layout",
        "specimen sheet layout grid documentation",
        "evidence board arrangement photograph",
        "museum catalogue page layout photography",
        "field guide plate layout illustration",
        "{institution} data sheet layout print",
    ],
}

INTENTS: dict[Cluster, str] = {
    Cluster.LITERAL: "what the subject actually looks like",
    Cluster.ARCHIVAL: "how the subject was recorded historically",
    Cluster.LANGUAGE: "the graphic dialect the design will speak",
    Cluster.TEXTURE: "the physical surface the artwork pretends to live on",
    Cluster.TYPOGRAPHY: "how type behaves as a graphic system, not as decoration",
    Cluster.COMPOSITION: "the layout skeleton the artwork inherits",
}

# Slightly more weight on the clusters that carry the visual system, because
# subject imagery is the easy part and the differentiator is everything else.
CLUSTER_QUOTA = {
    Cluster.LITERAL: 0.18,
    Cluster.ARCHIVAL: 0.18,
    Cluster.LANGUAGE: 0.18,
    Cluster.TEXTURE: 0.16,
    Cluster.TYPOGRAPHY: 0.15,
    Cluster.COMPOSITION: 0.15,
}


def _tokens(text: str) -> set[str]:
    return {t for t in text.lower().replace("-", " ").split() if len(t) > 2}


def _too_similar(candidate: str, existing: list[str], threshold: float = 0.62) -> bool:
    cand = _tokens(candidate)
    if not cand:
        return True
    for other in existing:
        other_tokens = _tokens(other)
        if not other_tokens:
            continue
        overlap = len(cand & other_tokens) / len(cand | other_tokens)
        if overlap >= threshold:
            return True
    return False


def generate_queries(
    topic: str,
    ladder: NicheLadder,
    *,
    count: int = 24,
    seed: int = 0,
    llm=None,
) -> list[SearchQuery]:
    """Return ``count`` (clamped to 10..30) varied queries across all six clusters."""
    count = max(10, min(30, count))
    rng = random.Random(f"queries|{topic}|{seed}")
    vocab = topic_vocabulary(topic, ladder, seed=seed)
    terms = vocab["topic_terms"] or keywords(topic) or [topic]

    queries: list[SearchQuery] = []
    seen: list[str] = []

    def add(text: str, cluster: Cluster) -> bool:
        text = " ".join(text.split()).strip()
        if not text or _too_similar(text, seen):
            return False
        seen.append(text)
        queries.append(SearchQuery(text=text, cluster=cluster, intent=INTENTS[cluster]))
        return True

    # Guarantee one query per cluster before filling the quota.
    for cluster, templates in TEMPLATES.items():
        for template in rng.sample(templates, k=len(templates)):
            filled = template.format(
                topic=topic,
                term=rng.choice(terms),
                era=rng.choice(vocab["era"]),
                geography=rng.choice(vocab["geography"]),
                medium=rng.choice(vocab["medium"]),
                institution=rng.choice(vocab["institution"]),
            )
            if add(filled, cluster):
                break

    # Fill the remainder proportionally, with a bounded number of attempts so a
    # narrow topic can never spin here.
    attempts = 0
    while len(queries) < count and attempts < count * 25:
        attempts += 1
        cluster = rng.choices(list(CLUSTER_QUOTA), weights=list(CLUSTER_QUOTA.values()))[0]
        template = rng.choice(TEMPLATES[cluster])
        filled = template.format(
            topic=topic,
            term=rng.choice(terms),
            era=rng.choice(vocab["era"]),
            geography=rng.choice(vocab["geography"]),
            medium=rng.choice(vocab["medium"]),
            institution=rng.choice(vocab["institution"]),
        )
        add(filled, cluster)

    if llm is not None and llm.available:
        extra = llm.extra_queries(topic=topic, ladder=ladder, existing=[q.text for q in queries])
        for text, cluster in extra:
            if len(queries) >= 30:
                break
            add(text, cluster)

    return queries[:count]


def cluster_summary(queries: list[SearchQuery]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for query in queries:
        counts[query.cluster.value] = counts.get(query.cluster.value, 0) + 1
    return dict(sorted(counts.items()))
