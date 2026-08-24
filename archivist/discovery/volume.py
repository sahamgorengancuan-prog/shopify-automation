"""Volume-first discovery — rank by demand before spending anything on detail.

Growth alone picks winners nobody searches for. This asks a different question
first: *of the broad roots this house can actually design, which ones do people
search for most?* Google Trends only reports relative numbers, so every batch is
compared against one shared benchmark (``archive`` = 100), which makes the
ranking comparable across requests.

Only the leading quartile then receives the expensive per-topic measurement, and
a partial answer is refused: if Trends throttled more than a fifth of the pool,
the ranking is abandoned rather than chosen from holes in the data.
"""

from __future__ import annotations

import json
import math
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import screening
from .fit import TARGET_PROFILE, VOLUME_ROOTS, topic_hygiene
from .models import Seed, TopicOpportunity
from .scoring import competition_gap_score, growth_score

Log = Callable[[str], None]
Progress = Callable[[float, str], None]

BENCHMARK = "archive"
BATCH_SIZE = 4
MIN_COVERAGE = 0.80


class VolumeDiscoveryError(RuntimeError):
    """Raised instead of choosing a topic from incomplete measurements."""


@dataclass
class VolumeRow:
    topic: str
    relative_volume: float
    fit: float
    measured: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic, "relative_volume": self.relative_volume,
            "fit": self.fit, "measured": self.measured,
        }


@dataclass
class VolumeReport:
    created_at: str = ""
    benchmark: str = BENCHMARK
    coverage: float = 0.0
    throttled_batches: list[dict[str, Any]] = field(default_factory=list)
    ranking: list[VolumeRow] = field(default_factory=list)
    shortlist: list[str] = field(default_factory=list)
    validated: list[dict[str, Any]] = field(default_factory=list)
    selected: TopicOpportunity | None = None
    selected_volume: float = 0.0
    selected_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "method": "1-2 word roots → shared-benchmark relative volume → detailed validation",
            "benchmark": self.benchmark,
            "benchmark_index": 100,
            "measurement_coverage": round(self.coverage, 3),
            "throttled_batches": self.throttled_batches,
            "candidate_count": len(self.ranking),
            "shortlist_count": len(self.shortlist),
            "volume_ranking": [row.to_dict() for row in self.ranking],
            "validated_ranking": self.validated,
            "selected": self.selected.to_dict() if self.selected else None,
            "selected_relative_volume": self.selected_volume,
            "selected_smart_score": self.selected_score,
        }


def normalise_roots(roots: list[str] | None = None) -> list[str]:
    """Keep only screenable one- and two-word roots — what Trends can compare.

    V10.1: roots come from the caller. There is no house pool to fall back on,
    because a fallback pool is exactly how a curated aesthetic would re-enter
    autonomous discovery through the back door.
    """
    if not roots and not VOLUME_ROOTS:
        raise VolumeDiscoveryError(
            "volume comparison needs roots to compare. It is a diagnostic tool the caller "
            "supplies terms to, not a discovery source — autonomous discovery harvests "
            "public signals instead."
        )
    out: list[str] = []
    seen: set[str] = set()
    for raw in roots or VOLUME_ROOTS:
        term = " ".join(str(raw).lower().split())
        words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", term)
        if not 1 <= len(words) <= 2 or term in seen or not screening.screen(term).ok:
            continue
        seen.add(term)
        out.append(term)
    return out


def _compare_offline(engine, batch: list[str], timeframe: str) -> dict[str, float]:
    """Offline/no-session fallback: series means against the benchmark's mean."""
    benchmark_series = engine.trends.interest_over_time(BENCHMARK, timeframe)
    base = benchmark_series.mean() or 1.0
    values: dict[str, float] = {}
    for term in batch:
        series = engine.trends.interest_over_time(term, timeframe)
        values[term] = round(100.0 * series.mean() / base, 2) if series.ok else 0.0
    return values


def rank_by_volume(engine, roots: list[str], *, timeframe: str, log: Log,
                   progress: Progress | None = None,
                   batch_size: int = BATCH_SIZE) -> tuple[list[VolumeRow], float, list[dict[str, Any]]]:
    rows: list[VolumeRow] = []
    measured_terms = 0
    throttled: list[dict[str, Any]] = []
    batches = [roots[start:start + batch_size] for start in range(0, len(roots), batch_size)]

    for index, batch in enumerate(batches):
        if progress:
            progress(index / max(1, len(batches)), f"comparing volume: {', '.join(batch)}")
        compared: dict[str, float] | None = None
        last_error: Exception | None = None

        for attempt in range(3):
            try:
                if hasattr(engine.trends, "compare"):
                    compared = engine.trends.compare(batch, benchmark=BENCHMARK, timeframe=timeframe)
                else:
                    compared = _compare_offline(engine, batch, timeframe)
                measured_terms += len(batch)
                break
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    wait = 2.0 ** (attempt + 1) + random.random()
                    log(f"  trends throttled; retrying this batch in {wait:.1f}s")
                    time.sleep(wait)

        if compared is None:
            throttled.append({"terms": batch, "error": f"{type(last_error).__name__}: {last_error}"})
            log(f"  batch unavailable after retries: {throttled[-1]['error']}")
            compared = {term: 0.0 for term in batch}

        for term in batch:
            rows.append(VolumeRow(
                topic=term, relative_volume=float(compared.get(term, 0.0)),
                fit=topic_hygiene(term), measured=bool(compared.get(term, 0.0) or last_error is None),
            ))

    rows.sort(key=lambda row: -row.relative_volume)
    coverage = measured_terms / max(1, len(roots))
    return rows, coverage, throttled


