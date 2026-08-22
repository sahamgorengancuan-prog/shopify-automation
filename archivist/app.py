"""The Gradio control room.

Six tabs, one job each:

  ① SETUP       keys, defaults, and a .env written for you
  ② CONNECTION  one button that proves every dependency before you spend credits
  ③ STUDIO      run the pipeline with a live log, galleries and print packages
  ④ MONITOR     every past run, its report, its assets, its log
  ⑤ AUTO-PLAN   turn one theme into a scheduled collection and let it run
  ⑥ DEPLOY      Docker / systemd / Windows Task / HF Space, written out filled in

Run it with ``python -m archivist.app`` (or the .bat / .sh launchers).
"""

from __future__ import annotations

import argparse
import os
import queue
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr

from . import connectivity, deploy as deploy_mod, storage
from .config import Settings, load_env
from .models import RunResult
from .pipeline import PipelineOptions, run as run_pipeline
from .scheduler import CADENCES, WEEKDAYS, Scheduler, plan_preview, plan_topics

GARMENTS = ["dark", "faded-black", "black", "light", "white", "sand"]
ASPECTS = ["3:4", "1:1", "2:3", "4:3", "9:16", "16:9"]
BFL_MODELS = ["flux-kontext-max", "flux-kontext-pro", "flux-pro-1.1-ultra", "flux-pro-1.1", "flux-dev"]
ANTHROPIC_MODELS = ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"]

CSS = """
:root { --arc-line:#2a2a2e; --arc-dim:#8b877e; --arc-ink:#e9e6df; --arc-accent:#c8b98a; }
.gradio-container { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace !important;
  max-width: 1480px !important; }
#arc-head { border-bottom:1px solid var(--arc-line); padding-bottom:14px; margin-bottom:10px; }
#arc-head h1 { font-size:20px !important; letter-spacing:.5em; text-transform:uppercase; margin:0 0 6px; }
#arc-head p { color:var(--arc-dim); font-size:12px; letter-spacing:.13em; text-transform:uppercase; margin:0; }
.arc-card { border:1px solid var(--arc-line); border-radius:6px; padding:14px 16px; }
.arc-note { color:var(--arc-dim); font-size:12px; line-height:1.7; }
.arc-status { font-size:13px; line-height:1.7; }
.arc-status code { font-size:12px; }
.arc-bar { font-family: ui-monospace, monospace; letter-spacing:-.05em; }
footer { display:none !important; }
.tabitem { padding-top:16px !important; }
"""

HEADER = """<div id="arc-head">
<h1>Archivist</h1>
<p>trend research → reference mining → BFL context → apparel graphics</p>
</div>"""


