"""Stage 1 — turn a raw topic into a micro-niche (section 15).

The escalation is deliberate: a literal trend is a crowded market, a micro-niche
with an implied institution behind it is not. Everything is derived
deterministically from the topic + seed so a run can be reproduced, with an
optional LLM assist layered on top when a key is available.
"""

from __future__ import annotations

import random
import re
import unicodedata

from .models import NicheLadder

STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "for", "with", "in", "on", "to", "at",
    "vs", "by", "from", "into", "about",
}

# Lenses that reframe a subject as a documented artefact rather than a picture of a thing.
INSTITUTIONS = [
    "Cultural Archive", "Field Survey", "Records Office", "Specimen Registry",
    "Documentation Unit", "Forensic Archive", "Observation Bureau", "Preservation Society",
    "Index Department", "Research Station", "Evidence Library", "Standards Institute",
]

ERAS = [
    "1960s institutional", "1970s state-issue", "1980s analogue", "1990s photocopy-era",
    "Cold War", "post-industrial", "pre-digital", "early-broadcast", "millennial-archive",
    "contemporary declassified",
]

GEOGRAPHIES = [
    "Eastern Bloc", "North Sea", "Trans-Pacific", "Municipal", "Federal",
    "Provincial", "Continental", "Off-Grid", "Port Authority", "Border Region",
]

MEDIUMS = [
    "microfilm", "contact sheet", "photocopy", "photographic plate", "index card",
    "telex printout", "ledger page", "carbon copy", "field notebook", "slide mount",
]

CULTURAL_LENSES = [
    "institutional memory", "evidence and proof", "preservation vs. decay",
    "the bureaucracy of meaning", "declassification", "amateur documentation",
    "what gets kept and what gets discarded", "the record outliving the event",
    "classification as a form of authorship", "the last analogue witness",
]

AGGRESSION_NOTES = {
    0: "restrained — the archive is legible and calm",
    3: "measured — one disruptive element per layout",
    5: "assertive — layered documentation, visible process",
    8: "loud — heavy redaction, stamped surfaces, aggressive cropping",
    10: "hostile — the document actively resists being read",
}


def slugify(value: str, max_length: int = 60) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return (value or "untitled")[:max_length].strip("-")


def keywords(topic: str, limit: int = 6) -> list[str]:
    """Content words of a topic, order preserved, duplicates removed."""
    tokens = [t for t in re.split(r"[^a-zA-Z0-9']+", topic.lower()) if t]
    out: list[str] = []
    for token in tokens:
        if token in STOPWORDS or len(token) < 2:
            continue
        if token not in out:
            out.append(token)
    return out[:limit]


def headline(topic: str) -> str:
    """Topic as a display string — title case but acronyms kept intact."""
    words = []
    for word in topic.split():
        words.append(word if word.isupper() and len(word) > 1 else word.capitalize())
    return " ".join(words)


def aggression_note(level: int) -> str:
    keys = sorted(AGGRESSION_NOTES)
    closest = min(keys, key=lambda k: abs(k - level))
    return AGGRESSION_NOTES[closest]


def derive_ladder(
    topic: str,
    *,
    audience: str = "",
    aggressiveness: int = 5,
    seed: int = 0,
    llm=None,
) -> NicheLadder:
    """Build the four-rung niche ladder plus the cultural signals behind it."""
    rng = random.Random(f"{topic}|{seed}|{aggressiveness}")
    display = headline(topic)
    institution = rng.choice(INSTITUTIONS)
    era = rng.choice(ERAS)
    geography = rng.choice(GEOGRAPHIES)
    lenses = rng.sample(CULTURAL_LENSES, k=3)

    ladder = NicheLadder(
        trend=display,
        generic=f"{display} T-Shirt",
        better=f"{display} Documentation",
        niche=f"{era.title()} {display} Archive",
        micro_niche=f"{geography} {era.title()} {display} {institution}",
        cultural_signals=[
            f"Subject read through {lenses[0]}",
            f"Secondary tension: {lenses[1]}",
            f"Undertone: {lenses[2]}",
            f"Framing device: {rng.choice(MEDIUMS)} as the carrier of the image",
            f"Intensity: {aggression_note(aggressiveness)}",
        ],
        audience=audience or "collectors of design-literate streetwear; archive/documentary aesthetic readers",
    )

    if llm is not None and llm.available:
        refined = llm.refine_ladder(ladder, topic=topic, audience=audience)
        if refined is not None:
            ladder = refined
    return ladder


def topic_vocabulary(topic: str, ladder: NicheLadder, seed: int = 0) -> dict[str, list[str]]:
    """The word pools the query generator draws from, biased by the ladder."""
    rng = random.Random(f"vocab|{topic}|{seed}")
    words = keywords(topic) or [slugify(topic).replace("-", " ")]
    return {
        "topic_terms": words,
        "topic": [topic],
        "era": rng.sample(ERAS, k=min(5, len(ERAS))),
        "geography": rng.sample(GEOGRAPHIES, k=min(5, len(GEOGRAPHIES))),
        "medium": rng.sample(MEDIUMS, k=min(6, len(MEDIUMS))),
        "institution": rng.sample(INSTITUTIONS, k=min(5, len(INSTITUTIONS))),
        "niche": [ladder.niche, ladder.micro_niche],
    }
