"""Scheduling and auto-planning.

Two things live here:

* a small dependency-free scheduler that runs the pipeline on an interval, at a
  time of day, or once — persisted to disk so it survives a restart;
* the auto-planner, which turns one theme into a *collection plan*: a sequence
  of distinct but stylistically locked topics, spread across a schedule, so a
  drop builds itself over a week instead of being ten variations of one shirt.

Times are handled in the machine's local timezone, which is what a person
setting "every day at 09:00" means.
"""

from __future__ import annotations

import json
import random
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .pipeline import PipelineOptions, autopilot as run_autopilot, run as run_pipeline
from .trends import ERAS, GEOGRAPHIES, INSTITUTIONS, MEDIUMS, headline

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_HISTORY = 200

CADENCES = ("interval", "daily", "weekly", "once")
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _fmt(moment: datetime) -> str:
    return moment.strftime(TIME_FORMAT)


def _parse(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, TIME_FORMAT)
    except (ValueError, TypeError):
        return None


def _parse_clock(value: str, default: tuple[int, int] = (9, 0)) -> tuple[int, int]:
    try:
        hour, _, minute = value.partition(":")
        return max(0, min(23, int(hour))), max(0, min(59, int(minute or 0)))
    except (ValueError, AttributeError):
        return default


@dataclass
class Job:
    id: str
    name: str
    topics: list[str]
    # "topics"   — work through the list above, one per firing
    # "autopilot" — discover the topics at fire time and design the winners
    mode: str = "topics"
    cadence: str = "daily"            # interval | daily | weekly | once
    interval_minutes: int = 720
    at_time: str = "09:00"
    weekday: int = 0                  # 0 = Monday, only used by "weekly"
    options: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    next_run: str = ""
    last_run: str = ""
    last_status: str = "never run"
    last_run_dir: str = ""
    runs_completed: int = 0
    cursor: int = 0
    created_at: str = field(default_factory=lambda: _fmt(_now()))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def autonomous(self) -> bool:
        return self.mode == "autopilot"

    def current_topic(self) -> str:
        if self.autonomous:
            return "(discovered at run time)"
        if not self.topics:
            return ""
        return self.topics[self.cursor % len(self.topics)]

    def runnable(self) -> bool:
        return self.autonomous or bool(self.topics)

    def compute_next(self, *, after: datetime | None = None) -> str:
        """Next fire time, always strictly in the future."""
        base = after or _now()
        if self.cadence == "interval":
            return _fmt(base + timedelta(minutes=max(1, self.interval_minutes)))
        if self.cadence == "once":
            scheduled = _parse(self.next_run)
            if scheduled and scheduled > base:
                return _fmt(scheduled)
            return ""  # a fired one-shot has no next run
        hour, minute = _parse_clock(self.at_time)
        candidate = base.replace(hour=hour, minute=minute, second=0)
        if self.cadence == "weekly":
            delta = (self.weekday - candidate.weekday()) % 7
            candidate += timedelta(days=delta)
        while candidate <= base:
            candidate += timedelta(days=7 if self.cadence == "weekly" else 1)
        return _fmt(candidate)

    def describe(self) -> str:
        if self.cadence == "interval":
            hours, minutes = divmod(max(1, self.interval_minutes), 60)
            span = f"{hours}h{minutes:02d}m" if hours else f"{minutes}m"
            return f"every {span}"
        if self.cadence == "daily":
            return f"daily at {self.at_time}"
        if self.cadence == "weekly":
            return f"every {WEEKDAYS[self.weekday % 7]} at {self.at_time}"
        return f"once at {self.next_run or '—'}"