# --------------------------------------------------------------------------
# shared state
# --------------------------------------------------------------------------
class AppState:
    """One process-wide holder for settings, the scheduler and the last run."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root or Path.cwd())
        load_env(self.root)
        self.settings = Settings.from_env(self.root)
        self.sched_log: deque[str] = deque(maxlen=500)
        self.scheduler = Scheduler(self.settings, on_event=self._on_event)
        self.cancel = threading.Event()
        self.running = threading.Event()
        self.last_result: RunResult | None = None
        self.selected_run: str = ""

    def _on_event(self, message: str) -> None:
        self.sched_log.append(f"{datetime.now().strftime('%H:%M:%S')}  {message}")

    def scheduler_log(self) -> str:
        return "\n".join(self.sched_log) or "scheduler idle — no events yet"

    def refresh_settings(self, **overrides: Any) -> Settings:
        self.settings = Settings.from_env(self.root, **{k: v for k, v in overrides.items() if v is not None})
        self.scheduler.settings = self.settings
        return self.settings


STATE = AppState()


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _bar(fraction: float, width: int = 34) -> str:
    filled = int(max(0.0, min(1.0, fraction)) * width)
    return "█" * filled + "░" * (width - filled)


def env_path() -> Path:
    return STATE.root / ".env"


def write_env(values: dict[str, str]) -> Path:
    """Merge values into .env, preserving anything already there."""
    path = env_path()
    existing: list[str] = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen: set[str] = set()
    out: list[str] = []

    for line in existing:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in values:
            value = values[key]
            seen.add(key)
            if value == "":          # empty means "leave what was there"
                out.append(line)
            else:
                out.append(f"{key}={value}")
        else:
            out.append(line)

    for key, value in values.items():
        if key not in seen and value != "":
            out.append(f"{key}={value}")

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    for key, value in values.items():
        if value != "":
            os.environ[key] = value
    return path


def capability_markdown(settings: Settings) -> str:
    rows = settings.capability_report()

    def icon(text: str) -> str:
        if text.startswith("ready"):
            return "🟢"
        if text.startswith("offline"):
            return "⚪"
        return "🟡"

    lines = [
        "| service | state |",
        "|---|---|",
        *[f"| {name} | {icon(value)} {value} |" for name, value in rows.items()],
    ]
    lines += [
        "",
        f"**runs directory** `{Path(settings.runs_dir).resolve()}`  ·  "
        f"**collection** `{settings.collection}`  ·  "
        f"**model** `{settings.bfl_model}`  ·  "
        f"**print** {settings.print_width_in:g}in @ {settings.print_dpi} dpi",
    ]
    return "\n".join(lines)


def concept_rows(result: RunResult | None) -> list[list[Any]]:
    if not result:
        return []
    return [
        [
            concept.key,
            concept.lane,
            concept.name,
            concept.scores.trend_fit,
            concept.scores.niche_fit,
            concept.scores.visual_uniqueness,
            concept.scores.apparel_potential,
            concept.scores.overall,
            "pass" if concept.gate.get("passed") else "revised: " + ", ".join(concept.gate.get("failing", [])),
            "★" if concept.key == result.recommended else "",
        ]
        for concept in result.concepts
    ]


def result_files(result: RunResult | None) -> list[str]:
    if not result:
        return []
    run_dir = Path(result.run_dir)
    files = [
        str(path)
        for name in ("report.md", "manifest.json", "board.html")
        if (path := run_dir / name).is_file()
    ]
    for concept in result.concepts:
        print_file = concept.print_assets.get("print")
        if isinstance(print_file, str) and print_file and Path(print_file).is_file():
            files.append(print_file)
    return files


def summary_markdown(result: RunResult | None) -> str:
    if not result:
        return "_no run yet_"
    direction = result.direction
    ladder = result.ladder
    lines = [
        f"### {direction.style_name if direction else '—'}",
        f"_{direction.thesis if direction else ''}_",
        "",
        f"- **micro-niche:** {ladder.micro_niche if ladder else '—'}",
        f"- **references:** {len(result.references)} kept of {result.candidates} mined",
        f"- **recommended:** {result.recommended or '—'}",
        f"- **run directory:** `{result.run_dir}`",
    ]
    if direction:
        lines += ["", "**Visual DNA**", *[f"- {line}" for line in direction.dna.as_lines()]]
    if result.warnings:
        lines += ["", "**Warnings**", *[f"- {warning}" for warning in result.warnings[:10]]]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# ① setup
# --------------------------------------------------------------------------
def save_setup(
    bfl_key: str,
    pexels_key: str,
    anthropic_key: str,
    bfl_model: str,
    anthropic_model: str,
    collection: str,
    garment: str,
    aspect: str,
    width_in: float,
    dpi: int,
    runs_dir: str,
    offline: bool,
) -> tuple[str, str]:
    values = {
        "BFL_API_KEY": bfl_key.strip(),
        "PEXELS_API_KEY": pexels_key.strip(),
        "ANTHROPIC_API_KEY": anthropic_key.strip(),
        "BFL_MODEL": bfl_model,
        "ANTHROPIC_MODEL": anthropic_model,
        "ARCHIVIST_COLLECTION": collection.strip() or "default",
        "ARCHIVIST_GARMENT": garment,
        "ARCHIVIST_ASPECT_RATIO": aspect,
        "ARCHIVIST_PRINT_WIDTH_IN": str(width_in),
        "ARCHIVIST_PRINT_DPI": str(int(dpi)),
        "ARCHIVIST_RUNS_DIR": runs_dir.strip() or "runs",
        "ARCHIVIST_OFFLINE": "1" if offline else "0",
    }
    path = write_env(values)
    os.environ["ARCHIVIST_OFFLINE"] = "1" if offline else "0"
    settings = STATE.refresh_settings()
    note = (
        f"✅ saved to `{path}` — keys are stored locally only and are never written into a run manifest."
    )
    return note, capability_markdown(settings)


def setup_tab() -> None:
    gr.Markdown(
        "### ① Setup\n"
        "Paste the keys you have. Nothing here is mandatory: with no keys at all the pipeline still "
        "runs end to end in offline mode using synthetic references, which is the fastest way to see "
        "what it does before spending credits."
    )
    with gr.Row():
        with gr.Column(scale=3):
            with gr.Group():
                bfl_key = gr.Textbox(
                    label="BFL_API_KEY", type="password", placeholder="required to generate artwork",
                    info="api.bfl.ai — Kontext models take the mined references as context images",
                )
                pexels_key = gr.Textbox(
                    label="PEXELS_API_KEY", type="password", placeholder="optional",
                    info="adds contemporary photography and cinematic light to the reference pool",
                )
                anthropic_key = gr.Textbox(
                    label="ANTHROPIC_API_KEY", type="password", placeholder="optional",
                    info="refines the niche ladder, queries, Visual DNA and art direction",
                )
            with gr.Row():
                bfl_model = gr.Dropdown(BFL_MODELS, value=STATE.settings.bfl_model, label="BFL model")
                anthropic_model = gr.Dropdown(
                    ANTHROPIC_MODELS, value=STATE.settings.anthropic_model, label="Creative assist model"
                )
            with gr.Row():
                collection = gr.Textbox(
                    value=STATE.settings.collection, label="Collection",
                    info="collections share a style lock: same visual language, different subjects",
                )
                garment = gr.Dropdown(GARMENTS, value=STATE.settings.garment, label="Default garment")
                aspect = gr.Dropdown(ASPECTS, value=STATE.settings.aspect_ratio, label="Aspect ratio")
            with gr.Row():
                width_in = gr.Number(value=STATE.settings.print_width_in, label="Print width (in)", precision=1)
                dpi = gr.Number(value=STATE.settings.print_dpi, label="Print DPI", precision=0)
                runs_dir = gr.Textbox(value=str(STATE.settings.runs_dir), label="Runs directory")
            offline = gr.Checkbox(
                value=STATE.settings.offline, label="Offline mode (synthetic references, no network calls)"
            )
            save_button = gr.Button("Save configuration", variant="primary")
            saved_note = gr.Markdown("", elem_classes="arc-note")
        with gr.Column(scale=2):
            gr.Markdown("#### Current capability", elem_classes="arc-note")
            capability = gr.Markdown(capability_markdown(STATE.settings), elem_classes="arc-status")
            refresh_capability = gr.Button("Refresh", size="sm")
            with gr.Accordion("Where do the keys come from?", open=False):
                gr.Markdown(
                    "- **BFL** — https://api.bfl.ai, dashboard → API keys. Charged per generation.\n"
                    "- **Pexels** — https://www.pexels.com/api/, free key, attribution is carried "
                    "through onto the reference board automatically.\n"
                    "- **Anthropic** — https://console.anthropic.com. Optional; every stage has a "
                    "deterministic fallback.\n\n"
                    "Keys are written to `.env` in the project folder and loaded on start. "
                    "They never enter a run manifest, a prompt file or a log line.",
                    elem_classes="arc-note",
                )
            with gr.Accordion("Launching it elsewhere", open=False):
                gr.Markdown(
                    "```\n"
                    "python -m archivist.app --port 7860          # local\n"
                    "python -m archivist.app --host 0.0.0.0       # on your network\n"
                    "python -m archivist.app --share              # temporary public URL\n"
                    "python -m archivist.app --auth user:password # password gate\n"
                    "```\n"
                    "Windows: `run_archivist.bat` · Ubuntu: `./scripts/linux/archivist.sh app`",
                    elem_classes="arc-note",
                )

    save_button.click(
        save_setup,
        inputs=[bfl_key, pexels_key, anthropic_key, bfl_model, anthropic_model, collection,
                garment, aspect, width_in, dpi, runs_dir, offline],
        outputs=[saved_note, capability],
    )
    refresh_capability.click(lambda: capability_markdown(STATE.refresh_settings()), outputs=capability)


# --------------------------------------------------------------------------
# ② connection
# --------------------------------------------------------------------------
def run_connection_checks(include_generation: bool) -> tuple[str, list[list[str]]]:
    settings = STATE.refresh_settings()
    results = connectivity.run_checks(settings, include_generation=include_generation)
    return connectivity.summarise(results), connectivity.as_rows(results)


def connection_tab() -> None:
    gr.Markdown(
        "### ② Connection test\n"
        "Probe every dependency before a run: Python and Pillow, disk, DuckDuckGo, Pexels, the BFL "
        "key, and the optional creative assist. A red row is a blocker; a yellow row degrades one "
        "stage and the pipeline still completes."
    )
    with gr.Row():
        include_generation = gr.Checkbox(value=True, label="Include BFL key probe")
        test_button = gr.Button("Run all checks", variant="primary", scale=2)
    summary = gr.Markdown("_not tested yet_", elem_classes="arc-status")
    table = gr.Dataframe(
        headers=["state", "service", "latency", "detail"],
        datatype=["str", "str", "str", "str"],
        interactive=False,
        wrap=True,
        label="Results",
    )
    with gr.Accordion("Common failures and what they mean", open=False):
        gr.Markdown(
            "- **duckduckgo fail** — rate limited or blocked by a network policy. Wait a minute, or "
            "install `ddgs` (`pip install ddgs`) which tracks endpoint changes, or switch on offline mode.\n"
            "- **pexels 401** — key typo, or the key was revoked. Optional; mining continues without it.\n"
            "- **bfl 401/403** — key rejected. Check for a trailing space when pasting.\n"
            "- **storage low disk** — a run writes 20–60 reference images plus print files; keep a "
            "few hundred MB free.\n"
            "- **anthropic fail** — optional. Every stage it touches has a deterministic fallback.",
            elem_classes="arc-note",
        )
    test_button.click(run_connection_checks, inputs=include_generation, outputs=[summary, table])


# --------------------------------------------------------------------------
# ③ studio
# --------------------------------------------------------------------------
def studio_run(
    topic: str,
    audience: str,
    collection: str,
    garment: str,
    aggressiveness: int,
    variants: list[str],
    generate: bool,
    generate_keys: list[str],
    keep_references: int,
    max_queries: int,
    per_query: int,
    offline: bool,
    seed: int,
    include_text: bool,
    build_mockup: bool,
    use_llm: bool,
):
    """Streaming run: yields status + log while the pipeline works in a thread."""
    blank = [gr.update()] * 8
    if not topic.strip():
        yield ("⚠️ enter a topic first", "", *blank)
        return

    settings = STATE.refresh_settings(
        collection=collection.strip() or "default",
        offline=bool(offline),
        keep_references=int(keep_references),
        max_queries=int(max_queries),
        candidates_per_query=int(per_query),
        seed=int(seed),
        garment=garment,
    )
    options = PipelineOptions(
        audience=audience.strip(),
        garment=garment,
        aggressiveness=int(aggressiveness),
        variants=list(variants) or ["A", "B", "C"],
        generate=bool(generate),
        generate_keys=[k for k in generate_keys] if generate_keys else [],
        include_text=bool(include_text),
        build_mockup=bool(build_mockup),
        use_llm=bool(use_llm),
    )

    STATE.cancel.clear()
    STATE.running.set()
    events: queue.Queue = queue.Queue()
    box: dict[str, Any] = {}
    progress_state = {"fraction": 0.0, "message": "starting"}

    def on_progress(fraction: float, message: str) -> None:
        progress_state["fraction"] = fraction
        progress_state["message"] = message

    def worker() -> None:
        try:
            box["result"] = run_pipeline(
                topic, settings, options,
                progress=on_progress,
                log=events.put,
                cancel=STATE.cancel.is_set,
            )
        except Exception as exc:  # surfaced in the status line, not swallowed
            box["error"] = exc
        finally:
            events.put(None)

    thread = threading.Thread(target=worker, name="archivist-run", daemon=True)
    thread.start()

    lines: list[str] = []
    finished = False
    last_emit = 0.0
    while not finished:
        try:
            item = events.get(timeout=0.4)
            if item is None:
                finished = True
            else:
                lines.append(str(item))
        except queue.Empty:
            pass
        now = time.time()
        if finished or now - last_emit > 0.35:
            last_emit = now
            status = (
                f"`{_bar(progress_state['fraction'])}` **{progress_state['fraction'] * 100:4.0f}%** — "
                f"{progress_state['message']}"
            )
            yield (status, "\n".join(lines[-400:]), *blank)

    thread.join(timeout=1.0)
    STATE.running.clear()

    if "error" in box:
        yield (f"❌ run failed — {type(box['error']).__name__}: {box['error']}", "\n".join(lines[-400:]), *blank)
        return

    result: RunResult = box["result"]
    STATE.last_result = result
    STATE.selected_run = result.run_dir

    cancelled = any("cancelled" in warning for warning in result.warnings)
    status = (
        "⏹ cancelled — partial run saved" if cancelled
        else f"✅ done — {len(result.references)} references, {len(result.concepts)} directions, "
             f"recommended **{result.recommended}**"
    )
    keys = [concept.key for concept in result.concepts]
    yield (
        status,
        "\n".join(lines[-400:]),
        storage.gallery_paths(result, kind="references"),
        concept_rows(result),
        storage.gallery_paths(result, kind="artwork"),
        storage.gallery_paths(result, kind="all"),
        summary_markdown(result),
        result_files(result),
        gr.update(choices=keys, value=result.recommended or (keys[0] if keys else None)),
        result.run_dir,
    )


def show_prompt(key: str) -> tuple[str, str]:
    result = STATE.last_result
    if not result or not key:
        return "", ""
    concept = result.concept(key)
    if not concept:
        return "", ""
    return concept.prompt, concept.negative_prompt


def regenerate_variant(key: str, seed: int, garment: str) -> tuple[str, list, list]:
    result = STATE.last_result
    if not result:
        return "no run loaded", [], []
    settings = STATE.refresh_settings()
    if not settings.can_generate:
        return "BFL_API_KEY is not set — nothing to regenerate with", [], []
    from .pipeline import regenerate as regenerate_run

    try:
        regenerate_run(
            result, key, settings,
            PipelineOptions(garment=garment),
            seed=int(seed) or None,
        )
    except Exception as exc:
        return f"❌ {type(exc).__name__}: {exc}", [], []
    return (
        f"✅ regenerated {key}",
        storage.gallery_paths(result, kind="artwork"),
        storage.gallery_paths(result, kind="all"),
    )


def studio_tab() -> None:
    gr.Markdown(
        "### ③ Studio\n"
        "One topic in, a full run out: niche ladder → queries → mined references → scored board → "
        "Visual DNA → art direction → three ranked directions → BFL prompts → artwork → print package."
    )
    with gr.Row():
        with gr.Column(scale=2):
            topic = gr.Textbox(
                label="Topic / trend / cultural phenomenon",
                placeholder="e.g. deep sea salvage, competitive pigeon racing, 1998 solar eclipse",
                autofocus=True,
            )
            audience = gr.Textbox(label="Target audience (optional)", placeholder="who wears this")
            with gr.Row():
                collection = gr.Textbox(value=STATE.settings.collection, label="Collection")
                garment = gr.Dropdown(GARMENTS, value=STATE.settings.garment, label="Garment")
                seed = gr.Number(value=0, label="Seed", precision=0)
            aggressiveness = gr.Slider(0, 10, value=5, step=1, label="Aggressiveness")
            with gr.Row():
                variants = gr.CheckboxGroup(
                    ["A", "B", "C"], value=["A", "B", "C"], label="Directions to develop",
                    info="A safe commercial · B niche cultural · C extreme experimental",
                )
            with gr.Row():
                generate = gr.Checkbox(value=True, label="Generate artwork (uses BFL credits)")
                generate_keys = gr.CheckboxGroup(
                    ["A", "B", "C"], value=[], label="Generate which",
                    info="empty = the recommended direction only",
                )
            with gr.Accordion("Advanced", open=False):
                with gr.Row():
                    keep_references = gr.Slider(4, 16, value=STATE.settings.keep_references, step=1,
                                                label="References to keep")
                    max_queries = gr.Slider(10, 30, value=STATE.settings.max_queries, step=1,
                                            label="Search queries")
                    per_query = gr.Slider(2, 12, value=STATE.settings.candidates_per_query, step=1,
                                          label="Candidates per query")
                with gr.Row():
                    offline = gr.Checkbox(value=STATE.settings.offline, label="Offline mode")
                    include_text = gr.Checkbox(value=True, label="Allow lettering in the artwork")
                    build_mockup = gr.Checkbox(value=True, label="Build garment mockup")
                    use_llm = gr.Checkbox(value=True, label="Use creative assist if a key is set")
            with gr.Row():
                run_button = gr.Button("Run pipeline", variant="primary", scale=3)
                cancel_button = gr.Button("Cancel", variant="stop", scale=1)
        with gr.Column(scale=3):
            status = gr.Markdown("_idle_", elem_classes="arc-status")
            log = gr.Textbox(label="Live log", lines=16, max_lines=16, interactive=False, autoscroll=True)
            run_dir_box = gr.Textbox(label="Run directory", interactive=False)

    with gr.Tabs():
        with gr.Tab("References"):
            refs_gallery = gr.Gallery(label="Selected references (roles in the caption)", columns=4,
                                      height=420, object_fit="cover")
        with gr.Tab("Directions"):
            concepts_df = gr.Dataframe(
                headers=["key", "lane", "name", "trend", "niche", "unique", "apparel", "overall", "gate", "rec"],
                datatype=["str"] * 3 + ["number"] * 5 + ["str", "str"],
                interactive=False, wrap=True, label="Ranked directions",
            )
        with gr.Tab("Prompt"):
            with gr.Row():
                variant_dd = gr.Dropdown(["A", "B", "C"], label="Variant", scale=1)
                regen_seed = gr.Number(value=0, label="Regenerate seed", precision=0, scale=1)
                regen_button = gr.Button("Regenerate this variant", scale=1)
            regen_note = gr.Markdown("", elem_classes="arc-note")
            prompt_box = gr.Textbox(label="BFL Context prompt", lines=22)
            negative_box = gr.Textbox(label="Negative constraints", lines=4)
        with gr.Tab("Artwork"):
            artwork_gallery = gr.Gallery(label="Generated artwork", columns=3, height=520, object_fit="contain")
        with gr.Tab("Print package"):
            print_gallery = gr.Gallery(label="Print file · separation · legibility · mockup",
                                       columns=4, height=460, object_fit="contain")
            files = gr.File(label="Download", file_count="multiple", interactive=False)
        with gr.Tab("Summary"):
            report_md = gr.Markdown("_no run yet_")

    run_event = run_button.click(
        studio_run,
        inputs=[topic, audience, collection, garment, aggressiveness, variants, generate, generate_keys,
                keep_references, max_queries, per_query, offline, seed, include_text, build_mockup, use_llm],
        outputs=[status, log, refs_gallery, concepts_df, artwork_gallery, print_gallery, report_md,
                 files, variant_dd, run_dir_box],
    )
    cancel_button.click(lambda: (STATE.cancel.set(), "⏹ cancelling after the current step…")[1], outputs=status,
                        cancels=[run_event])
    variant_dd.change(show_prompt, inputs=variant_dd, outputs=[prompt_box, negative_box])
    regen_button.click(
        regenerate_variant,
        inputs=[variant_dd, regen_seed, garment],
        outputs=[regen_note, artwork_gallery, print_gallery],
    )


# --------------------------------------------------------------------------
# ④ monitoring
# --------------------------------------------------------------------------
def monitor_refresh() -> tuple[str, list[list[Any]]]:
    settings = STATE.refresh_settings()
    data = storage.stats(settings.runs_dir)
    scheduler_status = STATE.scheduler.status()
    cards = (
        f"**{data['runs']}** runs  ·  **{data['generated_artworks']}** artworks  ·  "
        f"**{data['references']}** references  ·  **{data['failed']}** failed  ·  "
        f"**{data['disk_mb']} MB** on disk\n\n"
        f"collections: {', '.join(data['collections']) or '—'}  ·  latest: {data['latest']}\n\n"
        f"scheduler: {'🟢 running' if scheduler_status['running'] else '⚪ stopped'} — "
        f"{scheduler_status['active_jobs']} active job(s), next: {scheduler_status['next']}"
    )
    rows = [
        [r["created"], r["collection"], r["topic"], r["style"], r["refs"], r["concepts"],
         r["generated"], r["best_score"], r["recommended"], r["status"], r["run_dir"]]
        for r in storage.list_runs(settings.runs_dir, limit=100)
    ]
    return cards, rows


def monitor_select(evt: gr.SelectData, table: Any):
    """Load a run when its row is clicked."""
    try:
        row_index = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        rows = table.values.tolist() if hasattr(table, "values") else list(table)
        run_dir = rows[row_index][-1]
    except Exception:
        return "could not resolve that row", [], [], "", ""
    return load_run_dir(str(run_dir))


def load_run_dir(run_dir: str):
    path = Path(run_dir.strip())
    if not (path / "manifest.json").is_file():
        return f"no manifest in `{path}`", [], [], "", ""
    try:
        result = storage.load_run(path)
    except Exception as exc:
        return f"could not load run: {type(exc).__name__}: {exc}", [], [], "", ""
    STATE.last_result = result
    STATE.selected_run = str(path)
    report = (path / "report.md")
    report_text = report.read_text(encoding="utf-8") if report.is_file() else summary_markdown(result)
    return (
        summary_markdown(result),
        storage.gallery_paths(result, kind="references"),
        storage.gallery_paths(result, kind="all"),
        storage.tail_log(path, 120),
        report_text,
    )


def delete_selected(run_dir: str) -> str:
    if not run_dir.strip():
        return "nothing selected"
    ok = storage.delete_run(run_dir.strip())
    return f"🗑 deleted `{run_dir}`" if ok else f"could not delete `{run_dir}`"


def monitor_tab() -> None:
    gr.Markdown("### ④ Monitoring\nEvery run that has ever executed here, with its assets and log.")
    with gr.Row():
        refresh_button = gr.Button("Refresh", variant="primary")
        auto_refresh = gr.Checkbox(value=False, label="Auto-refresh every 15s")
    stats_md = gr.Markdown("_loading_", elem_classes="arc-status")
    runs_df = gr.Dataframe(
        headers=["created", "collection", "topic", "style", "refs", "dirs", "art", "best", "rec", "status", "run_dir"],
        datatype=["str", "str", "str", "str", "number", "number", "number", "number", "str", "str", "str"],
        interactive=False, wrap=True, label="Runs (click a row to open)",
    )
    with gr.Row():
        run_dir_input = gr.Textbox(label="Run directory", scale=4)
        load_button = gr.Button("Open", scale=1)
        delete_button = gr.Button("Delete", variant="stop", scale=1)
    detail_md = gr.Markdown("_select a run_", elem_classes="arc-status")
    with gr.Tabs():
        with gr.Tab("Assets"):
            detail_gallery = gr.Gallery(label="Artwork and print package", columns=4, height=420,
                                        object_fit="contain")
        with gr.Tab("References"):
            detail_refs = gr.Gallery(label="Reference board", columns=5, height=420, object_fit="cover")
        with gr.Tab("Report"):
            detail_report = gr.Markdown("")
        with gr.Tab("Log"):
            detail_log = gr.Textbox(label="run.log (tail)", lines=20, interactive=False)

    timer = gr.Timer(15, active=False)
    refresh_button.click(monitor_refresh, outputs=[stats_md, runs_df])
    timer.tick(monitor_refresh, outputs=[stats_md, runs_df])
    auto_refresh.change(lambda on: gr.Timer(15, active=bool(on)), inputs=auto_refresh, outputs=timer)
    runs_df.select(
        monitor_select, inputs=runs_df,
        outputs=[detail_md, detail_refs, detail_gallery, detail_log, detail_report],
    ).then(lambda: STATE.selected_run, outputs=run_dir_input)
    load_button.click(
        load_run_dir, inputs=run_dir_input,
        outputs=[detail_md, detail_refs, detail_gallery, detail_log, detail_report],
    )
    delete_button.click(delete_selected, inputs=run_dir_input, outputs=detail_md).then(
        monitor_refresh, outputs=[stats_md, runs_df]
    )


# --------------------------------------------------------------------------
# ⑤ auto-plan and scheduling
# --------------------------------------------------------------------------
def build_plan(theme: str, count: int, seed: int, cadence: str, interval_minutes: int,
               at_time: str, weekday: str) -> tuple[str, list[list[str]]]:
    if not theme.strip():
        return "", []
    topics = plan_topics(theme, int(count), seed=int(seed))
    preview = plan_preview(
        topics, cadence=cadence, interval_minutes=int(interval_minutes),
        at_time=at_time, weekday=WEEKDAYS.index(weekday) if weekday in WEEKDAYS else 0,
    )
    return "\n".join(topics), preview


def create_job(
    name: str, topics_text: str, cadence: str, interval_minutes: int, at_time: str, weekday: str,
    collection: str, garment: str, aggressiveness: int, variants: list[str], generate: bool,
    offline: bool, enabled: bool,
) -> tuple[str, list[list[Any]]]:
    topics = [line.strip() for line in topics_text.splitlines() if line.strip()]
    if not topics:
        return "⚠️ no topics — generate a plan or type one topic per line", STATE.scheduler.job_rows()
    job = STATE.scheduler.create_job(
        name or f"{topics[0][:30]} plan",
        topics,
        cadence=cadence,
        interval_minutes=int(interval_minutes),
        at_time=at_time,
        weekday=WEEKDAYS.index(weekday) if weekday in WEEKDAYS else 0,
        enabled=bool(enabled),
        options={
            "collection": collection.strip() or "default",
            "garment": garment,
            "aggressiveness": int(aggressiveness),
            "variants": list(variants) or ["A", "B", "C"],
            "generate": bool(generate),
            "offline": bool(offline),
        },
    )
    return (
        f"✅ job `{job.id}` created — {job.describe()}, {len(job.topics)} topics, next {job.next_run or '—'}",
        STATE.scheduler.job_rows(),
    )


def scheduler_start() -> tuple[str, str]:
    started = STATE.scheduler.start()
    return (
        "🟢 scheduler running" if started else "🟢 scheduler was already running",
        STATE.scheduler_log(),
    )


def scheduler_stop() -> tuple[str, str]:
    stopped = STATE.scheduler.stop()
    return ("⚪ scheduler stopped" if stopped else "⚪ scheduler was not running", STATE.scheduler_log())


def job_action(action: str, job_id: str) -> tuple[str, list[list[Any]], list[list[Any]]]:
    job_id = job_id.strip()
    if not job_id:
        return "enter a job id", STATE.scheduler.job_rows(), STATE.scheduler.history_rows()
    if action == "run":
        threading.Thread(target=STATE.scheduler.run_job, args=(job_id,), daemon=True).start()
        message = f"▶ running `{job_id}` now — watch the event log"
    elif action == "pause":
        message = ("⏸ paused" if STATE.scheduler.toggle_job(job_id, False) else "unknown job") + f" `{job_id}`"
    elif action == "resume":
        message = ("▶ resumed" if STATE.scheduler.toggle_job(job_id, True) else "unknown job") + f" `{job_id}`"
    else:
        message = ("🗑 removed" if STATE.scheduler.remove_job(job_id) else "unknown job") + f" `{job_id}`"
    return message, STATE.scheduler.job_rows(), STATE.scheduler.history_rows()


def scheduler_refresh() -> tuple[str, list[list[Any]], list[list[Any]], str]:
    status = STATE.scheduler.status()
    banner = (
        f"{'🟢 running' if status['running'] else '⚪ stopped'} · {status['active_jobs']} active job(s) · "
        f"{status['completed']} run(s) completed · next: {status['next']}"
        + (f" · currently: {status['current']}" if status["current"] else "")
    )
    return banner, STATE.scheduler.job_rows(), STATE.scheduler.history_rows(), STATE.scheduler_log()


def schedule_tab() -> None:
    gr.Markdown(
        "### ⑤ Auto-plan & schedule\n"
        "Give it one theme and it writes a collection plan — distinct but related topics, spread "
        "across a schedule. Every run in a collection inherits the same style lock, so the drop "
        "reads as one body of work instead of ten unrelated shirts."
    )
    with gr.Row():
        with gr.Column(scale=2):
            gr.Markdown("#### Plan", elem_classes="arc-note")
            theme = gr.Textbox(label="Theme", placeholder="e.g. North Sea oil decommissioning")
            with gr.Row():
                count = gr.Slider(2, 12, value=6, step=1, label="Designs in the plan")
                plan_seed = gr.Number(value=0, label="Seed", precision=0)
            with gr.Row():
                cadence = gr.Dropdown(list(CADENCES), value="daily", label="Cadence")
                interval_minutes = gr.Number(value=720, label="Interval (minutes)", precision=0)
            with gr.Row():
                at_time = gr.Textbox(value="09:00", label="At time (HH:MM, local)")
                weekday = gr.Dropdown(WEEKDAYS, value="Monday", label="Weekday (weekly only)")
            plan_button = gr.Button("Generate plan", variant="primary")
            topics_text = gr.Textbox(label="Topics (one per line — edit freely)", lines=8)
            preview_df = gr.Dataframe(
                headers=["#", "scheduled", "topic"], datatype=["str", "str", "str"],
                interactive=False, wrap=True, label="Schedule preview",
            )
        with gr.Column(scale=2):
            gr.Markdown("#### Job settings", elem_classes="arc-note")
            job_name = gr.Textbox(label="Job name", placeholder="Autumn drop")
            with gr.Row():
                job_collection = gr.Textbox(value=STATE.settings.collection, label="Collection")
                job_garment = gr.Dropdown(GARMENTS, value=STATE.settings.garment, label="Garment")
            job_aggressiveness = gr.Slider(0, 10, value=5, step=1, label="Aggressiveness")
            job_variants = gr.CheckboxGroup(["A", "B", "C"], value=["A", "B", "C"], label="Directions")
            with gr.Row():
                job_generate = gr.Checkbox(value=True, label="Generate artwork")
                job_offline = gr.Checkbox(value=STATE.settings.offline, label="Offline mode")
                job_enabled = gr.Checkbox(value=True, label="Enabled")
            create_button = gr.Button("Create scheduled job", variant="primary")
            create_note = gr.Markdown("", elem_classes="arc-note")
            gr.Markdown(
                "Scheduled runs use the keys in `.env`. Generation costs credits on every fire — "
                "start with generation off, or with offline mode, to watch the cadence behave first.",
                elem_classes="arc-note",
            )

    gr.Markdown("#### Scheduler", elem_classes="arc-note")
    with gr.Row():
        start_button = gr.Button("Start scheduler", variant="primary")
        stop_button = gr.Button("Stop scheduler", variant="stop")
        refresh_button = gr.Button("Refresh")
        live = gr.Checkbox(value=True, label="Live updates")
    sched_banner = gr.Markdown("⚪ stopped", elem_classes="arc-status")
    jobs_df = gr.Dataframe(
        headers=["id", "name", "state", "cadence", "next run", "topic", "current topic", "last status"],
        datatype=["str"] * 8, interactive=False, wrap=True, label="Jobs",
    )
    with gr.Row():
        job_id = gr.Textbox(label="Job id", scale=2)
        run_now_button = gr.Button("Run now", scale=1)
        pause_button = gr.Button("Pause", scale=1)
        resume_button = gr.Button("Resume", scale=1)
        remove_button = gr.Button("Remove", variant="stop", scale=1)
    action_note = gr.Markdown("", elem_classes="arc-note")
    with gr.Row():
        history_df = gr.Dataframe(
            headers=["started", "job", "topic", "status", "duration", "run dir"],
            datatype=["str"] * 6, interactive=False, wrap=True, label="History",
        )
    event_log = gr.Textbox(label="Scheduler events", lines=12, interactive=False, autoscroll=True)

    timer = gr.Timer(5, active=True)
    plan_button.click(
        build_plan,
        inputs=[theme, count, plan_seed, cadence, interval_minutes, at_time, weekday],
        outputs=[topics_text, preview_df],
    )
    create_button.click(
        create_job,
        inputs=[job_name, topics_text, cadence, interval_minutes, at_time, weekday, job_collection,
                job_garment, job_aggressiveness, job_variants, job_generate, job_offline, job_enabled],
        outputs=[create_note, jobs_df],
    )
    start_button.click(scheduler_start, outputs=[sched_banner, event_log])
    stop_button.click(scheduler_stop, outputs=[sched_banner, event_log])
    refresh_button.click(scheduler_refresh, outputs=[sched_banner, jobs_df, history_df, event_log])
    timer.tick(scheduler_refresh, outputs=[sched_banner, jobs_df, history_df, event_log])
    live.change(lambda on: gr.Timer(5, active=bool(on)), inputs=live, outputs=timer)
    run_now_button.click(lambda i: job_action("run", i), inputs=job_id,
                         outputs=[action_note, jobs_df, history_df])
    pause_button.click(lambda i: job_action("pause", i), inputs=job_id,
                       outputs=[action_note, jobs_df, history_df])
    resume_button.click(lambda i: job_action("resume", i), inputs=job_id,
                        outputs=[action_note, jobs_df, history_df])
    remove_button.click(lambda i: job_action("remove", i), inputs=job_id,
                        outputs=[action_note, jobs_df, history_df])


# --------------------------------------------------------------------------
# ⑥ deploy
# --------------------------------------------------------------------------
def write_deploy(port: int, image: str, user: str, workdir: str, windows_workdir: str, target: str):
    target_dir = Path(target.strip() or "deploy")
    try:
        written = deploy_mod.materialise(
            target_dir,
            port=int(port),
            image=image.strip() or "archivist:latest",
            user=user.strip() or "ubuntu",
            workdir=workdir.strip() or "/opt/archivist",
            windows_workdir=windows_workdir.strip() or r"C:\archivist",
            gradio_version=getattr(gr, "__version__", "5.0.0"),
        )
    except Exception as exc:
        return f"❌ {type(exc).__name__}: {exc}", [], ""
    commands = deploy_mod.summary(int(port), target_dir)
    note = "\n".join(
        [
            f"✅ wrote {len(written)} files to `{target_dir.resolve()}`",
            "",
            "```bash",
            f"# docker\n{commands['docker']}",
            "",
            f"# ubuntu service\n{commands['systemd']}",
            "",
            f"# windows, start at logon\n{commands['windows']}",
            "```",
            f"then open {commands['url']}",
        ]
    )
    notes_file = target_dir / "NOTES.md"
    return note, written, notes_file.read_text(encoding="utf-8") if notes_file.is_file() else ""


def deploy_tab() -> None:
    gr.Markdown(
        "### ⑥ Deploy\n"
        "Write out deployment artefacts already filled in with your port and paths: a Dockerfile and "
        "compose file, a systemd unit for Ubuntu, a Windows scheduled-task definition, and a Hugging "
        "Face Space entry point."
    )
    with gr.Row():
        with gr.Column():
            port = gr.Number(value=7860, label="Port", precision=0)
            image = gr.Textbox(value="archivist:latest", label="Docker image tag")
            target = gr.Textbox(value="deploy", label="Output directory")
        with gr.Column():
            user = gr.Textbox(value="ubuntu", label="Linux service user")
            workdir = gr.Textbox(value="/opt/archivist", label="Linux install directory")
            windows_workdir = gr.Textbox(value=r"C:\archivist", label="Windows install directory")
    write_button = gr.Button("Write deployment files", variant="primary")
    deploy_note = gr.Markdown("", elem_classes="arc-status")
    deploy_files = gr.File(label="Generated files", file_count="multiple", interactive=False)
    with gr.Accordion("Notes", open=True):
        deploy_notes = gr.Markdown("", elem_classes="arc-note")
    with gr.Accordion("Before you expose this publicly", open=False):
        gr.Markdown(
            "- The app holds API keys and can spend credits. Put it behind auth "
            "(`--auth user:password`) or a reverse proxy — never leave `--share` running unattended.\n"
            "- The scheduler keeps firing while the process lives: check the cadence and the "
            "generation toggle before deploying a job that spends money hourly.\n"
            "- Mount `runs/` on a volume. It holds the collection style lock, and losing it means "
            "losing visual continuity across the collection.\n"
            "- Reference images are downloaded from third parties for internal art direction. "
            "Check licensing before publishing a reference board, and keep the Pexels attribution "
            "that the board records.",
            elem_classes="arc-note",
        )
    write_button.click(
        write_deploy,
        inputs=[port, image, user, workdir, windows_workdir, target],
        outputs=[deploy_note, deploy_files, deploy_notes],
    )


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------
def _theme() -> Any:
    # Fonts must be Font objects on Gradio 6 (bare strings break theme comparison),
    # while older versions accept either.
    stack = ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"]
    font_class = getattr(gr.themes, "Font", None)
    fonts: list[Any] = [font_class(name) for name in stack] if font_class else stack
    return gr.themes.Soft(primary_hue="slate", neutral_hue="stone", font=fonts)


def _gradio_major() -> int:
    try:
        return int(str(getattr(gr, "__version__", "5")).split(".")[0])
    except ValueError:
        return 5


def styling_kwargs() -> dict[str, Any]:
    """Gradio 6 moved ``theme``/``css`` from Blocks() to launch(); support both."""
    return {"theme": _theme(), "css": CSS}


def build_app() -> gr.Blocks:
    blocks_kwargs: dict[str, Any] = {"title": "Archivist — apparel design pipeline", "fill_height": True}
    if _gradio_major() < 6:
        blocks_kwargs.update(styling_kwargs())
    with gr.Blocks(**blocks_kwargs) as demo:
        gr.HTML(HEADER)
        with gr.Tabs():
            with gr.Tab("① Setup"):
                setup_tab()
            with gr.Tab("② Connection"):
                connection_tab()
            with gr.Tab("③ Studio"):
                studio_tab()
            with gr.Tab("④ Monitor"):
                monitor_tab()
            with gr.Tab("⑤ Auto-plan"):
                schedule_tab()
            with gr.Tab("⑥ Deploy"):
                deploy_tab()
        gr.Markdown(
            "References are ingredients, never targets — nothing mined is reproduced in the output. "
            "Check licensing before commercial use, and keep recognisable brands, logos and real "
            "people out of what you print.",
            elem_classes="arc-note",
        )
    return demo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the Archivist Gradio app")
    parser.add_argument("--host", default=os.environ.get("GRADIO_SERVER_NAME", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("GRADIO_SERVER_PORT", 7860)))
    parser.add_argument("--share", action="store_true", help="temporary public URL")
    parser.add_argument("--open", action="store_true", help="open a browser window")
    parser.add_argument("--auth", default="", help="user:password gate")
    parser.add_argument("--scheduler", action="store_true", help="start the scheduler on launch")
    args = parser.parse_args(argv)

    if args.scheduler:
        STATE.scheduler.start()

    auth = tuple(args.auth.split(":", 1)) if ":" in args.auth else None
    demo = build_app()
    launch_kwargs: dict[str, Any] = {
        "server_name": args.host,
        "server_port": args.port,
        "share": args.share,
        "inbrowser": args.open,
        "auth": auth,
    }
    if _gradio_major() >= 6:
        launch_kwargs.update(styling_kwargs())
    demo.queue(default_concurrency_limit=4).launch(**launch_kwargs)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
