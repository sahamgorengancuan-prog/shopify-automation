"""Data model for autonomous topic discovery.

Nothing here is a guess: every number carries the source that produced it and a
human-readable detail string, so a discovered topic can always be audited back
to the request that measured it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Signal:
    """One measurement from one source."""

    source: str          # google_trends | reddit | x | meta | duckduckgo | offline
    metric: str          # growth_3m | momentum | heat | avg_engagement | competition | ...
    value: float
    detail: str = ""
    ok: bool = True      # False = the source could not answer (missing key, blocked)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "metric": self.metric,
            "value": round(self.value, 3),
            "detail": self.detail,
            "ok": self.ok,
        }


@dataclass
class Seed:
    """A raw candidate term before it has been measured."""

    term: str
    source: str
    context: str = ""
    weight: float = 1.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"term": self.term, "source": self.source, "context": self.context, "weight": self.weight}


@dataclass
class OpportunityScores:
    """The five axes the brief asks for, plus how well it wears.

    growth        rise over the last three months
    social        how hot it is on Reddit / X / Meta right now
    engagement    average engagement per post — "average views high"
    competition   *gap*: 10 means nobody is selling this yet
    apparel_fit   can this become a wearable graphic at all
    """

    growth: float = 0.0
    social: float = 0.0
    engagement: float = 0.0
    competition_gap: float = 0.0
    apparel_fit: float = 0.0
    confirmation: float = 0.0   # how many independent sources agree

    WEIGHTS = {
        "growth": 0.28,
        "social": 0.20,
        "engagement": 0.15,
        "competition_gap": 0.22,
        "apparel_fit": 0.10,
        "confirmation": 0.05,
    }

    @property
    def overall(self) -> float:
        return round(sum(getattr(self, key) * weight for key, weight in self.WEIGHTS.items()), 2)

    def to_dict(self) -> dict[str, Any]:
        data = {key: round(getattr(self, key), 1) for key in self.WEIGHTS}
        data["overall"] = self.overall
        return data


@dataclass
class TopicOpportunity:
    """A candidate topic with every signal that was measured about it."""

    topic: str
    seeds: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    # --- raw measurements ------------------------------------------------
    growth_3m: float = 0.0          # % change, last 4 weeks vs first 4 weeks of a 3-month window
    momentum: float = 0.0           # % change, last 2 weeks vs the 6 before them
    interest_mean: float = 0.0      # 0..100 Google Trends index
    peak_ratio: float = 0.0         # latest / peak — 1.0 means it is peaking now
    breakout: bool = False          # Google Trends flagged it as a breakout rising query
    social_heat: float = 0.0        # 0..100 composite of Reddit / X / Meta
    avg_engagement: float = 0.0     # average engagement per post on the hottest platform
    posts_seen: int = 0
    competition: float = 0.0        # 0..100, higher = more crowded on the apparel marketplaces
    listings_seen: int = 0

    # --- derived ---------------------------------------------------------
    timeline: list[float] = field(default_factory=list)
    rising_queries: list[str] = field(default_factory=list)
    correlated_with: list[str] = field(default_factory=list)
    family: str = ""
    scores: OpportunityScores = field(default_factory=OpportunityScores)
    signals: list[Signal] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    # --- judgement -------------------------------------------------------
    angle: str = ""                 # the design angle the LLM proposes
    audience: str = ""
    durability: str = ""            # fad | seasonal | lasting
    risk: str = ""                  # trademark / likeness / taste concerns
    accepted: bool = True
    rejected_reason: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def overall(self) -> float:
        return self.scores.overall

    def add(self, signal: Signal) -> None:
        self.signals.append(signal)
        if signal.ok and signal.source not in self.sources:
            self.sources.append(signal.source)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scores"] = self.scores.to_dict()
        data["signals"] = [s.to_dict() for s in self.signals]
        data["overall"] = self.overall
        return data

    def summary(self) -> str:
        return (
            f"{self.topic} — growth {self.growth_3m:+.0f}%, social {self.social_heat:.0f}/100, "
            f"engagement {self.avg_engagement:.0f}/post, competition {self.competition:.0f}/100, "
            f"score {self.overall}"
        )


@dataclass
class DiscoveryReport:
    """One discovery cycle, start to finish."""

    created_at: str = ""
    geo: str = ""
    timeframe: str = ""
    seeds: list[Seed] = field(default_factory=list)
    measured: int = 0
    opportunities: list[TopicOpportunity] = field(default_factory=list)
    rejected: list[TopicOpportunity] = field(default_factory=list)
    families: dict[str, list[str]] = field(default_factory=dict)
    source_status: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    duration_s: float = 0.0

    @property
    def best(self) -> TopicOpportunity | None:
        return self.opportunities[0] if self.opportunities else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "geo": self.geo,
            "timeframe": self.timeframe,
            "seeds": [s.to_dict() for s in self.seeds],
            "measured": self.measured,
            "opportunities": [o.to_dict() for o in self.opportunities],
            "rejected": [o.to_dict() for o in self.rejected],
            "families": self.families,
            "source_status": self.source_status,
            "warnings": self.warnings,
            "duration_s": round(self.duration_s, 1),
        }

    def table_rows(self) -> list[list[Any]]:
        """Rows for the Gradio opportunity table."""
        return [
            [
                index,
                opportunity.topic,
                round(opportunity.overall, 2),
                f"{opportunity.growth_3m:+.0f}%",
                round(opportunity.social_heat),
                round(opportunity.avg_engagement),
                round(opportunity.competition),
                opportunity.durability or "—",
                ", ".join(opportunity.sources) or "—",
                opportunity.family or "—",
            ]
            for index, opportunity in enumerate(self.opportunities, 1)
        ]
