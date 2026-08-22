"""The orchestrator — the single entry point every surface calls.

The notebook, the CLI, the Gradio app, the .bat launcher and the scheduler all
run *this*; none of them re-implements a stage. Progress, logging and
cancellation are injected so the same function can drive a progress bar or a
log file without knowing which.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import board, brief, direction as direction_mod, gate, mining, prompts, queries as queries_mod
from .apparel import prepare
from .bfl import BFLClient, BFLError
from .config import Settings
from .dna import build_dna
from .llm import LLM
from .models import Concept, Reference, Role, RunResult, dump_json
from .roles import assign_roles
from .scoring import select_references
from .sources import build_sources
from .trends import derive_ladder, keywords, slugify
from .variations import build_concepts, recommend

Progress = Callable[[float, str], None]
Log = Callable[[str], None]
Cancel = Callable[[], bool]


class Cancelled(RuntimeError):
    pass


@dataclass
class PipelineOptions:
    audience: str = ""
    garment: str = "dark"
    aggressiveness: int = 5
    variants: list[str] = field(default_factory=lambda: ["A", "B", "C"])
    generate: bool = True
    generate_keys: list[str] = field(default_factory=list)  # empty -> recommended only
    include_text: bool = True
    build_mockup: bool = True
    use_llm: bool = True
    context_roles: list[str] = field(
        default_factory=lambda: [Role.HERO.value, Role.TEXTURE.value, Role.COMPOSITION.value, Role.TYPOGRAPHY.value]
    )

    def normalised_variants(self) -> list[str]:
        keys = [k.strip().upper()[:1] for k in self.variants if k.strip()]
        return [k for k in ("A", "B", "C") if k in keys] or ["A", "B", "C"]


# Stage weights so the progress bar advances at a believable pace.
STAGE_WEIGHTS = {
    "trend": 0.03,
    "queries": 0.05,
    "mining": 0.42,
    "select": 0.06,
    "dna": 0.06,
    "concepts": 0.08,
    "generate": 0.24,
    "output": 0.06,
}


class _Reporter:
    def __init__(self, progress: Progress | None, log: Log | None, cancel: Cancel | None, log_path: Path):
        self.progress = progress or (lambda fraction, message: None)
        self._log = log or (lambda message: None)
        self.cancel = cancel or (lambda: False)
        self.log_path = log_path
        self.base = 0.0
        self.started = time.time()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = log_path.open("a", encoding="utf-8")

    def say(self, message: str, fraction: float | None = None) -> None:
        elapsed = time.time() - self.started
        line = f"[{elapsed:7.1f}s] {message}"
        self.handle.write(line + "\n")
        self.handle.flush()
        self._log(line)
        if fraction is not None:
            self.progress(min(1.0, max(0.0, fraction)), message)

    def within(self, name: str) -> Progress:
        """A progress callback scoped to one stage's slice of the bar."""
        order = list(STAGE_WEIGHTS)
        start = sum(STAGE_WEIGHTS[k] for k in order[: order.index(name)])
        weight = STAGE_WEIGHTS[name]

        def inner(fraction: float, message: str) -> None:
            self.say(message, start + weight * max(0.0, min(1.0, fraction)))

        return inner

    def check_cancel(self) -> None:
        if self.cancel():
            raise Cancelled("run cancelled")

    def close(self) -> None:
        try:
            self.handle.close()
        except Exception:
            pass


