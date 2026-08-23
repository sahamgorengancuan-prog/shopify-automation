"""Autonomous topic discovery.

The bot finds its own subject: Google Trends for demand and three-month growth,
Reddit / X / Meta for whether anyone actually cares, DuckDuckGo for how crowded
the apparel market already is, and the LLM for wearability, angle and risk.

    from archivist.discovery import DiscoveryEngine
    report = DiscoveryEngine(settings, llm=llm).discover(count=5)
    for opportunity in report.opportunities:
        print(opportunity.summary())
"""

from __future__ import annotations

from .competition import CompetitionReport, measure as measure_competition
from .correlation import affinity, correlate, pearson
from .engine import DEFAULT_ANCHORS, DiscoveryConfig, DiscoveryEngine, latest_report
from .google_trends import GoogleTrends, InterestSeries, RisingQuery
from .models import DiscoveryReport, OpportunityScores, Seed, Signal, TopicOpportunity
from .offline import OfflineSignals
from .reddit import Reddit, RedditHeat
from .scoring import Thresholds, rank, score
from .screening import Screening, screen
from .social import MetaSignals, SocialHeat, XSignals

__all__ = [
    "CompetitionReport", "measure_competition",
    "affinity", "correlate", "pearson",
    "DEFAULT_ANCHORS", "DiscoveryConfig", "DiscoveryEngine", "latest_report",
    "GoogleTrends", "InterestSeries", "RisingQuery",
    "DiscoveryReport", "OpportunityScores", "Seed", "Signal", "TopicOpportunity",
    "OfflineSignals",
    "Reddit", "RedditHeat",
    "Thresholds", "rank", "score",
    "Screening", "screen",
    "MetaSignals", "SocialHeat", "XSignals",
]