class Scheduler:
    """Persisted job store + one background worker thread."""

    def __init__(self, settings: Settings, *, tick_seconds: int = 15,
                 on_event: Callable[[str], None] | None = None):
        self.settings = settings
        self.tick_seconds = tick_seconds
        self.on_event = on_event or (lambda message: None)
        self.state_dir = Path(settings.runs_dir) / "_scheduler"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_path = self.state_dir / "jobs.json"
        self.history_path = self.state_dir / "history.json"
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.jobs: dict[str, Job] = {}
        self.history: list[dict[str, Any]] = []
        self.current: str = ""
        self.load()

    # -- persistence ------------------------------------------------------
    def load(self) -> None:
        with self._lock:
            if self.jobs_path.is_file():
                try:
                    raw = json.loads(self.jobs_path.read_text(encoding="utf-8"))
                    self.jobs = {row["id"]: Job(**row) for row in raw}
                except (OSError, json.JSONDecodeError, TypeError, KeyError):
                    self.jobs = {}
            if self.history_path.is_file():
                try:
                    self.history = json.loads(self.history_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self.history = []

    def save(self) -> None:
        with self._lock:
            self.jobs_path.write_text(
                json.dumps([job.to_dict() for job in self.jobs.values()], indent=2), encoding="utf-8"
            )
            self.history_path.write_text(
                json.dumps(self.history[-MAX_HISTORY:], indent=2), encoding="utf-8"
            )

    # -- job management ---------------------------------------------------
    def add_job(self, job: Job) -> Job:
        with self._lock:
            if not job.next_run:
                job.next_run = job.compute_next()
            self.jobs[job.id] = job
            self.save()
        self.on_event(f"job added: {job.name} ({job.describe()}) → next {job.next_run or 'never'}")
        return job

    def create_job(
        self,
        name: str,
        topics: list[str],
        *,
        mode: str = "topics",
        cadence: str = "daily",
        interval_minutes: int = 720,
        at_time: str = "09:00",
        weekday: int = 0,
        options: dict[str, Any] | None = None,
        start_at: str = "",
        enabled: bool = True,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:8],
            name=name.strip() or "unnamed plan",
            topics=[t.strip() for t in topics if t.strip()],
            mode="autopilot" if mode == "autopilot" else "topics",
            cadence=cadence if cadence in CADENCES else "daily",
            interval_minutes=max(1, int(interval_minutes)),
            at_time=at_time,
            weekday=int(weekday) % 7,
            options=options or {},
            enabled=enabled,
            next_run=start_at,
        )
        return self.add_job(job)

    def remove_job(self, job_id: str) -> bool:
        with self._lock:
            removed = self.jobs.pop(job_id, None)
            self.save()
        if removed:
            self.on_event(f"job removed: {removed.name}")
        return removed is not None

    def toggle_job(self, job_id: str, enabled: bool) -> bool:
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            job.enabled = enabled
            if enabled and not job.next_run:
                job.next_run = job.compute_next()
            self.save()
        self.on_event(f"job {'enabled' if enabled else 'paused'}: {job.name}")
        return True

    def job_rows(self) -> list[list[Any]]:
        with self._lock:
            jobs = sorted(self.jobs.values(), key=lambda j: (not j.enabled, j.next_run or "9999"))
        return [
            [
                job.id,
                job.name,
                "▶ running" if self.current == job.id else ("on" if job.enabled else "paused"),
                "autopilot" if job.autonomous else "topics",
                job.describe(),
                job.next_run or "—",
                "auto" if job.autonomous else f"{job.cursor % max(1, len(job.topics)) + 1}/{len(job.topics)}",
                job.current_topic(),
                job.last_status,
            ]
            for job in jobs
        ]

    def history_rows(self, limit: int = 40) -> list[list[Any]]:
        with self._lock:
            rows = list(reversed(self.history[-limit:]))
        return [
            [
                row.get("started", ""),
                row.get("job", ""),
                row.get("topic", ""),
                row.get("status", ""),
                row.get("duration", ""),
                row.get("run_dir", ""),
            ]
            for row in rows
        ]

    # -- execution --------------------------------------------------------
    def _options_for(self, job: Job) -> tuple[Settings, PipelineOptions]:
        data = dict(job.options)
        settings = Settings.from_env()
        settings.collection = data.get("collection") or self.settings.collection
        settings.offline = bool(data.get("offline", self.settings.offline))
        settings.keep_references = int(data.get("keep_references", self.settings.keep_references))
        settings.max_queries = int(data.get("max_queries", self.settings.max_queries))
        settings.seed = int(data.get("seed", self.settings.seed))
        options = PipelineOptions(
            audience=data.get("audience", ""),
            garment=data.get("garment", "dark"),
            aggressiveness=int(data.get("aggressiveness", 5)),
            variants=list(data.get("variants", ["A", "B", "C"])),
            generate=bool(data.get("generate", True)),
            generate_keys=list(data.get("generate_keys", [])),
            build_mockup=bool(data.get("build_mockup", True)),
        )
        return settings, options

    def run_job(self, job_id: str) -> dict[str, Any]:
        """Execute one job now. Blocking — the worker thread calls this."""
        with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                return {"status": "missing job"}
            topic = job.current_topic()
            self.current = job.id
        if not topic:
            self.current = ""
            return {"status": "no topics configured"}

        started = _now()
        settings, options = self._options_for(job)
        entry: dict[str, Any] = {
            "job": job.name,
            "job_id": job.id,
            "topic": topic,
            "started": _fmt(started),
            "status": "running",
            "run_dir": "",
            "duration": "",
        }
        self.on_event(f"▶ {job.name}: {topic}")
        try:
            if job.autonomous:
                # The bot picks its own subject at fire time, then designs it.
                auto = run_autopilot(
                    settings, options,
                    designs=int(job.options.get("designs", settings.autopilot_designs)),
                    log=lambda line: self.on_event(f"  {line}"),
                )
                entry["topic"] = ", ".join(auto.topics) or "(nothing cleared the filters)"
                entry["run_dir"] = auto.runs[-1].run_dir if auto.runs else ""
                entry["recommended"] = auto.runs[-1].recommended if auto.runs else ""
                entry["discovered"] = [
                    {"topic": o.topic, "score": o.overall, "growth_3m": o.growth_3m}
                    for o in (auto.report.opportunities if auto.report else [])
                ]
                entry["status"] = "ok" if auto.runs else "no opportunity cleared the filters"
            else:
                result = run_pipeline(topic, settings, options, log=lambda line: self.on_event(f"  {line}"))
                entry["status"] = "failed" if any("run failed" in w for w in result.warnings) else "ok"
                entry["run_dir"] = result.run_dir
                entry["recommended"] = result.recommended
        except Exception as exc:
            entry["status"] = f"error: {type(exc).__name__}: {exc}"
        finally:
            entry["duration"] = f"{(_now() - started).total_seconds():.0f}s"
            with self._lock:
                job.last_run = _fmt(started)
                job.last_status = entry["status"]
                job.last_run_dir = entry["run_dir"]
                job.runs_completed += 1
                job.cursor += 1
                job.next_run = job.compute_next()
                if job.cadence == "once":
                    job.enabled = False
                self.history.append(entry)
                self.current = ""
                self.save()
            self.on_event(f"■ {job.name}: {entry['status']} ({entry['duration']})")
        return entry

    def due_jobs(self, moment: datetime | None = None) -> list[Job]:
        moment = moment or _now()
        with self._lock:
            due = []
            for job in self.jobs.values():
                if not job.enabled or not job.runnable():
                    continue
                scheduled = _parse(job.next_run)
                if scheduled and scheduled <= moment:
                    due.append(job)
            return sorted(due, key=lambda j: j.next_run)

    def _loop(self) -> None:
        self.on_event("scheduler started")
        while not self._stop.is_set():
            try:
                for job in self.due_jobs():
                    if self._stop.is_set():
                        break
                    self.run_job(job.id)
            except Exception as exc:  # a scheduler must not die on one bad job
                self.on_event(f"scheduler error: {type(exc).__name__}: {exc}")
            self._stop.wait(self.tick_seconds)
        self.on_event("scheduler stopped")

    def start(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="archivist-scheduler", daemon=True)
            self._thread.start()
            return True

    def stop(self) -> bool:
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                return False
            self._stop.set()
            thread = self._thread
        thread.join(timeout=2.0)
        return True

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def status(self) -> dict[str, Any]:
        with self._lock:
            enabled = [job for job in self.jobs.values() if job.enabled and job.runnable()]
            upcoming = sorted((job.next_run, job.name, job.current_topic()) for job in enabled if job.next_run)
        return {
            "running": self.running,
            "jobs": len(self.jobs),
            "active_jobs": len(enabled),
            "current": self.jobs[self.current].name if self.current in self.jobs else "",
            "next": f"{upcoming[0][0]} — {upcoming[0][1]}: {upcoming[0][2]}" if upcoming else "nothing scheduled",
            "completed": sum(job.runs_completed for job in self.jobs.values()),
        }


