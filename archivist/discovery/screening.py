"""Screening — what an autonomous bot must refuse to print.

Google Trends' front page is mostly celebrities, sports fixtures, breaking news
and brands. All of those are exactly what you must not put on a shirt: likeness
rights, trademarks, live tragedies. A bot that picks topics on its own needs
this filter more than a human-driven one does, not less.

The checks are deliberately blunt and the reason is always recorded, so a
rejected topic can be reviewed rather than silently disappearing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BRANDS = {
    "nike", "adidas", "puma", "gucci", "prada", "supreme", "apple", "google", "amazon",
    "tesla", "disney", "marvel", "netflix", "pixar", "nintendo", "playstation", "xbox",
    "pokemon", "starbucks", "mcdonalds", "coca cola", "pepsi", "spotify", "tiktok",
    "instagram", "youtube", "openai", "chatgpt", "samsung", "sony", "bmw", "ferrari",
    "lego", "barbie", "hello kitty", "star wars", "harry potter", "minecraft", "roblox",
    "fortnite", "taylor swift", "premier league", "nba", "nfl", "fifa", "uefa", "olympics",
}

FRANCHISE_HINTS = re.compile(
    r"\b(season\s?\d|episode|trailer|movie|film|series|album|tour dates|box office|"
    r"vs\.?|match|fixture|score|highlights|transfer|signing)\b", re.I
)

TRAGEDY = re.compile(
    r"\b(death|dies|died|killed|shooting|shooter|massacre|crash|earthquake|hurricane|"
    r"wildfire|flood|war|bombing|attack|hostage|missing|funeral|obituary|verdict|"
    r"arrested|lawsuit|indicted|overdose|suicide|victims?)\b", re.I
)

POLITICS = re.compile(
    r"\b(election|president|senator|parliament|prime minister|campaign|ballot|impeach|"
    r"protest|immigration raid|deportation|referendum|governor|congress)\b", re.I
)

MEDICAL = re.compile(
    r"\b(cure|cures|treatment|symptoms|diagnosis|vaccine|cancer|covid|outbreak|"
    r"weight loss|ozempic|supplement)\b", re.I
)

ADULT = re.compile(r"\b(porn|nsfw|onlyfans|nude|escort|xxx)\b", re.I)

GAMBLING_FINANCE = re.compile(
    r"\b(casino|betting|odds|crypto pump|pump and dump|stock tip|forex signal)\b", re.I
)

# Words that make a Title Case pair a thing rather than a person.
COMMON_NOUNS = {
    "day", "week", "night", "club", "society", "archive", "museum", "festival", "market",
    "station", "bridge", "tower", "valley", "river", "coast", "island", "forest", "canal",
    "railway", "factory", "mine", "harbour", "harbor", "lighthouse", "observatory", "core",
    "class", "type", "model", "series", "project", "system", "method", "school", "guide",
}


@dataclass
class Screening:
    ok: bool
    category: str = ""
    reason: str = ""

    @property
    def label(self) -> str:
        return "clear" if self.ok else f"rejected: {self.category}"


def looks_like_person(term: str) -> bool:
    """Two or three Title Case words with no common noun — probably somebody's name."""
    words = term.split()
    if not 2 <= len(words) <= 3:
        return False
    if any(word.lower() in COMMON_NOUNS for word in words):
        return False
    return all(word[:1].isupper() and word[1:].islower() and word.isalpha() for word in words)


def screen(topic: str, *, context: str = "", allow_people: bool = False) -> Screening:
    """Decide whether a discovered topic may become a design at all."""
    text = f"{topic} {context}".strip()
    lowered = topic.lower()

    if len(topic.strip()) < 3:
        return Screening(False, "too-short", "not enough of a topic to design around")

    for brand in BRANDS:
        if re.search(rf"\b{re.escape(brand)}\b", lowered):
            return Screening(False, "trademark", f"names a brand or protected property ({brand})")

    if TRAGEDY.search(text):
        return Screening(False, "tragedy", "breaking news or human harm — not a merch subject")
    if POLITICS.search(text):
        return Screening(False, "politics", "live political subject — trademark-free but reputationally hot")
    if MEDICAL.search(text):
        return Screening(False, "health-claim", "health or medical claim — regulated on printed goods")
    if ADULT.search(text):
        return Screening(False, "adult", "adult content")
    if GAMBLING_FINANCE.search(text):
        return Screening(False, "financial", "gambling or financial-advice framing")
    if FRANCHISE_HINTS.search(text):
        return Screening(False, "entertainment-event", "a match, release or episode — someone else owns it")
    if not allow_people and looks_like_person(topic):
        return Screening(False, "likeness", "reads as a person's name — likeness rights")

    return Screening(True)


def screen_all(topics: list[str], contexts: dict[str, str] | None = None) -> dict[str, Screening]:
    contexts = contexts or {}
    return {topic: screen(topic, context=contexts.get(topic, "")) for topic in topics}
