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

ANCHORS = [
    "industrial archaeology", "obsolete technology", "field documentation",
    "scientific instruments", "maritime infrastructure", "hydrographic survey",
    "railway signal maintenance", "public works archive", "geological fieldwork",
    "meteorological records", "analog communication", "museum cataloguing",
    "archive conservation", "industrial typography", "expedition logbook",
    "machine identification plates", "cartographic field notes", "port logistics",
    "laboratory documentation", "material culture archive", "amateur radio logbook",
    "underwater archaeology", "urban infrastructure", "technical manual archive",
]

CURATED_TOPICS = [
    "weather balloon telemetry", "hydrographic survey instruments",
    "railway signal maintenance", "industrial archaeology field notes",
    "subsea cable mapping", "oceanographic specimen records",
    "lighthouse lens mechanics", "seismic monitoring stations",
    "geological core sampling", "analog telephone exchange schematics",
    "harbor crane engineering", "tide gauge records",
    "meteorological observation logs", "field recording equipment",
    "bridge inspection markings", "cold storage logistics",
    "shipyard riveting methods", "mine ventilation diagrams",
    "public works identification plates", "cartographic error studies",
    "botanical specimen cataloguing", "archive conservation tools",
    "industrial control room notation", "photogrammetry field survey",
    "deep sea salvage records", "observatory photographic plates",
    "port cargo classification codes", "railway timetable typography",
    "obsolete computing maintenance", "amateur radio signal logs",
    "municipal water infrastructure", "aeronautical maintenance records",
]

# Broad one- and two-word roots, which is what Google Trends can actually compare.
VOLUME_ROOTS = [
    "archaeology", "cartography", "telemetry", "hydrography", "oceanography",
    "meteorology", "seismology", "geology", "surveying", "infrastructure",
    "shipyard", "lighthouse", "railway", "radar", "sonar", "navigation",
    "aviation", "typography", "fieldwork", "observatory", "laboratory",
    "microscopy", "conservation", "restoration", "foundry", "mining",
    "machinery", "engineering", "schematics", "logistics", "harbor",
    "canals", "tunnels", "bridges", "satellites", "robotics", "analog",
    "fossils", "minerals", "specimens", "industrial archaeology",
    "technical manuals", "field notes", "weather balloon", "tide gauge",
    "public works", "maritime history", "analog computing", "signal tower",
    "railway signals", "ocean mapping", "marine survey", "core sampling",
    "amateur radio", "cold storage", "port logistics", "material culture",
    "scientific instruments", "archival science", "machine plates",
    "control room", "civil engineering", "urban systems", "deep sea",
    "salvage diving", "geological survey", "botanical archive", "industrial design",
]

HOUSE_TERMS = [
    "archive", "archival", "industrial", "infrastructure", "field", "survey",
    "instrument", "scientific", "specimen", "catalog", "logbook", "record",
    "telemetry", "signal", "railway", "maritime", "harbor", "port",
    "subsea", "oceanographic", "geological", "meteorological", "observatory",
    "cartographic", "photogrammetry", "archaeology", "conservation", "obsolete",
    "analog", "machine", "maintenance", "engineering", "technical", "manual",
    "laboratory", "public works", "material culture", "typography", "schematic",
]

QUERY_NOISE = [
    "near me", "open today", "how to", "what is", "for sale", "amazon",
    "template", "maker", "quiz", "standings", "celebrity", "portrait",
]


def house_fit(topic: str, source: str = "") -> float:
    """0–10: can the house actually make something out of this?"""
    lowered = topic.lower()
    if any(noise in lowered for noise in QUERY_NOISE):
        return 0.0
    matches = sum(1 for term in HOUSE_TERMS if term in lowered)
    score = min(10.0, 4.0 + matches * 1.15)
    if source in {"curated", "llm-targeted"}:
        score = max(score, 8.2)
    return round(score, 2)


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