# --- auto planning -------------------------------------------------------

FACETS = [
    "{era} {theme} archive",
    "{geography} {theme} survey",
    "{theme} recorded on {medium}",
    "{theme} filed by the {institution}",
    "{theme} — damage report",
    "{theme} — specimen study",
    "{theme} — chain of custody",
    "{theme} — decommissioning record",
    "{theme} — witness statement",
    "{theme} — restricted appendix",
]


def plan_topics(theme: str, count: int = 6, *, seed: int = 0) -> list[str]:
    """Expand one theme into a collection's worth of distinct, related topics."""
    theme = headline(theme.strip()) or "Untitled"
    rng = random.Random(f"plan|{theme}|{seed}")
    shapes = rng.sample(FACETS, k=min(len(FACETS), max(1, count)))
    topics: list[str] = []
    for shape in shapes:
        topic = shape.format(
            theme=theme,
            era=rng.choice(ERAS),
            geography=rng.choice(GEOGRAPHIES),
            medium=rng.choice(MEDIUMS),
            institution=rng.choice(INSTITUTIONS),
        )
        if topic not in topics:
            topics.append(topic)
    while len(topics) < count:  # count can exceed the facet pool
        extra = f"{theme} — appendix {len(topics) + 1:02d}"
        topics.append(extra)
    return topics[:count]


def plan_preview(
    topics: list[str],
    *,
    cadence: str = "daily",
    interval_minutes: int = 720,
    at_time: str = "09:00",
    weekday: int = 0,
    start: datetime | None = None,
) -> list[list[str]]:
    """When each planned topic would actually run, for the preview table."""
    probe = Job(
        id="preview", name="preview", topics=topics, cadence=cadence,
        interval_minutes=interval_minutes, at_time=at_time, weekday=weekday,
    )
    moment = start or _now()
    rows: list[list[str]] = []
    for index, topic in enumerate(topics, 1):
        moment = _parse(probe.compute_next(after=moment)) or moment + timedelta(minutes=interval_minutes)
        rows.append([str(index), _fmt(moment), topic])
    return rows
