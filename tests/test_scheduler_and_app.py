"""Scheduler, deployment artefacts and the Gradio surface."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from archivist import deploy
from archivist.config import Settings, load_env
from archivist.scheduler import Job, Scheduler, plan_preview, plan_topics


# --- jobs --------------------------------------------------------------
def test_next_run_is_always_in_the_future():
    base = datetime(2026, 5, 1, 10, 30, 0)

    interval = Job(id="1", name="i", topics=["t"], cadence="interval", interval_minutes=90)
    assert interval.compute_next(after=base) == "2026-05-01 12:00:00"

    daily = Job(id="2", name="d", topics=["t"], cadence="daily", at_time="09:00")
    assert daily.compute_next(after=base) == "2026-05-02 09:00:00"

    # 1 May 2026 is a Friday; the next Monday is the 4th.
    weekly = Job(id="3", name="w", topics=["t"], cadence="weekly", at_time="08:00", weekday=0)
    assert weekly.compute_next(after=base) == "2026-05-04 08:00:00"

    once = Job(id="4", name="o", topics=["t"], cadence="once", next_run="2020-01-01 00:00:00")
    assert once.compute_next(after=base) == "", "a fired one-shot must not reschedule itself"


def test_job_cycles_through_its_topics():
    job = Job(id="5", name="plan", topics=["a", "b", "c"])
    assert job.current_topic() == "a"
    job.cursor += 1
    assert job.current_topic() == "b"
    job.cursor += 2
    assert job.current_topic() == "a", "the cursor wraps"


def test_scheduler_persists_jobs_between_instances(settings):
    scheduler = Scheduler(settings)
    job = scheduler.create_job("plan", ["one", "two"], cadence="daily", at_time="07:30")

    reloaded = Scheduler(settings)
    assert job.id in reloaded.jobs
    assert reloaded.jobs[job.id].topics == ["one", "two"]
    assert reloaded.jobs[job.id].describe() == "daily at 07:30"

    assert reloaded.toggle_job(job.id, False)
    assert not Scheduler(settings).jobs[job.id].enabled
    assert reloaded.remove_job(job.id)
    assert job.id not in Scheduler(settings).jobs


def test_due_jobs_only_returns_enabled_jobs_whose_time_has_passed(settings):
    scheduler = Scheduler(settings)
    past = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    future = (datetime.now() + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")

    due = scheduler.create_job("due", ["x"], cadence="once", start_at=past)
    scheduler.create_job("later", ["y"], cadence="once", start_at=future)
    paused = scheduler.create_job("paused", ["z"], cadence="once", start_at=past, enabled=False)

    ids = {job.id for job in scheduler.due_jobs()}
    assert due.id in ids
    assert paused.id not in ids
    assert len(ids) == 1


def test_scheduler_runs_a_job_end_to_end(settings):
    events: list[str] = []
    scheduler = Scheduler(settings, on_event=events.append)
    job = scheduler.create_job(
        "offline plan", ["tidal barrier maintenance"], cadence="once",
        options={"collection": "test", "generate": False, "offline": True},
    )

    entry = scheduler.run_job(job.id)
    assert entry["status"] == "ok", entry
    assert Path(entry["run_dir"], "manifest.json").is_file()

    stored = scheduler.jobs[job.id]
    assert stored.runs_completed == 1
    assert stored.cursor == 1
    assert not stored.enabled, "a one-shot disables itself after firing"
    assert scheduler.history and scheduler.history[-1]["topic"] == "tidal barrier maintenance"
    assert any("offline plan" in event for event in events)


def test_scheduler_start_and_stop_are_idempotent(settings):
    scheduler = Scheduler(settings, tick_seconds=1)
    assert scheduler.start() is True
    assert scheduler.start() is False, "starting twice must not spawn a second thread"
    assert scheduler.running
    assert scheduler.stop() is True
    assert scheduler.stop() is False
    assert not scheduler.running


# --- auto-plan ---------------------------------------------------------
def test_plan_topics_are_distinct_and_deterministic():
    first = plan_topics("north sea oil decommissioning", 6, seed=0)
    second = plan_topics("north sea oil decommissioning", 6, seed=0)

    assert first == second
    assert len(set(first)) == 6
    assert all("North Sea Oil Decommissioning" in topic for topic in first)
    assert plan_topics("same theme", 4, seed=1) != plan_topics("same theme", 4, seed=2)


def test_plan_preview_is_ordered_and_covers_every_topic():
    topics = plan_topics("harbour cranes", 4, seed=0)
    rows = plan_preview(topics, cadence="daily", at_time="09:00")

    assert len(rows) == 4
    times = [row[1] for row in rows]
    assert times == sorted(times), "the preview must run forward in time"
    assert [row[2] for row in rows] == topics


# --- config ------------------------------------------------------------
def test_env_file_is_loaded_without_clobbering_real_env(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        'BFL_API_KEY="from-file"\n# comment\nexport ARCHIVIST_COLLECTION=drop-01\nBROKEN LINE\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BFL_API_KEY", "from-environment")

    loaded = load_env(tmp_path)
    assert loaded["BFL_API_KEY"] == "from-file"
    assert loaded["ARCHIVIST_COLLECTION"] == "drop-01"

    settings = Settings.from_env(tmp_path)
    assert settings.bfl_api_key == "from-environment", "a real env var wins over .env"
    assert settings.collection == "drop-01"


def test_redacted_settings_never_expose_a_key(tmp_path, monkeypatch):
    monkeypatch.setenv("BFL_API_KEY", "super-secret-value")
    redacted = Settings.from_env(tmp_path).redacted()

    assert redacted["bfl_api_key"] == "set"
    assert "super-secret-value" not in str(redacted)


def test_capability_report_explains_what_is_missing(tmp_path, monkeypatch):
    for key in ("BFL_API_KEY", "PEXELS_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    report = Settings.from_env(tmp_path).capability_report()

    assert "BFL_API_KEY" in report["bfl"]
    assert report["duckduckgo"].startswith("ready")


# --- creative assist (OpenAI) ------------------------------------------
def test_llm_is_inert_without_a_key():
    from archivist.llm import LLM

    llm = LLM(api_key="", model="gpt-5.1")
    assert not llm.available
    ok, detail = llm.check()
    assert not ok and "OPENAI_API_KEY" in detail

    # Every refinement must return None rather than raising, so the pipeline
    # silently keeps its deterministic output.
    ladder = __import__("archivist.trends", fromlist=["derive_ladder"]).derive_ladder("test", seed=0)
    assert llm.refine_ladder(ladder, topic="test") is None
    assert llm.extra_queries(topic="test", ladder=ladder, existing=[]) == []


def test_responses_payloads_are_parsed_including_reasoning_items():
    from archivist.llm import _extract_json, _text_from_chat, _text_from_responses

    reasoning_shaped = {
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text": '{"ok":true}'}]},
        ]
    }
    assert _text_from_responses(reasoning_shaped) == '{"ok":true}'
    assert _text_from_responses({"output_text": '{"ok":1}'}) == '{"ok":1}'
    assert _text_from_chat({"choices": [{"message": {"content": "hello"}}]}) == "hello"

    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('here you go {"a": 2} — done') == {"a": 2}
    assert _extract_json("not json at all") is None


def test_settings_carry_the_openai_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.1-mini")
    monkeypatch.delenv("ARCHIVIST_OFFLINE", raising=False)
    settings = Settings.from_env(tmp_path)

    assert settings.can_use_llm
    assert settings.openai_model == "gpt-5.1-mini"
    assert settings.openai_base_url == "https://api.openai.com/v1"
    assert settings.redacted()["openai_api_key"] == "set"
    assert "sk-test" not in str(settings.redacted())


# --- deployment --------------------------------------------------------
def test_deployment_artefacts_are_written_with_the_chosen_port(tmp_path):
    written = deploy.materialise(tmp_path / "deploy", port=8123, image="archivist:test")
    names = {Path(path).name for path in written}

    assert {"Dockerfile", "docker-compose.yml", "archivist.service",
            "windows-task.xml", "space_app.py", "NOTES.md"} <= names
    assert "8123" in (tmp_path / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert "archivist:test" in (tmp_path / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")


# --- the app -----------------------------------------------------------
gradio = pytest.importorskip("gradio", reason="gradio is only needed for the UI")


def test_app_builds_and_helpers_respond(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHIVIST_OFFLINE", "1")
    monkeypatch.setenv("ARCHIVIST_RUNS_DIR", str(tmp_path / "runs"))
    from archivist import app as app_module

    demo = app_module.build_app()
    assert demo is not None

    stats, rows = app_module.monitor_refresh()
    assert "runs" in stats
    assert isinstance(rows, list)

    topics, preview = app_module.build_plan("coastal erosion", 3, 0, "daily", 720, "09:00", "Monday")
    assert len(topics.splitlines()) == 3
    assert len(preview) == 3


def test_writing_env_from_the_setup_tab_preserves_unrelated_keys(tmp_path, monkeypatch):
    from archivist import app as app_module

    env_file = tmp_path / ".env"
    env_file.write_text("# header\nSOMETHING_ELSE=keep-me\nBFL_API_KEY=old\n", encoding="utf-8")
    monkeypatch.setattr(app_module.STATE, "root", tmp_path)

    app_module.write_env({"BFL_API_KEY": "new", "PEXELS_API_KEY": "", "ARCHIVIST_COLLECTION": "drop"})
    written = env_file.read_text(encoding="utf-8")

    assert "SOMETHING_ELSE=keep-me" in written
    assert "BFL_API_KEY=new" in written
    assert "ARCHIVIST_COLLECTION=drop" in written
    assert "PEXELS_API_KEY" not in written, "an empty field must not overwrite or add a key"
