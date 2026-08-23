"""Turning raw signals into an opportunity score.

The brief is explicit about what a good topic looks like: **rising hard over the
last three months, hot on Reddit/X/Meta, high average engagement, few
competitors.** Those are the four heavy axes here; apparel fit and cross-source
confirmation are the tie-breakers.

Hard filters run before scoring, because a topic that fails one of them is not a
low-scoring opportunity — it is not an opportunity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import OpportunityScores, TopicOpportunity


@dataclass
class Thresholds:
    """A topic must clear all of these to be offered at all."""

    min_growth: float = 25.0        # % over three months
    max_competition: float = 70.0   # 0..100 crowding
    min_social: float = 12.0        # 0..100 combined social heat
    min_interest: float = 3.0       # mean Trends index — below this it is noise
    min_sources: int = 2            # independent sources that answered

    def failures(self, opportunity: TopicOpportunity) -> list[str]:
        problems: list[str] = []
        if opportunity.growth_3m < self.min_growth and not opportunity.breakout:
            problems.append(f"growth {opportunity.growth_3m:+.0f}% below the {self.min_growth:.0f}% floor")
        if opportunity.competition > self.max_competition:
            problems.append(f"competition {opportunity.competition:.0f}/100 above the {self.max_competition:.0f} ceiling")
        if opportunity.social_heat < self.min_social:
            problems.append(f"social heat {opportunity.social_heat:.0f} below the {self.min_social:.0f} floor")
        if opportunity.interest_mean and opportunity.interest_mean < self.min_interest:
            problems.append(f"search interest {opportunity.interest_mean:.1f} is statistical noise")
        if len(opportunity.sources) < self.min_sources:
            problems.append(f"only {len(opportunity.sources)} source(s) could measure it")
        return problems


def growth_score(growth_pct: float, *, breakout: bool = False, momentum: float = 0.0) -> float:
    """0..10 from a percentage rise, saturating so a 900% blip cannot dominate."""
    if growth_pct <= 0:
        base = max(0.0, 3.0 + growth_pct / 30.0)     # a decline still scores, badly
    else:
        base = 3.0 + 7.0 * min(1.0, math.log10(1 + growth_pct) / math.log10(1 + 250))
    if breakout:
        base += 1.0
    if momentum > 20:
        base += 0.5      # still accelerating, not just already risen
    elif momentum < -25:
        base -= 1.0      # the peak has passed
    return round(max(0.0, min(10.0, base)), 2)


def engagement_score(avg_engagement: float, *, ceiling: float = 4000.0) -> float:
    """0..10, log-scaled: social engagement is heavy-tailed."""
    if avg_engagement <= 0:
        return 0.0
    return round(min(10.0, 10.0 * math.log10(1 + avg_engagement) / math.log10(1 + ceiling)), 2)


def competition_gap_score(competition: float) -> float:
    """0..100 crowding inverted into a 0..10 gap, with a steeper penalty when crowded."""
    gap = max(0.0, 100.0 - competition) / 10.0
    if competition > 55:
        gap *= 0.75
    return round(min(10.0, gap), 2)


def apparel_fit_default(opportunity: TopicOpportunity) -> float:
    """A neutral prior for wearability when no LLM judgement is available.

    Objects, places and practices wear well; single-word abstractions and things
    that only exist as news do not.
    """
    words = opportunity.topic.split()
    fit = 6.5
    if len(words) >= 2:
        fit += 0.5                       # a phrase gives an art director more to hold
    if len(words) > 5:
        fit -= 1.0                       # too long to become a graphic
    if any(char.isdigit() for char in opportunity.topic):
        fit -= 0.5
    if opportunity.rising_queries:
        fit += 0.5                       # a vocabulary around it means visual material exists
    return round(max(0.0, min(10.0, fit)), 2)


def score(
    opportunity: TopicOpportunity,
    *,
    thresholds: Thresholds | None = None,
    apparel_fit: float | None = None,
    max_sources: int = 4,
) -> TopicOpportunity:
    """Fill in ``opportunity.scores`` and the accept/reject verdict."""
    thresholds = thresholds or Thresholds()

    scores = OpportunityScores(
        growth=growth_score(opportunity.growth_3m, breakout=opportunity.breakout,
                            momentum=opportunity.momentum),
        social=round(min(10.0, opportunity.social_heat / 10.0), 2),
        engagement=engagement_score(opportunity.avg_engagement),
        competition_gap=competition_gap_score(opportunity.competition),
        apparel_fit=apparel_fit if apparel_fit is not None else apparel_fit_default(opportunity),
        confirmation=round(min(10.0, 10.0 * len(opportunity.sources) / max_sources), 2),
    )
    opportunity.scores = scores

    problems = thresholds.failures(opportunity)
    if problems and opportunity.accepted:
        opportunity.accepted = False
        opportunity.rejected_reason = "; ".join(problems)
    return opportunity


def rank(opportunities: list[TopicOpportunity]) -> list[TopicOpportunity]:
    """Accepted first, then by overall score, then by how recent the momentum is."""
    return sorted(
        opportunities,
        key=lambda item: (not item.accepted, -item.overall, -item.momentum),
    )
