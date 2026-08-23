"""Autonomous discovery — the part that chooses what to design."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from archivist.discovery import competition, correlation, screening
from archivist.discovery.engine import DiscoveryEngine
from archivist.discovery.google_trends import InterestSeries, TrendPoint, _strip_guard, _traffic_to_int
from archivist.discovery.models import TopicOpportunity
from archivist.discovery.offline import OfflineSignals
from archivist.discovery.reddit import Post, Reddit
from archivist.discovery.scoring import Thresholds, competition_gap_score, growth_score, rank, score
from archivist.pipeline import PipelineOptions, autopilot
from archivist.storage import load_run


def _series(values: list[float]) -> InterestSeries:
    return InterestSeries(
        keyword="probe",
        points=[TrendPoint(time=f"d{index}", value=value) for index, value in enumerate(values)],
    )


# --- google trends maths -------------------------------------------------
def test_growth_is_measured_from_the_ends_of_the_window():
    doubling = _series([10.0] * 20 + [20.0] * 20)
    assert doubling.growth_pct(window=14) == pytest.approx(100.0, abs=1.0)

    flat = _series([25.0] * 40)
    assert flat.growth_pct(window=14) == pytest.approx(0.0, abs=1.0)

    falling = _series([40.0] * 20 + [10.0] * 20)
    assert falling.growth_pct(window=14) < -50


def test_a_term_starting_at_zero_cannot_report_infinite_growth():
    """A brand new term is a new term, not a 10,000% winner."""
    from_zero = _series([0.0] * 20 + [30.0] * 20)
    assert from_zero.growth_pct(window=14) < 2100  # floored baseline, not division by zero


def test_momentum_and_peak_ratio_describe_where_the_wave_is():
    still_climbing = _series([10] * 30 + [40] * 10)
    assert still_climbing.momentum_pct() > 50
    assert still_climbing.peak_ratio() == pytest.approx(1.0, abs=0.05)

    past_it = _series([10] * 10 + [80] * 20 + [20] * 10)
    assert past_it.momentum_pct() < 0
    assert past_it.peak_ratio() < 0.5


def test_traffic_labels_and_the_json_guard_are_parsed():
    assert _traffic_to_int("20K+") == 20_000
    assert _traffic_to_int("1M+") == 1_000_000
    assert _traffic_to_int("500+") == 500
    assert _traffic_to_int("") == 0
    assert _strip_guard(")]}',\n{\"widgets\": []}") == {"widgets": []}


# --- screening -----------------------------------------------------------
@pytest.mark.parametrize(
    "topic,category",
    [
        ("nike air max collecting", "trademark"),
        ("plane crash investigation", "tragedy"),
        ("presidential election night", "politics"),
        ("ozempic weight loss", "health-claim"),
        ("Marcus Whitfield", "likeness"),
        ("season 4 trailer reaction", "entertainment-event"),
    ],
)
def test_unprintable_topics_are_refused_with_a_reason(topic, category):
    verdict = screening.screen(topic)
    assert not verdict.ok
    assert verdict.category == category
    assert verdict.reason


@pytest.mark.parametrize(
    "topic",
    ["brutalist bus shelters", "urban foraging", "tide clock making", "harbour dredging"],
)
def test_object_and_practice_topics_pass(topic):
    assert screening.screen(topic).ok


def test_person_detection_does_not_eat_ordinary_two_word_topics():
    assert not screening.looks_like_person("Night Train")     # contains a common noun
    assert screening.looks_like_person("Marcus Whitfield")


# --- scoring -------------------------------------------------------------
def test_growth_score_rises_but_saturates():
    assert growth_score(0) < growth_score(30) < growth_score(120) < growth_score(400)
    assert growth_score(5000) <= 10.0
    assert growth_score(-40) < 3.0
    # A breakout beats the same growth without the flag; a dying wave is penalised.
    assert growth_score(80, breakout=True) > growth_score(80)
    assert growth_score(80, momentum=-50) < growth_score(80)


def test_competition_gap_rewards_an_empty_market():
    assert competition_gap_score(0) == 10.0
    assert competition_gap_score(90) < competition_gap_score(40)


def test_thresholds_reject_and_explain():
    weak = TopicOpportunity(
        topic="flat thing", growth_3m=4.0, social_heat=3.0, competition=95.0,
        interest_mean=1.0, sources=["google_trends"],
    )
    score(weak, thresholds=Thresholds())
    assert not weak.accepted
    for expected in ("growth", "competition", "social heat", "source"):
        assert expected in weak.rejected_reason

    strong = TopicOpportunity(
        topic="rising thing", growth_3m=140.0, social_heat=48.0, avg_engagement=900,
        competition=18.0, interest_mean=22.0, sources=["google_trends", "reddit", "duckduckgo"],
    )
    score(strong, thresholds=Thresholds())
    assert strong.accepted
    assert strong.overall > 6.5


def test_breakout_survives_a_low_growth_number():
    """Google flags breakouts when the baseline is too small to compute a percentage."""
    breakout = TopicOpportunity(
        topic="new thing", growth_3m=5.0, breakout=True, social_heat=30.0,
        competition=20.0, interest_mean=8.0, sources=["google_trends", "reddit"],
    )
    score(breakout, thresholds=Thresholds())
    assert breakout.accepted


def test_ranking_puts_accepted_topics_first():
    accepted = TopicOpportunity(topic="a", sources=["x", "y"])
    accepted.scores.growth = 5
    rejected = TopicOpportunity(topic="b", accepted=False, sources=["x", "y"])
    rejected.scores.growth = 10
    assert [item.topic for item in rank([rejected, accepted])] == ["a", "b"]


# --- correlation ---------------------------------------------------------
def test_pearson_matches_known_cases():
    assert correlation.pearson([1, 2, 3, 4, 5, 6], [2, 4, 6, 8, 10, 12]) == 1.0
    assert correlation.pearson([1, 2, 3, 4, 5, 6], [6, 5, 4, 3, 2, 1]) == -1.0
    assert correlation.pearson([1, 1, 1, 1, 1, 1], [1, 2, 3, 4, 5, 6]) == 0.0
    assert correlation.pearson([1, 2], [1, 2]) == 0.0  # too short to mean anything


def test_shared_vocabulary_links_topics_and_families_stay_small():
    def make(topic: str, timeline: list[float]) -> TopicOpportunity:
        item = TopicOpportunity(topic=topic, timeline=timeline)
        item.scores.growth = 8
        return item

    rising = [float(index) + (index % 3) for index in range(30)]
    items = [
        make("analogue photography revival", rising),
        make("analogue photography gear", rising),
        make("competitive pigeon racing", [50 - index * 0.5 for index in range(30)]),
    ]
    families = correlation.correlate(items, threshold=0.4, max_family=5)

    assert items[0].family == items[1].family, "the same subject must land in one family"
    assert items[2].family != items[0].family, "an unrelated topic must not be swept in"
    assert all(len(members) <= 5 for members in families.values())


def test_merely_both_rising_is_not_a_correlation():
    a = TopicOpportunity(topic="tide clock making", timeline=[float(i) for i in range(30)])
    b = TopicOpportunity(topic="mushroom identification", timeline=[float(i) * 2 for i in range(30)])
    assert correlation.affinity(a, b) == 0.0


# --- competition ---------------------------------------------------------
class _StubText:
    def __init__(self, rows):
        self.rows = rows

    def search(self, query, limit=30):
        return self.rows[:limit]


def test_marketplace_listings_drive_the_competition_number():
    crowded = _StubText([
        {"url": "https://www.redbubble.com/i/t-shirt/thing", "title": "Thing T-Shirt", "snippet": "buy a tee"},
        {"url": "https://www.etsy.com/listing/1/thing-tee", "title": "Thing Tee", "snippet": "t-shirt"},
        {"url": "https://www.teepublic.com/t-shirt/thing", "title": "Thing", "snippet": "t shirt design"},
        {"url": "https://en.wikipedia.org/wiki/Thing", "title": "Thing", "snippet": "an article"},
    ])
    report = competition.measure("thing", crowded)
    assert report.listings == 3
    assert set(report.marketplaces) == {"Redbubble", "Etsy", "TeePublic"}
    assert report.competition > 40
    assert report.gap < 6

    empty = _StubText([
        {"url": "https://en.wikipedia.org/wiki/Rare", "title": "Rare", "snippet": "an article"},
        {"url": "https://example.org/blog", "title": "Rare thing", "snippet": "a post"},
    ])
    quiet = competition.measure("rare", empty)
    assert quiet.listings == 0
    assert quiet.competition == 0.0
    assert quiet.gap == 10.0


def test_a_dead_search_source_is_reported_not_guessed():
    class Broken:
        def search(self, query, limit=30):
            raise RuntimeError("blocked")

    report = competition.measure("thing", Broken())
    assert not report.ok
    assert "blocked" in report.error


# --- reddit --------------------------------------------------------------
def test_reddit_heat_rewards_volume_engagement_and_spread(monkeypatch):
    import time as time_module

    now = time_module.time()

    def posts(count: int, score_value: int, subreddits: int):
        return [
            Post(title=f"post {index}", score=score_value, comments=score_value // 4,
                 subreddit=f"sub{index % subreddits}", created_utc=now - 3600, permalink="/r/x/1")
            for index in range(count)
        ]

    client = Reddit()
    monkeypatch.setattr(client, "search", lambda *a, **k: posts(40, 2000, 10))
    hot = client.heat("busy topic")
    monkeypatch.setattr(client, "search", lambda *a, **k: posts(2, 3, 1))
    quiet = client.heat("quiet topic")

    assert hot.heat > quiet.heat
    assert hot.posts == 40 and hot.avg_engagement > quiet.avg_engagement
    assert len(hot.subreddits) == 10

    monkeypatch.setattr(client, "search", lambda *a, **k: [])
    empty = client.heat("nothing")
    assert empty.posts == 0 and empty.heat == 0.0 and empty.ok


def test_reddit_failure_is_captured(monkeypatch):
    client = Reddit()

    def boom(*a, **k):
        raise RuntimeError("403 blocked")

    monkeypatch.setattr(client, "search", boom)
    result = client.heat("anything")
    assert not result.ok and "403" in result.error


# --- offline signals -----------------------------------------------------
def test_offline_signals_are_deterministic_and_varied():
    first = OfflineSignals(seed=3)
    second = OfflineSignals(seed=3)
    assert first.interest_over_time("cold plunge culture").values == \
        second.interest_over_time("cold plunge culture").values

    growths = {
        topic: first.interest_over_time(topic).growth_pct()
        for topic in ("cold plunge culture", "mushroom identification", "harbour dredging")
    }
    assert max(growths.values()) > 50, "some offline topics must look like real risers"
    assert min(growths.values()) < 25, "and some must fail the filter, or nothing is being tested"


# --- the whole cycle -----------------------------------------------------
def test_discovery_cycle_produces_auditable_opportunities(settings):
    report = DiscoveryEngine(settings).discover(count=5)

    assert report.opportunities, "offline discovery must always find something"
    assert report.measured >= len(report.opportunities)

    for opportunity in report.opportunities:
        assert opportunity.accepted
        assert len(opportunity.sources) >= 2, "an accepted topic must be confirmed by 2+ sources"
        assert opportunity.signals, "every number must carry the source that produced it"
        assert opportunity.growth_3m >= settings.discovery_min_growth or opportunity.breakout
        assert opportunity.competition <= settings.discovery_max_competition
        assert screening.screen(opportunity.topic).ok, "nothing unprintable may be offered"
        assert opportunity.family

    for rejected in report.rejected:
        assert rejected.rejected_reason, "a rejection without a reason is not auditable"

    rows = report.table_rows()
    assert len(rows) == len(report.opportunities)
    assert rows[0][1] == report.opportunities[0].topic


def test_discovery_report_round_trips_to_disk(settings):
    engine = DiscoveryEngine(settings)
    report = engine.discover(count=3)
    path = engine.write_report(report)

    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["opportunities"][0]["topic"] == report.opportunities[0].topic
    assert (Path(settings.runs_dir) / "_discovery" / "latest.json").is_file()

    from archivist.discovery import latest_report

    assert latest_report(settings.runs_dir)["measured"] == report.measured


def test_autopilot_designs_a_topic_nobody_typed(settings):
    result = autopilot(settings, PipelineOptions(generate=False), designs=1)

    assert result.runs, "autopilot must produce a design run"
    assert result.report is not None and result.report_path

    run_result = result.runs[0]
    assert run_result.topic in [o.topic for o in result.report.opportunities]
    assert run_result.concepts and run_result.recommended

    # The evidence travels with the design, so a run can answer "why this subject".
    evidence = run_result.discovery
    assert evidence["chosen_by"] == "autopilot"
    assert "growth_3m" in evidence and "competition" in evidence
    assert evidence["signals"], "the manifest must carry the raw signals"

    reloaded = load_run(run_result.run_dir)
    assert reloaded.discovery["chosen_by"] == "autopilot"


def test_autopilot_says_so_when_nothing_clears_the_filters(settings):
    # A growth floor would be bypassed by Google's breakout flag, so squeeze the
    # one threshold that has no override.
    settings.discovery_max_competition = -1.0
    result = autopilot(settings, PipelineOptions(generate=False), designs=1)

    assert not result.runs
    assert any("nothing that cleared the filters" in warning for warning in result.warnings)


def test_scheduler_can_run_an_autopilot_job(settings):
    from archivist.scheduler import Scheduler

    scheduler = Scheduler(settings)
    job = scheduler.create_job(
        "nightly", [], mode="autopilot", cadence="once",
        options={"generate": False, "offline": True, "designs": 1, "collection": settings.collection},
    )
    assert job.autonomous and job.runnable()
    assert job.current_topic() == "(discovered at run time)"

    entry = scheduler.run_job(job.id)
    assert entry["status"] == "ok", entry
    assert entry["discovered"], "the history must record what it considered"
    assert Path(entry["run_dir"], "manifest.json").is_file()