def make_run_dir(settings: Settings, topic: str) -> tuple[Path, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = f"{stamp}-{slugify(topic, 40)}"
    run_dir = Path(settings.runs_dir) / settings.collection / slug
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, slug


def run(
    topic: str,
    settings: Settings | None = None,
    options: PipelineOptions | None = None,
    *,
    progress: Progress | None = None,
    log: Log | None = None,
    cancel: Cancel | None = None,
) -> RunResult:
    """Run the whole pipeline for one topic and return the persisted result."""
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("topic is required")

    settings = settings or Settings.from_env()
    options = options or PipelineOptions()
    settings.garment = options.garment or settings.garment

    run_dir, slug = make_run_dir(settings, topic)
    reporter = _Reporter(progress, log, cancel, run_dir / "run.log")
    result = RunResult(
        topic=topic,
        slug=slug,
        run_dir=str(run_dir),
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        collection=settings.collection,
        settings=settings.redacted(),
    )

    try:
        llm = LLM(
            settings.anthropic_api_key,
            model=settings.anthropic_model,
            enabled=options.use_llm and settings.can_use_llm,
        )

        # 1 — trend -> micro-niche ---------------------------------------
        reporter.say(f"topic: {topic}", 0.0)
        ladder = derive_ladder(
            topic, audience=options.audience, aggressiveness=options.aggressiveness,
            seed=settings.seed, llm=llm,
        )
        result.ladder = ladder
        reporter.say(f"micro-niche: {ladder.micro_niche}", STAGE_WEIGHTS["trend"])
        reporter.check_cancel()

        # 2 — queries -----------------------------------------------------
        search_queries = queries_mod.generate_queries(
            topic, ladder, count=settings.max_queries, seed=settings.seed, llm=llm
        )
        result.queries = search_queries
        dump_json([q.to_dict() for q in search_queries], run_dir / "queries.json")
        reporter.say(
            f"{len(search_queries)} queries across {len(queries_mod.cluster_summary(search_queries))} clusters",
            STAGE_WEIGHTS["trend"] + STAGE_WEIGHTS["queries"],
        )
        reporter.check_cancel()

        # 3/4 — mining + analysis ----------------------------------------
        sources = build_sources(settings)
        reporter.say("sources: " + ", ".join(source.name for source in sources))
        candidates, warnings = mining.mine(
            search_queries,
            sources,
            run_dir / "references",
            per_query=settings.candidates_per_query,
            max_candidates=settings.max_candidates,
            request_delay=settings.request_delay,
            timeout=settings.http_timeout,
            user_agent=settings.user_agent,
            progress=reporter.within("mining"),
            cancel=reporter.cancel,
        )
        result.candidates = len(candidates)
        result.warnings.extend(warnings)
        reporter.check_cancel()
        if not candidates:
            raise RuntimeError(
                "no references could be mined — check connectivity on the Connection tab, "
                "or run in offline mode to use synthetic references"
            )

        # 5/6 — scoring + roles -------------------------------------------
        selected, notes = select_references(
            candidates,
            topic_terms=keywords(topic),
            keep=settings.keep_references,
            minimum=settings.min_reference_score,
        )
        result.warnings.extend(notes)
        references: list[Reference] = assign_roles(selected)
        result.references = references
        reporter.say(
            f"kept {len(references)} references — roles: "
            + ", ".join(r.role.value for r in references if r.role),
            sum(STAGE_WEIGHTS[k] for k in ("trend", "queries", "mining", "select")),
        )
        board.write_board(references, run_dir, title=f"{topic} — reference board")
        reporter.check_cancel()

        # 7/8/9 — DNA, direction, style lock ------------------------------
        dna = build_dna(
            references, ladder, garment=options.garment,
            aggressiveness=options.aggressiveness, llm=llm,
        )
        lock = direction_mod.load_lock(settings.runs_dir, settings.collection)
        art_direction = direction_mod.synthesise(
            ladder, dna, references, seed=settings.seed,
            aggressiveness=options.aggressiveness, lock=lock, llm=llm,
        )
        result.direction = art_direction
        direction_mod.save_lock(settings.runs_dir, settings.collection, art_direction)
        reporter.say(
            f"art direction: {art_direction.style_name}"
            + (" (inherited collection style lock)" if lock else " (new style lock written)"),
            sum(STAGE_WEIGHTS[k] for k in ("trend", "queries", "mining", "select", "dna")),
        )
        reporter.check_cancel()

        # 10/11 — concepts, prompts, quality gate --------------------------
        wanted = options.normalised_variants()
        concepts = [c for c in build_concepts(
            ladder, art_direction, references,
            aggressiveness=options.aggressiveness, seed=settings.seed,
        ) if c.key in wanted]
        for concept in concepts:
            gate.enforce(
                concept, art_direction, ladder, references,
                seed=settings.seed, garment=options.garment,
            )
            concept.prompt = prompts.build_prompt(
                concept, art_direction, ladder, references,
                garment=options.garment, include_text=options.include_text,
            )
            (run_dir / "prompts").mkdir(exist_ok=True)
            (run_dir / "prompts" / f"{concept.key}.txt").write_text(concept.prompt, encoding="utf-8")
            (run_dir / "prompts" / f"{concept.key}_negative.txt").write_text(
                concept.negative_prompt, encoding="utf-8"
            )
        result.concepts = concepts
        result.recommended = recommend(concepts)
        reporter.say(
            "concepts: " + ", ".join(f"{c.key}={c.overall}" for c in concepts)
            + f" — recommended {result.recommended}",
            sum(STAGE_WEIGHTS[k] for k in ("trend", "queries", "mining", "select", "dna", "concepts")),
        )
        reporter.check_cancel()

        # 12/13 — generation + print prep ---------------------------------
        keys = [k.upper() for k in options.generate_keys] or ([result.recommended] if result.recommended else [])
        if options.generate and settings.can_generate and keys:
            client = BFLClient(
                settings.bfl_api_key,
                base_url=settings.bfl_base_url,
                model=settings.bfl_model,
                fallback_model=settings.bfl_fallback_model,
                timeout=settings.http_timeout,
                poll_interval=settings.poll_interval,
                poll_timeout=settings.poll_timeout,
            )
            context_paths = _context_paths(references, options.context_roles)
            for index, key in enumerate(keys):
                concept = result.concept(key)
                if concept is None:
                    result.warnings.append(f"cannot generate unknown variant {key}")
                    continue
                reporter.check_cancel()
                reporter.say(f"generating {key} with {settings.bfl_model} ({len(context_paths)} context images)")
                artwork = run_dir / "artwork" / f"{key}.{settings.output_format}"
                artwork.parent.mkdir(parents=True, exist_ok=True)
                try:
                    client.generate(
                        concept.prompt,
                        artwork,
                        context_paths=context_paths,
                        aspect_ratio=settings.aspect_ratio,
                        output_format=settings.output_format,
                        seed=settings.seed or None,
                        safety_tolerance=settings.safety_tolerance,
                        on_tick=reporter.within("generate"),
                    )
                except BFLError as exc:
                    result.warnings.append(f"generation failed for {key}: {exc}")
                    reporter.say(f"generation failed for {key}: {exc}")
                    continue
                concept.artwork_path = str(artwork)
                concept.print_assets = prepare(
                    artwork, run_dir / "print", key=key, garment=options.garment,
                    width_in=settings.print_width_in, dpi=settings.print_dpi,
                    build_mockup=options.build_mockup,
                )
                reporter.say(f"print package ready for {key}: {concept.print_assets.get('print_size_in', '')}")
        elif options.generate and not settings.can_generate:
            result.warnings.append(
                "generation skipped — no BFL_API_KEY (prompts and print settings are still written)"
            )
            reporter.say("generation skipped: no BFL key configured")

        # 14 — brief, report, manifest ------------------------------------
        for concept in concepts:
            brief.write_brief(result, concept)
        brief.write_report(result)
        dump_json(result, run_dir / "manifest.json")
        reporter.say(f"run complete → {run_dir}", 1.0)

    except Cancelled:
        result.warnings.append("run cancelled by user")
        reporter.say("run cancelled", 1.0)
        dump_json(result, run_dir / "manifest.json")
    except Exception as exc:
        result.warnings.append(f"run failed: {type(exc).__name__}: {exc}")
        reporter.say(f"FAILED: {type(exc).__name__}: {exc}")
        reporter.handle.write(traceback.format_exc())
        dump_json(result, run_dir / "manifest.json")
        reporter.close()
        raise
    finally:
        reporter.close()

    return result


def _context_paths(references: list[Reference], role_names: list[str]) -> list[Path]:
    wanted = [name.upper() for name in role_names]
    ordered: list[Path] = []
    for name in wanted:
        for reference in references:
            if reference.role and reference.role.value == name and reference.local_path:
                ordered.append(Path(reference.local_path))
                break
    if not ordered:
        ordered = [Path(r.local_path) for r in references[:3] if r.local_path]
    return ordered[:4]


def regenerate(
    result: RunResult,
    key: str,
    settings: Settings,
    options: PipelineOptions,
    *,
    seed: int | None = None,
    progress: Progress | None = None,
    log: Log | None = None,
) -> Concept:
    """Re-render one variant of an existing run without re-mining references."""
    concept = result.concept(key)
    if concept is None:
        raise ValueError(f"unknown variant {key}")
    if not settings.can_generate:
        raise BFLError("BFL_API_KEY is not set")

    run_dir = Path(result.run_dir)
    reporter = _Reporter(progress, log, None, run_dir / "run.log")
    try:
        client = BFLClient(
            settings.bfl_api_key, base_url=settings.bfl_base_url, model=settings.bfl_model,
            fallback_model=settings.bfl_fallback_model, timeout=settings.http_timeout,
            poll_interval=settings.poll_interval, poll_timeout=settings.poll_timeout,
        )
        stamp = datetime.now(timezone.utc).strftime("%H%M%S")
        artwork = run_dir / "artwork" / f"{key}-{stamp}.{settings.output_format}"
        artwork.parent.mkdir(parents=True, exist_ok=True)
        reporter.say(f"regenerating {key}")
        client.generate(
            concept.prompt,
            artwork,
            context_paths=_context_paths(result.references, options.context_roles),
            aspect_ratio=settings.aspect_ratio,
            output_format=settings.output_format,
            seed=seed,
            safety_tolerance=settings.safety_tolerance,
            on_tick=lambda fraction, message: reporter.say(message, fraction),
        )
        concept.artwork_path = str(artwork)
        concept.print_assets = prepare(
            artwork, run_dir / "print", key=f"{key}-{stamp}", garment=options.garment,
            width_in=settings.print_width_in, dpi=settings.print_dpi, build_mockup=options.build_mockup,
        )
        brief.write_report(result)
        dump_json(result, run_dir / "manifest.json")
        reporter.say("regeneration complete", 1.0)
    finally:
        reporter.close()
    return concept