def validate(engine, shortlist: list[VolumeRow], *, log: Log,
             progress: Progress | None = None) -> list[dict[str, Any]]:
    """Measure growth, competition and social heat for the volume leaders only."""
    max_volume = max((row.relative_volume for row in shortlist), default=1.0) or 1.0
    records: list[dict[str, Any]] = []

    for index, row in enumerate(shortlist):
        if progress:
            progress(index / max(1, len(shortlist)), f"validating: {row.topic}")
        opportunity = engine.measure(Seed(term=row.topic, source="google-relative-volume", context=TARGET_PROFILE))
        answered = {signal.source for signal in opportunity.signals if signal.ok}

        volume_score = 10.0 * math.sqrt(row.relative_volume / max_volume)
        weighted: list[tuple[float, float]] = [(volume_score, 0.42), (row.fit, 0.25)]
        if "google_trends" in answered:
            weighted.append((growth_score(
                opportunity.growth_3m, breakout=opportunity.breakout, momentum=opportunity.momentum
            ), 0.15))
        if "duckduckgo" in answered:
            weighted.append((competition_gap_score(opportunity.competition), 0.15))
        if answered & {"reddit", "x", "meta"}:
            weighted.append((min(10.0, opportunity.social_heat / 10.0), 0.05))
        total_weight = sum(weight for _, weight in weighted)
        score = round(sum(value * weight for value, weight in weighted) / total_weight, 2)

        records.append({
            "opportunity": opportunity, "topic": row.topic, "relative_volume": row.relative_volume,
            "fit": row.fit, "score": score, "growth_3m": opportunity.growth_3m,
            "competition": opportunity.competition, "social_heat": opportunity.social_heat,
        })
        log(
            f"  volume {row.relative_volume:>8.2f} | score {score:>5.2f} | {row.topic:<24} "
            f"growth {opportunity.growth_3m:+7.0f}% | competition {opportunity.competition:>4.0f}"
        )
    return records


def discover(engine, *, timeframe: str = "today 3-m", roots: list[str] | None = None,
             log: Log | None = None, progress: Progress | None = None,
             min_coverage: float = MIN_COVERAGE) -> VolumeReport:
    """Rank the root pool by demand, then validate the leading quartile."""
    log = log or (lambda message: None)
    pool = normalise_roots(roots)
    report = VolumeReport(created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    log(f"comparing {len(pool)} broad roots in Google Trends ({BENCHMARK} = 100)")
    ranking, coverage, throttled = rank_by_volume(engine, pool, timeframe=timeframe, log=log, progress=progress)
    report.ranking, report.coverage, report.throttled_batches = ranking, coverage, throttled

    if coverage < min_coverage:
        raise VolumeDiscoveryError(
            f"Google Trends answered for only {coverage:.0%} of the pool. The ranking was abandoned "
            "instead of choosing from throttled data — wait a few minutes and run again."
        )

    positive = [row for row in ranking if row.relative_volume > 0]
    if not positive:
        raise VolumeDiscoveryError("Google Trends returned no comparable volume for the root pool.")

    shortlist_size = max(12, math.ceil(len(positive) * 0.25))
    shortlist = positive[:shortlist_size]
    report.shortlist = [row.topic for row in shortlist]
    log(f"detailed validation of the top {len(shortlist)} volume-ranked roots")

    records = validate(engine, shortlist, log=log, progress=progress)
    report.validated = [
        {key: value for key, value in record.items() if key != "opportunity"}
        for record in sorted(records, key=lambda item: -item["score"])
    ]

    viable = [
        record for record in records
        if record["opportunity"].competition <= 75
        and (record["opportunity"].breakout or record["opportunity"].growth_3m >= -20)
        and screening.screen(record["opportunity"].topic).ok
    ]
    if not viable:
        raise VolumeDiscoveryError(
            "Volume was measured, but no root combined acceptable competition with non-collapsing "
            "demand. The pipeline stopped rather than forcing a weak topic into artwork."
        )

    best = max(viable, key=lambda record: record["score"])
    report.selected = best["opportunity"]
    report.selected_volume = best["relative_volume"]
    report.selected_score = best["score"]
    return report


def write_report(report: VolumeReport, runs_dir: Path | str) -> Path:
    directory = Path(runs_dir) / "_discovery"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "volume_first_latest.json"
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path
