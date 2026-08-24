"""The Gradio control room.

Six tabs, one job each:

  ① SETUP       keys, defaults, and a .env written for you
  ② CONNECTION  one button that proves every dependency before you spend credits
  ③ DISCOVERY   the bot finds its own topics, and can design them unattended
  ④ STUDIO      run the pipeline with a live log, galleries and print packages
  ⑤ MONITOR     every past run, its report, its assets, its log
  ⑥ SCHEDULE    autopilot on a cadence, or a planned collection of topics
  ⑦ HOUSE V10.1   the house system: owned blueprint, one paid image, measured proof
  ⑧ DEPLOY      Docker / systemd / Windows Task / HF Space, written out filled in

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
OPENAI_MODELS = ["gpt-5.1", "gpt-5.1-mini", "gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini"]

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
<p>public signal → market truth → evidence-bound route → owned blueprint → apparel graphics</p>
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
        self.discovery_log: deque[str] = deque(maxlen=500)
        self.last_discovery: Any = None
        self.staged_topic: str = ""
        self.house_log: deque[str] = deque(maxlen=500)
        self.last_house: Any = None

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
        f"**image** `{settings.hf_image_model if settings.image_provider == 'hf' else settings.bfl_model}`  ·  "
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
    hf_key: str,
    bfl_key: str,
    pexels_key: str,
    openai_key: str,
    reddit_id: str,
    reddit_secret: str,
    x_token: str,
    meta_token: str,
    meta_user: str,
    image_provider: str,
    hf_image_model: str,
    bfl_model: str,
    openai_model: str,
    collection: str,
    garment: str,
    aspect: str,
    width_in: float,
    dpi: int,
    runs_dir: str,
    trends_geo: str,
    offline: bool,
) -> tuple[str, str]:
    values = {
        "HF_TOKEN": hf_key.strip(),
        "ARCHIVIST_IMAGE_PROVIDER": (image_provider or "hf").strip(),
        "HF_IMAGE_MODEL": hf_image_model.strip() or "Qwen/Qwen-Image-Edit",
        "BFL_API_KEY": bfl_key.strip(),
        "PEXELS_API_KEY": pexels_key.strip(),
        "OPENAI_API_KEY": openai_key.strip(),
        "REDDIT_CLIENT_ID": reddit_id.strip(),
        "REDDIT_CLIENT_SECRET": reddit_secret.strip(),
        "X_BEARER_TOKEN": x_token.strip(),
        "META_ACCESS_TOKEN": meta_token.strip(),
        "META_IG_USER_ID": meta_user.strip(),
        "ARCHIVIST_TRENDS_GEO": trends_geo.strip() or "US",
        "BFL_MODEL": bfl_model,
        "OPENAI_MODEL": openai_model,
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
                hf_key = gr.Textbox(
                    label="HF_TOKEN", type="password", placeholder="required to generate artwork",
                    info="huggingface.co → Settings → Access Tokens. The default provider.",
                )
                bfl_key = gr.Textbox(
                    label="BFL_API_KEY", type="password", placeholder="only for the bfl provider",
                    info="api.bfl.ai — kept as a compatibility option, not the default",
                )
                pexels_key = gr.Textbox(
                    label="PEXELS_API_KEY", type="password", placeholder="optional",
                    info="adds contemporary photography and cinematic light to the reference pool",
                )
                openai_key = gr.Textbox(
                    label="OPENAI_API_KEY", type="password", placeholder="optional",
                    info="GPT-5.1 judges discovered topics and refines the art direction",
                )
            with gr.Accordion("Discovery credentials (all optional)", open=False):
                gr.Markdown(
                    "Google Trends and DuckDuckGo need no key. These only widen the social "
                    "signal — with none of them, Reddit answers anonymously and decides alone.",
                    elem_classes="arc-note",
                )
                with gr.Row():
                    reddit_id = gr.Textbox(label="REDDIT_CLIENT_ID", type="password",
                                           placeholder="if anonymous Reddit is blocked from your IP")
                    reddit_secret = gr.Textbox(label="REDDIT_CLIENT_SECRET", type="password")
                x_token = gr.Textbox(label="X_BEARER_TOKEN", type="password",
                                     placeholder="X API v2 — paid tier")
                with gr.Row():
                    meta_token = gr.Textbox(label="META_ACCESS_TOKEN", type="password",
                                            placeholder="Instagram Graph — business account")
                    meta_user = gr.Textbox(label="META_IG_USER_ID", placeholder="Instagram business user id")
                trends_geo = gr.Textbox(value=STATE.settings.trends_geo, label="Google Trends geo",
                                        info="US, GB, ID, DE… blank searches worldwide")
            with gr.Row():
                image_provider = gr.Radio(
                    ["hf", "bfl"], value=STATE.settings.image_provider, label="Image provider",
                    info="hugging face (Qwen) by default; bfl stays available for existing credit",
                )
                hf_image_model = gr.Textbox(
                    value=STATE.settings.hf_image_model, label="HF image model",
                    info="context edits; text-to-image falls back automatically",
                )
            with gr.Row():
                bfl_model = gr.Dropdown(BFL_MODELS, value=STATE.settings.bfl_model, label="BFL model")
                openai_model = gr.Dropdown(
                    OPENAI_MODELS, value=STATE.settings.openai_model, label="Creative assist model"
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
                    "- **Hugging Face** — https://huggingface.co/settings/tokens. The default provider.\n"
                    "- **BFL** — https://api.bfl.ai, dashboard → API keys. Optional compatibility path.\n"
                    "- **Pexels** — https://www.pexels.com/api/, free key, attribution is carried "
                    "through onto the reference board automatically.\n"
                    "- **OpenAI** — https://platform.openai.com/api-keys. Optional; GPT-5.1 sharpens "
                    "the wording, and every stage it touches has a deterministic fallback.\n\n"
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
        inputs=[hf_key, bfl_key, pexels_key, openai_key, reddit_id, reddit_secret, x_token, meta_token,
                meta_user, image_provider, hf_image_model, bfl_model, openai_model, collection,
                garment, aspect, width_in, dpi,
                runs_dir, trends_geo, offline],
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
        "Probe every dependency before a run: Python and Pillow, disk, DuckDuckGo, Pexels, the image "
        "key, and the optional creative assist. A red row is a blocker; a yellow row degrades one "
        "stage and the pipeline still completes."
    )
    with gr.Row():
        include_generation = gr.Checkbox(value=True, label="Include image provider probe")
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
            "- **provider 401/403** — key rejected. Check for a trailing space when pasting.\n"
            "- **storage low disk** — a run writes 20–60 reference images plus print files; keep a "
            "few hundred MB free.\n"
            "- **openai fail** — optional. A 404 usually means the key has no access to the chosen "
            "model; pick another in Setup. Every stage it touches has a deterministic fallback.",
            elem_classes="arc-note",
        )
    test_button.click(run_connection_checks, inputs=include_generation, outputs=[summary, table])


# --------------------------------------------------------------------------
# ③ discovery / autopilot
# --------------------------------------------------------------------------
DISCOVERY_HEADERS = ["#", "topic", "score", "growth 3m", "social", "eng/post", "competition",
                     "durability", "sources", "family"]


def _discovery_engine(settings: Settings, use_llm: bool):
    from .discovery import DiscoveryConfig, DiscoveryEngine
    from .discovery.scoring import Thresholds
    from .llm import LLM

    llm = LLM(
        settings.openai_api_key, model=settings.openai_model,
        base_url=settings.openai_base_url, reasoning_effort=settings.openai_reasoning_effort,
        enabled=use_llm and settings.can_use_llm,
    )
    config = DiscoveryConfig(
        geo=settings.trends_geo,
        timeframe=settings.trends_timeframe,
        max_candidates=settings.discovery_candidates,
        keep=settings.discovery_keep,
        thresholds=Thresholds(
            min_growth=settings.discovery_min_growth,
            max_competition=settings.discovery_max_competition,
            min_social=settings.discovery_min_social,
        ),
        use_llm=use_llm,
    )
    return DiscoveryEngine(settings, config=config, llm=llm, log=STATE.discovery_log.append)


def _discovery_detail(report) -> str:
    if not report or not report.opportunities:
        return "_nothing cleared the filters_"
    lines = ["### Why these topics", ""]
    for opportunity in report.opportunities:
        lines += [
            f"**{opportunity.topic}** — score {opportunity.overall} "
            f"({opportunity.durability or 'durability unrated'})",
            "",
            *[f"- `{signal.source}` {signal.metric}: {signal.detail}"
              for signal in opportunity.signals if signal.ok],
        ]
        if opportunity.angle:
            lines.append(f"- **angle:** {opportunity.angle}")
        if opportunity.correlated_with:
            lines.append(f"- **moves with:** {', '.join(opportunity.correlated_with)}")
        if opportunity.risk:
            lines.append(f"- **risk:** {opportunity.risk}")
        lines.append("")
    if report.rejected:
        lines += ["### Filtered out", ""]
        lines += [f"- {item.topic} — {item.rejected_reason}" for item in report.rejected[:15]]
    lines += ["", f"_sources: {report.source_status}_"]
    return "\n".join(lines)


def discovery_run(count: int, geo: str, timeframe: str, min_growth: float, max_competition: float,
                  min_social: float, candidates: int, offline: bool, use_llm: bool):
    """Streaming: harvest → measure → screen → score → correlate → judge."""
    STATE.discovery_log.clear()
    settings = STATE.refresh_settings(
        offline=bool(offline), trends_geo=geo.strip() or "US",
        trends_timeframe=timeframe.strip() or "today 3-m",
        discovery_min_growth=float(min_growth), discovery_max_competition=float(max_competition),
        discovery_min_social=float(min_social), discovery_candidates=int(candidates),
        discovery_keep=int(count),
    )
    engine = _discovery_engine(settings, use_llm)

    events: queue.Queue = queue.Queue()
    box: dict[str, Any] = {}
    state = {"fraction": 0.0, "message": "starting"}

    def worker() -> None:
        try:
            box["report"] = engine.discover(
                count=int(count),
                progress=lambda fraction, message: (
                    state.__setitem__("fraction", fraction), state.__setitem__("message", message)
                ),
                cancel=STATE.cancel.is_set,
            )
        except Exception as exc:
            box["error"] = exc
        finally:
            events.put(None)

    STATE.cancel.clear()
    thread = threading.Thread(target=worker, name="archivist-discovery", daemon=True)
    thread.start()

    while thread.is_alive():
        try:
            events.get(timeout=0.4)
            break
        except queue.Empty:
            pass
        yield (
            f"`{_bar(state['fraction'])}` **{state['fraction'] * 100:4.0f}%** — {state['message']}",
            "\n".join(list(STATE.discovery_log)[-300:]),
            gr.update(), gr.update(), gr.update(),
        )
    thread.join(timeout=1.0)

    if "error" in box:
        yield (f"❌ discovery failed — {type(box['error']).__name__}: {box['error']}",
               "\n".join(list(STATE.discovery_log)[-300:]), gr.update(), gr.update(), gr.update())
        return

    report = box.get("report")
    STATE.last_discovery = report
    engine.write_report(report)
    topics = [opportunity.topic for opportunity in report.opportunities]
    status = (
        f"✅ {len(topics)} opportunities from {report.measured} measured "
        f"({len(report.rejected)} filtered out) in {report.duration_s:.0f}s"
        if topics else
        "⚠️ nothing cleared the filters — loosen the thresholds below, or widen the geo"
    )
    yield (
        status,
        "\n".join(list(STATE.discovery_log)[-300:]),
        report.table_rows(),
        _discovery_detail(report),
        gr.update(choices=topics, value=topics[0] if topics else None),
    )


def autopilot_run(designs: int, garment: str, aggressiveness: int, generate: bool,
                  collection: str, offline: bool, use_llm: bool):
    """The whole bot: discover, then design, with no topic typed anywhere."""
    from .pipeline import autopilot as run_autopilot

    STATE.discovery_log.clear()
    settings = STATE.refresh_settings(
        offline=bool(offline), collection=collection.strip() or "default", garment=garment,
    )
    options = PipelineOptions(
        garment=garment, aggressiveness=int(aggressiveness), generate=bool(generate),
        use_llm=bool(use_llm),
    )

    events: queue.Queue = queue.Queue()
    box: dict[str, Any] = {}
    state = {"fraction": 0.0, "message": "starting"}
    STATE.cancel.clear()

    def worker() -> None:
        try:
            box["result"] = run_autopilot(
                settings, options, designs=int(designs),
                progress=lambda fraction, message: (
                    state.__setitem__("fraction", fraction), state.__setitem__("message", message)
                ),
                log=STATE.discovery_log.append,
                cancel=STATE.cancel.is_set,
            )
        except Exception as exc:
            box["error"] = exc
        finally:
            events.put(None)

    thread = threading.Thread(target=worker, name="archivist-autopilot", daemon=True)
    thread.start()
    while thread.is_alive():
        try:
            events.get(timeout=0.5)
            break
        except queue.Empty:
            pass
        yield (
            f"`{_bar(state['fraction'])}` **{state['fraction'] * 100:4.0f}%** — {state['message']}",
            "\n".join(list(STATE.discovery_log)[-300:]),
            gr.update(), gr.update(), gr.update(),
        )
    thread.join(timeout=1.0)

    if "error" in box:
        yield (f"❌ autopilot failed — {type(box['error']).__name__}: {box['error']}",
               "\n".join(list(STATE.discovery_log)[-300:]), gr.update(), gr.update(), gr.update())
        return

    result = box["result"]
    STATE.last_discovery = result.report
    if result.runs:
        STATE.last_result = result.runs[-1]
    designed = ", ".join(result.topics) or "nothing"
    status = f"✅ autopilot designed: **{designed}**" if result.runs else (
        "⚠️ " + (result.warnings[0] if result.warnings else "nothing was designed")
    )
    gallery = storage.gallery_paths(result.runs[-1], kind="all") if result.runs else []
    yield (
        status,
        "\n".join(list(STATE.discovery_log)[-300:]),
        result.report.table_rows() if result.report else [],
        _discovery_detail(result.report),
        gallery,
    )


def discovery_tab() -> None:
    gr.Markdown(
        "### ③ Discovery & autopilot\n"
        "Nobody types a topic. The bot reads Google Trends for three-month growth, Reddit / X / Meta "
        "for whether anyone cares, and DuckDuckGo for how crowded the apparel market already is — "
        "then screens out anything it must not print, scores what is left, and works out which "
        "survivors are the same wave."
    )
    with gr.Row():
        with gr.Column(scale=2):
            with gr.Row():
                count = gr.Slider(2, 12, value=STATE.settings.discovery_keep, step=1, label="Opportunities to keep")
                candidates = gr.Slider(6, 40, value=STATE.settings.discovery_candidates, step=1,
                                       label="Candidates to measure")
            with gr.Row():
                geo = gr.Textbox(value=STATE.settings.trends_geo, label="Google Trends geo",
                                 info="US, GB, ID, DE… blank = worldwide")
                timeframe = gr.Dropdown(
                    ["today 3-m", "today 12-m", "today 1-m", "now 7-d"],
                    value=STATE.settings.trends_timeframe, label="Window",
                )
            gr.Markdown("**Filters** — a topic must clear all three", elem_classes="arc-note")
            min_growth = gr.Slider(0, 200, value=STATE.settings.discovery_min_growth, step=5,
                                   label="Minimum growth over the window (%)")
            max_competition = gr.Slider(10, 100, value=STATE.settings.discovery_max_competition, step=5,
                                        label="Maximum competition (0 = empty market)")
            min_social = gr.Slider(0, 60, value=STATE.settings.discovery_min_social, step=2,
                                   label="Minimum social heat")
            with gr.Row():
                offline = gr.Checkbox(value=STATE.settings.offline, label="Offline mode")
                use_llm = gr.Checkbox(value=True, label="Use GPT for topic judgement")
            with gr.Row():
                discover_button = gr.Button("Find opportunities", variant="primary", scale=2)
                cancel_button = gr.Button("Cancel", variant="stop", scale=1)
        with gr.Column(scale=1):
            gr.Markdown("**Autopilot** — discover *and* design, hands off", elem_classes="arc-note")
            designs = gr.Slider(1, 5, value=STATE.settings.autopilot_designs, step=1, label="Designs per cycle")
            auto_collection = gr.Textbox(value=STATE.settings.collection, label="Collection")
            auto_garment = gr.Dropdown(GARMENTS, value=STATE.settings.garment, label="Garment")
            auto_aggr = gr.Slider(0, 10, value=5, step=1, label="Aggressiveness")
            auto_generate = gr.Checkbox(value=True, label="Generate artwork (spends provider credits)")
            autopilot_button = gr.Button("Run autopilot now", variant="primary")
            gr.Markdown(
                "Autopilot writes the discovery evidence into every run manifest, so each design can "
                "answer *why this subject* long after the trend has moved on.",
                elem_classes="arc-note",
            )

    status = gr.Markdown("_idle_", elem_classes="arc-status")
    table = gr.Dataframe(
        headers=DISCOVERY_HEADERS,
        datatype=["number", "str", "number", "str", "number", "number", "number", "str", "str", "str"],
        interactive=False, wrap=True, label="Opportunities",
    )
    with gr.Row():
        chosen = gr.Dropdown([], label="Send a topic to the Studio", scale=3)
        send_button = gr.Button("Use this topic", scale=1)
    send_note = gr.Markdown("", elem_classes="arc-note")
    with gr.Tabs():
        with gr.Tab("Evidence"):
            detail = gr.Markdown("_run discovery to see the evidence behind each topic_")
        with gr.Tab("Log"):
            log = gr.Textbox(label="Discovery log", lines=18, interactive=False, autoscroll=True)
        with gr.Tab("Autopilot output"):
            auto_gallery = gr.Gallery(label="What autopilot produced", columns=4, height=420,
                                      object_fit="contain")

    discover_event = discover_button.click(
        discovery_run,
        inputs=[count, geo, timeframe, min_growth, max_competition, min_social, candidates,
                offline, use_llm],
        outputs=[status, log, table, detail, chosen],
    )
    autopilot_event = autopilot_button.click(
        autopilot_run,
        inputs=[designs, auto_garment, auto_aggr, auto_generate, auto_collection, offline, use_llm],
        outputs=[status, log, table, detail, auto_gallery],
    )
    cancel_button.click(
        lambda: (STATE.cancel.set(), "⏹ cancelling after the current step…")[1],
        outputs=status, cancels=[discover_event, autopilot_event],
    )
    send_button.click(_stage_topic, inputs=chosen, outputs=send_note)


def _stage_topic(topic: str) -> str:
    """Hand a discovered topic to the Studio tab."""
    STATE.staged_topic = (topic or "").strip()
    if not STATE.staged_topic:
        return "pick a topic first"
    return f"📌 `{STATE.staged_topic}` staged — open ④ Studio and press **Load discovered topic**"


# --------------------------------------------------------------------------
# ④ studio
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
        return f"{STATE.settings.image_credential} is not set — nothing to regenerate with", [], []
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


def _load_staged_topic() -> tuple[str, str]:
    """Pull in whatever the Discovery tab staged, or the best topic on file."""
    if STATE.staged_topic:
        return STATE.staged_topic, f"loaded from discovery: **{STATE.staged_topic}**"
    from .discovery import latest_report

    report = latest_report(STATE.settings.runs_dir)
    opportunities = (report or {}).get("opportunities", [])
    if not opportunities:
        return gr.update(), "no discovery run yet — open ③ Discovery and press **Find opportunities**"
    best = opportunities[0]
    return best["topic"], (
        f"loaded the best topic on file: **{best['topic']}** "
        f"(score {best.get('overall', '—')}, growth {best.get('growth_3m', 0):+.0f}%)"
    )


def studio_tab() -> None:
    gr.Markdown(
        "### ③ Studio\n"
        "One topic in, a full run out: niche ladder → queries → mined references → scored board → "
        "Visual DNA → art direction → three ranked directions → prompts → artwork → print package."
    )
    with gr.Row():
        with gr.Column(scale=2):
            topic = gr.Textbox(
                label="Topic / trend / cultural phenomenon",
                placeholder="leave it to the bot — or type one here to override discovery",
                autofocus=True,
            )
            with gr.Row():
                load_discovered = gr.Button("Load discovered topic", size="sm")
                discovered_note = gr.Markdown("", elem_classes="arc-note")
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
    load_discovered.click(_load_staged_topic, outputs=[topic, discovered_note])
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
    name: str, topics_text: str, mode: str, designs: int, cadence: str, interval_minutes: int,
    at_time: str, weekday: str, collection: str, garment: str, aggressiveness: int,
    variants: list[str], generate: bool, offline: bool, enabled: bool,
) -> tuple[str, list[list[Any]]]:
    autonomous = mode.startswith("autopilot")
    topics = [line.strip() for line in topics_text.splitlines() if line.strip()]
    if not topics and not autonomous:
        return "⚠️ no topics — generate a plan, type one per line, or switch to autopilot", STATE.scheduler.job_rows()
    job = STATE.scheduler.create_job(
        name or ("autopilot" if autonomous else f"{topics[0][:30]} plan"),
        topics,
        mode="autopilot" if autonomous else "topics",
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
            "designs": int(designs),
        },
    )
    scope = f"autopilot, {int(designs)} design(s) per firing" if job.autonomous else f"{len(job.topics)} topics"
    return (
        f"✅ job `{job.id}` created — {job.describe()}, {scope}, next {job.next_run or '—'}",
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
        "### ⑥ Schedule\n"
        "Two ways to run unattended. **Autopilot** rediscovers what is trending at every firing and "
        "designs the winners — nothing is typed, ever. **Topics** works through a plan you generated "
        "from one theme. Either way, every run in a collection inherits the same style lock, so a "
        "drop reads as one body of work."
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
            job_mode = gr.Radio(
                ["autopilot — discover topics at run time", "topics — work through the list"],
                value="autopilot — discover topics at run time", label="What should each firing do?",
            )
            job_designs = gr.Slider(1, 5, value=STATE.settings.autopilot_designs, step=1,
                                    label="Designs per firing (autopilot)")
            job_name = gr.Textbox(label="Job name", placeholder="Nightly autopilot")
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
        headers=["id", "name", "state", "mode", "cadence", "next run", "progress",
                 "current topic", "last status"],
        datatype=["str"] * 9, interactive=False, wrap=True, label="Jobs",
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
        inputs=[job_name, topics_text, job_mode, job_designs, cadence, interval_minutes, at_time,
                weekday, job_collection, job_garment, job_aggressiveness, job_variants,
                job_generate, job_offline, job_enabled],
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
# ⑦ house system (V10.1)
# --------------------------------------------------------------------------
def _house_files(result) -> list[str]:
    files: list[str] = []
    if result.delivery:
        for path in sorted(Path(result.delivery.final_dir).iterdir()):
            if path.is_file():
                files.append(str(path))
    elif result.rejected and Path(result.rejected).is_file():
        files.append(result.rejected)
    return files


def _house_gallery(result) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if result.delivery:
        final = Path(result.delivery.final_dir)
        for name, caption in (
            ("FINAL_mockup.png", "garment proof"), ("FINAL_artwork.png", "composed artwork"),
            ("FINAL_print.png", "print file"), ("FINAL_blueprint.png", "owned blueprint"),
        ):
            if (final / name).is_file():
                pairs.append((str(final / name), caption))
        return pairs
    for candidate in (result.delivery.candidates if result.delivery else []):
        for key in ("artwork_path", "normalised_artwork_path", "raw_artwork_path"):
            path = candidate.get(key)
            if path and Path(path).is_file():
                pairs.append((path, f"{candidate['global_index']}: {key.replace('_', ' ')}"))
    return pairs


def _route_markdown(result) -> str:
    route = result.route
    if not route:
        return "_no route_"
    lines = [
        f"### {route['product_title']}",
        f"_{route['metaphor']}_", "",
        f"- **market signal:** {route['market_signal']}",
        f"- **evidence:** {route['real_subject']} — {route['source_property']}",
        f"- **one mutation:** {route['mutation']}",
        f"- **silhouette archetype:** {(route.get('silhouette') or {}).get('label', '—')} "
        f"({(route.get('silhouette') or {}).get('requirement', '')})",
        f"- **hero:** {route['hero_motif']}",
        f"- **interruption:** {route['signature_interruption']}",
        f"- **placement:** {route['placement_logic']}",
        f"- **statement on the garment:** **{route['statement']}** ({route['statement_lockup']})",
        f"- **palette:** {', '.join(route['palette'])}",
    ]
    if result.delivery:
        measured = result.delivery.selected.get("measured", {})
        review = result.delivery.selected.get("visual_review", {})
        lines += [
            "", "**Proof**",
            f"- hard checks: {measured.get('hard_checks')}",
            f"- heuristic total {measured.get('heuristic_total')} · ink {measured.get('ink_coverage')}% "
            f"(expected {measured.get('expected_ink_range')})",
            f"- vision total {review.get('total', '—')} · {review.get('reason', '')}",
            f"- paid generations used: {result.delivery.paid_calls}",
        ]
    elif result.rejected:
        lines += ["", f"**Rejected** — diagnosis package: `{result.rejected}`"]
    for warning in result.warnings[:6]:
        lines.append(f"- warning: {warning}")
    return "\n".join(lines)


def house_run(topic: str, collection: str, garment: str, aggressiveness: int, budget: int,
              allow_edit: bool, allow_concept_retry: bool, require_critic: bool,
              print_statement: bool, statement: str, anchor: str, reuse_raw: str,
              generate: bool, offline: bool):
    """The whole house system, streamed."""
    from .house import HouseBlocked, RenderOptions, run_session

    STATE.house_log.clear()
    settings = STATE.refresh_settings(
        offline=bool(offline), collection=collection.strip() or "default", garment=garment,
    )
    if statement.strip():
        settings.house_statement_override = statement.strip()
    settings.house_anchor = anchor or "auto"

    options = PipelineOptions(garment=garment, aggressiveness=int(aggressiveness))
    render_options = RenderOptions(
        budget=int(budget), allow_controlled_edit=bool(allow_edit),
        allow_concept_retry=bool(allow_concept_retry), require_critic=bool(require_critic),
        print_statement=bool(print_statement), reuse_raw=reuse_raw.strip(), seed=settings.seed,
    )

    events: queue.Queue = queue.Queue()
    box: dict[str, Any] = {}
    state = {"fraction": 0.0, "message": "starting"}
    STATE.cancel.clear()

    def worker() -> None:
        try:
            box["result"] = run_session(
                settings, options, topic=topic.strip(), render_options=render_options,
                generate=bool(generate),
                progress=lambda fraction, message: (
                    state.__setitem__("fraction", fraction), state.__setitem__("message", message)
                ),
                log=STATE.house_log.append, cancel=STATE.cancel.is_set,
            )
        except HouseBlocked as blocked:
            box["blocked"] = str(blocked)
        except Exception as exc:
            box["error"] = exc
        finally:
            events.put(None)

    thread = threading.Thread(target=worker, name="archivist-house", daemon=True)
    thread.start()
    while thread.is_alive():
        try:
            events.get(timeout=0.4)
            break
        except queue.Empty:
            pass
        yield (
            f"`{_bar(state['fraction'])}` **{state['fraction'] * 100:4.0f}%** — {state['message']}",
            "\n".join(list(STATE.house_log)[-300:]), gr.update(), gr.update(), gr.update(),
        )
    thread.join(timeout=1.0)

    log_text = "\n".join(list(STATE.house_log)[-300:])
    if "blocked" in box:
        yield (f"⛔ blocked before spending anything — {box['blocked']}", log_text,
               gr.update(), gr.update(), gr.update())
        return
    if "error" in box:
        yield (f"❌ {type(box['error']).__name__}: {box['error']}", log_text,
               gr.update(), gr.update(), gr.update())
        return

    result = box["result"]
    STATE.last_house = result
    if result.approved:
        status = (
            f"✅ approved — **{result.route['product_title']}**, "
            f"{result.delivery.paid_calls} paid generation(s) → `{result.delivery.final_dir}`"
        )
    elif result.rejected:
        status = f"⛔ rejected by the proof — no false final was packaged. Diagnosis: `{result.rejected}`"
    else:
        status = f"📋 prepared without generating — **{result.route['product_title']}**"
    yield status, log_text, _house_gallery(result), _route_markdown(result), _house_files(result)


def house_tab() -> None:
    gr.Markdown(
        "### ⑦ House system (V10.1)\n"
        "One real material fact, transformed once, placed off-centre, finished with one printed "
        "sentence. Only an owned blueprint conditions the image model; the statement is typeset by "
        "code; one paid generation is the default, and nothing ships unless the measured proof passes."
    )
    with gr.Row():
        with gr.Column(scale=2):
            topic = gr.Textbox(label="Market signal (blank = volume-first discovery decides)",
                               placeholder="harbor, radar, lighthouse…")
            with gr.Row():
                collection = gr.Textbox(value=STATE.settings.collection, label="Collection")
                garment = gr.Dropdown(GARMENTS, value=STATE.settings.garment, label="Garment")
                anchor = gr.Dropdown(["auto", "upper-left", "upper-right", "low-left", "low-right"],
                                     value=STATE.settings.house_anchor, label="Asymmetry anchor")
            aggressiveness = gr.Slider(0, 10, value=3, step=1, label="Aggressiveness")
            statement = gr.Textbox(label="Statement override (optional, 4-8 words)",
                                   placeholder="leave blank to let the route write it")
            with gr.Accordion("Budget and proof", open=True):
                with gr.Row():
                    budget = gr.Radio([1, 2], value=STATE.settings.house_paid_budget,
                                      label="Paid generations allowed")
                    generate = gr.Checkbox(value=True, label="Generate (spends BFL credits)")
                with gr.Row():
                    allow_edit = gr.Checkbox(value=STATE.settings.house_allow_controlled_edit,
                                             label="Allow one controlled edit")
                    allow_concept_retry = gr.Checkbox(value=STATE.settings.house_allow_concept_retry,
                                                      label="Allow a rebuilt route on a concept failure")
                with gr.Row():
                    require_critic = gr.Checkbox(value=STATE.settings.house_require_critic,
                                                 label="Require the vision critic")
                    print_statement = gr.Checkbox(value=STATE.settings.house_print_statement,
                                                  label="Print the statement")
                reuse_raw = gr.Textbox(label="Reuse a raw frame (zero-cost recovery)",
                                       placeholder="path to B_paid_01_raw.png from an interrupted run")
                offline = gr.Checkbox(value=STATE.settings.offline,
                                      label="Offline mode (synthesised frame, no credits)")
            with gr.Row():
                run_button = gr.Button("Run the house system", variant="primary", scale=3)
                cancel_button = gr.Button("Cancel", variant="stop", scale=1)
        with gr.Column(scale=3):
            status = gr.Markdown("_idle_", elem_classes="arc-status")
            log = gr.Textbox(label="Live log", lines=18, interactive=False, autoscroll=True)

    with gr.Tabs():
        with gr.Tab("Proof"):
            gallery = gr.Gallery(label="Mockup · artwork · print file · blueprint", columns=4,
                                 height=460, object_fit="contain")
        with gr.Tab("Creative route"):
            route_md = gr.Markdown("_run the house system to see the route and its proof_")
        with gr.Tab("Delivery"):
            files = gr.File(label="Approved delivery (or the rejection diagnosis)",
                            file_count="multiple", interactive=False)

    event = run_button.click(
        house_run,
        inputs=[topic, collection, garment, aggressiveness, budget, allow_edit, allow_concept_retry,
                require_critic, print_statement, statement, anchor, reuse_raw, generate, offline],
        outputs=[status, log, gallery, route_md, files],
    )
    cancel_button.click(
        lambda: (STATE.cancel.set(), "⏹ cancelling after the current step…")[1],
        outputs=status, cancels=[event],
    )


# --------------------------------------------------------------------------
# ⑧ deploy
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
        "### ⑧ Deploy\n"
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
            with gr.Tab("③ Discovery"):
                discovery_tab()
            with gr.Tab("④ Studio"):
                studio_tab()
            with gr.Tab("⑤ Monitor"):
                monitor_tab()
            with gr.Tab("⑥ Schedule"):
                schedule_tab()
            with gr.Tab("⑦ House V10.1"):
                house_tab()
            with gr.Tab("⑧ Deploy"):
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
