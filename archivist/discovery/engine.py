"""The autonomous discovery engine.

This is the part that makes the system a bot rather than a tool: nobody types a
topic. The engine harvests candidates, measures each one against four
independent services, throws away everything it must not print, scores what is
left on growth / social heat / engagement / competition, works out which
survivors are the same cultural wave, and hands the pipeline a ranked list.

    harvest → screen → expand → measure → screen again → score → correlate → judge → rank

Every stage degrades: with no keys at all it runs on offline signals, with only
Google Trends reachable it says so in ``source_status`` and scores on what it
has, and a topic that no source could measure is rejected rather than guessed at.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from ..models import dump_json
from ..sources.duckduckgo import DuckDuckGoImages, DuckDuckGoText
from . import competition as competition_mod
from . import correlation, screening
from .google_trends import GoogleTrends
from .models import DiscoveryReport, Seed, Signal, TopicOpportunity
from .offline import OfflineSignals
from .reddit import Reddit
from .scoring import Thresholds, rank, score
from .social import MetaSignals, XSignals


class _SkippedReddit:
    """Stands in for Reddit when anonymous access is knowingly unavailable."""

    name = "reddit"
    authenticated = False

    def heat(self, query: str, **_kwargs):
        from .reddit import RedditHeat

        return RedditHeat(
            query=query, ok=False,
            error="anonymous Reddit disabled (set REDDIT_CLIENT_ID/SECRET or ARCHIVIST_REDDIT_ANONYMOUS=1)",
        )

    def hot(self, subreddit: str = "all", **_kwargs):
        return []

Progress = Callable[[float, str], None]
Log = Callable[[str], None]
Cancel = Callable[[], bool]

# Anchors used to pull rising queries out of Google Trends. They are broad
# enough to catch a wave early and neutral enough not to bias the aesthetic.
DEFAULT_ANCHORS = [
    "aesthetic", "subculture", "hobby", "vintage gear", "field guide",
    "collecting", "archive", "workshop", "expedition", "restoration",
]


@dataclass
class DiscoveryConfig:
    geo: str = "US"
    timeframe: str = "today 3-m"
    anchors: list[str] = field(default_factory=lambda: list(DEFAULT_ANCHORS))
    seeds_per_source: int = 12
    max_candidates: int = 24
    keep: int = 6
    thresholds: Thresholds = field(default_factory=Thresholds)
    use_llm: bool = True
    measure_social: bool = True
    correlation_threshold: float = 0.45


class DiscoveryEngine:
    def __init__(
        self,
        settings: Settings,
        *,
        config: DiscoveryConfig | None = None,
        llm=None,
        log: Log | None = None,
    ):
        self.settings = settings
        self.config = config or DiscoveryConfig(
            geo=settings.trends_geo,
            timeframe=settings.trends_timeframe,
            thresholds=Thresholds(
                min_growth=settings.discovery_min_growth,
                max_competition=settings.discovery_max_competition,
                min_social=settings.discovery_min_social,
            ),
        )
        self.llm = llm
        self.log = log or (lambda message: None)
        self.offline = OfflineSignals(seed=settings.seed, geo=self.config.geo)
        cache_dir = Path(settings.cache_dir) / "trends"

        if settings.offline:
            self.trends = self.offline
            self.reddit = self.offline
            self.x = None
            self.meta = None
            self.text = None
            self.images = None
        else:
            self.trends = GoogleTrends(
                geo=self.config.geo, timeframe=self.config.timeframe,
                timeout=settings.http_timeout, user_agent=settings.user_agent,
                cache_dir=cache_dir,
            )
            self.reddit = Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                user_agent=settings.reddit_user_agent,
                timeout=settings.http_timeout,
            )
            if not self.reddit.authenticated and not settings.reddit_allow_anonymous:
                # Hosted notebooks and cloud IPs are routinely 403'd by Reddit;
                # skipping is cheaper than 24 failed requests per cycle.
                self.reddit = _SkippedReddit()
            self.x = XSignals(bearer_token=settings.x_bearer_token, timeout=settings.http_timeout)
            self.meta = MetaSignals(
                access_token=settings.meta_access_token,
                ig_user_id=settings.meta_ig_user_id,
                timeout=settings.http_timeout,
            )
            self.text = DuckDuckGoText(user_agent=settings.user_agent, timeout=settings.http_timeout)
            self.images = DuckDuckGoImages(user_agent=settings.user_agent, timeout=settings.http_timeout)

    # -- 1. harvest -------------------------------------------------------
    def harvest(self) -> list[Seed]:
        """Collect raw candidate terms from every source that will answer."""
        seeds: list[Seed] = []
        seen: set[str] = set()

        def add(term: str, source: str, context: str = "", weight: float = 1.0, raw: dict | None = None) -> None:
            term = " ".join((term or "").split()).strip(" #-–—")
            key = term.lower()
            if not term or key in seen or len(term) < 3:
                return
            seen.add(key)
            seeds.append(Seed(term=term, source=source, context=context, weight=weight, raw=raw or {}))

        # What is trending right now.
        try:
            for row in self.trends.trending_now(limit=self.config.seeds_per_source * 2):
                add(row["title"], "google_trends:trending",
                    context=" ".join(row.get("news", [])), weight=1.0, raw=row)
        except Exception as exc:
            self.log(f"trending harvest failed: {type(exc).__name__}: {exc}")

        # Rising related queries around neutral anchors — where a wave shows up
        # before it reaches the trending page.
        for anchor in self.config.anchors[: self.config.seeds_per_source]:
            try:
                for row in self.trends.rising_queries(anchor, limit=6):
                    add(row.query, "google_trends:rising",
                        context=f"rising around '{anchor}'",
                        weight=1.4 if row.breakout else 1.1,
                        raw={"value": row.value, "breakout": row.breakout, "anchor": anchor})
            except Exception as exc:
                self.log(f"rising queries failed for {anchor}: {type(exc).__name__}: {exc}")

        # Reddit titles only become seeds when an LLM can turn a headline into a
        # topic; otherwise Reddit contributes heat, not candidates.
        if self.llm is not None and getattr(self.llm, "available", False) and hasattr(self.reddit, "hot"):
            try:
                titles = [post.title for post in self.reddit.hot("all", limit=40)]
                for topic in self.llm.extract_topics(titles)[: self.config.seeds_per_source]:
                    add(topic, "reddit:hot", context="extracted from hot posts", weight=1.0)
            except Exception as exc:
                self.log(f"reddit harvest failed: {type(exc).__name__}: {exc}")

        return seeds

    # -- 2. measure -------------------------------------------------------
    def measure(self, seed: Seed) -> TopicOpportunity:
        """Ask every source what it knows about one candidate."""
        opportunity = TopicOpportunity(topic=seed.term, seeds=[seed.term])
        opportunity.evidence["seed_source"] = seed.source
        opportunity.evidence["seed_context"] = seed.context

        # --- Google Trends: the growth number the brief asks for -----------
        try:
            series = self.trends.interest_over_time(seed.term, self.config.timeframe)
            if series.ok and series.values:
                opportunity.timeline = series.values
                opportunity.growth_3m = series.growth_pct()
                opportunity.momentum = series.momentum_pct()
                opportunity.interest_mean = series.mean()
                opportunity.peak_ratio = series.peak_ratio()
                opportunity.add(Signal(
                    "google_trends", "growth_3m", opportunity.growth_3m,
                    f"{opportunity.growth_3m:+.0f}% over {self.config.timeframe}, "
                    f"momentum {opportunity.momentum:+.0f}%, mean index {opportunity.interest_mean}",
                ))
            else:
                opportunity.add(Signal("google_trends", "growth_3m", 0.0, series.error, ok=False))
        except Exception as exc:
            opportunity.add(Signal("google_trends", "growth_3m", 0.0, f"{type(exc).__name__}: {exc}", ok=False))

        if seed.raw.get("breakout"):
            opportunity.breakout = True
            opportunity.notes.append("Google Trends flagged this as a breakout rising query")

        try:
            rising = self.trends.rising_queries(seed.term, limit=8)
            opportunity.rising_queries = [row.query for row in rising]
            if any(row.breakout for row in rising):
                opportunity.breakout = True
        except Exception:
            pass

        # --- Reddit --------------------------------------------------------
        heats: list[tuple[str, float, float, int]] = []   # (platform, heat, avg engagement, posts)
        try:
            reddit_heat = self.reddit.heat(seed.term)
            if reddit_heat.ok and reddit_heat.posts:
                heats.append(("reddit", reddit_heat.heat, reddit_heat.avg_engagement, reddit_heat.posts))
                opportunity.evidence["reddit"] = reddit_heat.top
                opportunity.add(Signal(
                    "reddit", "heat", reddit_heat.heat,
                    f"{reddit_heat.posts} posts in {len(reddit_heat.subreddits)} subreddits, "
                    f"{reddit_heat.avg_engagement:.0f} engagement/post, "
                    f"{reddit_heat.recent_share:.0%} from the last week",
                ))
            else:
                opportunity.add(Signal("reddit", "heat", 0.0, reddit_heat.error or "no posts", ok=False))
        except Exception as exc:
            opportunity.add(Signal("reddit", "heat", 0.0, f"{type(exc).__name__}: {exc}", ok=False))

        # --- X and Meta ----------------------------------------------------
        if self.config.measure_social:
            for client in (self.x, self.meta):
                if client is None:
                    continue
                result = client.heat(seed.term)
                if result.ok and result.posts:
                    heats.append((result.platform, result.heat, result.avg_engagement, result.posts))
                    opportunity.evidence[result.platform] = result.top
                    opportunity.add(Signal(
                        result.platform, "heat", result.heat,
                        f"{result.posts} posts, {result.avg_engagement:.0f} engagement/post, "
                        f"~{result.avg_views:.0f} views/post",
                    ))
                else:
                    opportunity.add(Signal(result.platform, "heat", 0.0, result.error, ok=False))

        if heats:
            # Weight the loudest platform highest instead of averaging a silent
            # one into a false negative.
            heats.sort(key=lambda row: -row[1])
            leader = heats[0]
            others = sum(row[1] for row in heats[1:]) / max(1, len(heats) - 1) if len(heats) > 1 else 0.0
            opportunity.social_heat = round(min(100.0, 0.7 * leader[1] + 0.3 * others), 1)
            opportunity.avg_engagement = round(max(row[2] for row in heats), 1)
            opportunity.posts_seen = sum(row[3] for row in heats)

        # --- competition ---------------------------------------------------
        try:
            if self.settings.offline:
                report = self.offline.competition(seed.term)
            else:
                report = competition_mod.measure(seed.term, self.text, self.images)
            opportunity.competition = report.competition
            opportunity.listings_seen = report.listings
            opportunity.evidence["competition"] = report.to_dict()
            opportunity.add(Signal(
                "duckduckgo", "competition", report.competition,
                f"{report.listings} marketplace listings in {report.results_seen} results"
                + (f" ({', '.join(report.marketplaces)})" if report.marketplaces else ""),
                ok=report.ok,
            ))
        except Exception as exc:
            opportunity.add(Signal("duckduckgo", "competition", 0.0, f"{type(exc).__name__}: {exc}", ok=False))

        return opportunity

    # -- 3. the cycle -----------------------------------------------------
    def discover(
        self,
        *,
        count: int | None = None,
        progress: Progress | None = None,
        cancel: Cancel | None = None,
    ) -> DiscoveryReport:
        progress = progress or (lambda fraction, message: None)
        cancel = cancel or (lambda: False)
        started = time.time()
        keep = count or self.config.keep

        report = DiscoveryReport(
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            geo=self.config.geo,
            timeframe=self.config.timeframe,
        )

        # 1 — harvest
        progress(0.02, "harvesting candidates")
        seeds = self.harvest()
        report.seeds = seeds
        self.log(f"harvested {len(seeds)} raw candidates")
        if not seeds:
            report.warnings.append(
                "no candidates could be harvested — Google Trends is unreachable "
                "(rate limited, blocked, or the geo has no data). Offline mode still works."
            )
            report.duration_s = time.time() - started
            return report

        # 2 — screen early, so nothing unprintable is ever measured
        clean: list[Seed] = []
        for seed in seeds:
            verdict = screening.screen(seed.term, context=seed.context)
            if verdict.ok:
                clean.append(seed)
            else:
                rejected = TopicOpportunity(topic=seed.term, seeds=[seed.term], accepted=False)
                rejected.rejected_reason = f"{verdict.category}: {verdict.reason}"
                report.rejected.append(rejected)
        self.log(f"{len(clean)} candidates survived screening, {len(report.rejected)} rejected")

        # 3 — let the LLM turn raw query strings into design-viable topics
        if self.llm is not None and getattr(self.llm, "available", False) and self.config.use_llm:
            progress(0.12, "refining candidates")
            try:
                refined = self.llm.refine_seeds([seed.term for seed in clean[: self.config.max_candidates]])
                for original, replacement in refined.items():
                    for seed in clean:
                        if seed.term == original and replacement and replacement != original:
                            seed.context = f"{seed.context} (was: {original})".strip()
                            seed.term = replacement
            except Exception as exc:
                self.log(f"seed refinement failed: {type(exc).__name__}: {exc}")

        candidates = clean[: self.config.max_candidates]

        # 4 — measure
        opportunities: list[TopicOpportunity] = []
        for index, seed in enumerate(candidates):
            if cancel():
                report.warnings.append("discovery cancelled")
                break
            progress(0.15 + 0.6 * index / max(1, len(candidates)), f"measuring: {seed.term}")
            opportunity = self.measure(seed)
            self.log(f"  {opportunity.summary()}")
            opportunities.append(opportunity)
        report.measured = len(opportunities)

        # 5 — screen again now that we have context, then score
        progress(0.78, "scoring")
        for opportunity in opportunities:
            verdict = screening.screen(
                opportunity.topic,
                context=" ".join(opportunity.rising_queries[:5]),
            )
            if not verdict.ok:
                opportunity.accepted = False
                opportunity.rejected_reason = f"{verdict.category}: {verdict.reason}"
            score(opportunity, thresholds=self.config.thresholds)

        # 6 — correlate the survivors into families
        progress(0.85, "correlating")
        accepted = [o for o in opportunities if o.accepted]
        report.families = correlation.correlate(accepted, threshold=self.config.correlation_threshold)

        # 7 — LLM judgement: wearability, angle, durability, risk
        if self.llm is not None and getattr(self.llm, "available", False) and self.config.use_llm and accepted:
            progress(0.9, "judging wearability")
            try:
                verdicts = self.llm.judge_topics([
                    {
                        "topic": o.topic,
                        "growth_3m": o.growth_3m,
                        "social_heat": o.social_heat,
                        "competition": o.competition,
                        "rising_queries": o.rising_queries[:6],
                    }
                    for o in accepted[: keep * 2]
                ])
                for opportunity in accepted:
                    verdict = verdicts.get(opportunity.topic)
                    if not verdict:
                        continue
                    opportunity.angle = str(verdict.get("angle", ""))
                    opportunity.audience = str(verdict.get("audience", ""))
                    opportunity.durability = str(verdict.get("durability", ""))
                    opportunity.risk = str(verdict.get("risk", ""))
                    fit = verdict.get("apparel_fit")
                    if isinstance(fit, (int, float)):
                        score(opportunity, thresholds=self.config.thresholds, apparel_fit=float(fit))
                    if verdict.get("drop"):
                        opportunity.accepted = False
                        opportunity.rejected_reason = f"llm: {verdict.get('reason', 'judged unsuitable')}"
            except Exception as exc:
                self.log(f"topic judgement failed: {type(exc).__name__}: {exc}")

        # 8 — rank and split
        ranked = rank(opportunities)
        report.opportunities = [o for o in ranked if o.accepted][:keep]
        report.rejected.extend([o for o in ranked if not o.accepted])
        report.source_status = self.source_status()
        report.duration_s = time.time() - started

        progress(1.0, f"{len(report.opportunities)} opportunities from {report.measured} measured")
        self.log(
            "discovery complete: "
            + (", ".join(f"{o.topic} ({o.overall})" for o in report.opportunities) or "nothing cleared the filters")
        )
        return report

    # -- helpers ----------------------------------------------------------
    def source_status(self) -> dict[str, str]:
        if self.settings.offline:
            return {"mode": "offline — synthetic signals, no network"}
        status = {
            "google_trends": f"geo {self.config.geo}, {self.config.timeframe}",
            "reddit": "oauth" if getattr(self.reddit, "authenticated", False) else "anonymous",
            "x": "configured" if (self.x and self.x.configured) else "no X_BEARER_TOKEN",
            "meta": "configured" if (self.meta and self.meta.configured) else "no META_ACCESS_TOKEN",
            "duckduckgo": "competition measurement",
        }
        return status

    def write_report(self, report: DiscoveryReport, runs_dir: Path | str | None = None) -> Path:
        base = Path(runs_dir or self.settings.runs_dir) / "_discovery"
        base.mkdir(parents=True, exist_ok=True)
        stamp = report.created_at.replace(":", "").replace("-", "")[:15] or "report"
        path = base / f"{stamp}.json"
        dump_json(report.to_dict(), path)
        dump_json(report.to_dict(), base / "latest.json")
        return path


def latest_report(runs_dir: Path | str) -> dict[str, Any] | None:
    path = Path(runs_dir) / "_discovery" / "latest.json"
    if not path.is_file():
        return None
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
