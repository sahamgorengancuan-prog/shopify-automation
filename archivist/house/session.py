"""One house session, end to end.

    volume-first discovery → intent gate → creative route → pipeline (house mode)
    → structural gate → one paid generation → local proof → delivery

Nothing after the structural gate costs money until the gate passes, and nothing
is packaged as a final unless the proof accepts it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from ..discovery import volume as volume_mod
from ..discovery.engine import DiscoveryConfig, DiscoveryEngine
from ..llm import LLM
from ..models import RunResult, dump_json
from ..pipeline import PipelineOptions, run as run_pipeline
from . import deliver
from .render import Delivery, HouseRejected, RenderOptions, produce
from .route import build_route, validate_intent
from .rules import HOUSE_RULES

Log = Callable[[str], None]
Progress = Callable[[float, str], None]

MIN_INTENT_CONFIDENCE = 0.60


class HouseBlocked(RuntimeError):
    """The run stopped before spending anything, and says why."""


@dataclass
class HouseResult:
    route: dict[str, Any] = field(default_factory=dict)
    result: RunResult | None = None
    delivery: Delivery | None = None
    discovery: dict[str, Any] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    rejected: str = ""          # path to the review package, when the proof said no
    warnings: list[str] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.delivery is not None

    def summary(self) -> str:
        if not self.route:
            return "no route was produced"
        head = (
            f"{self.route['product_title']} — {self.route['real_subject']} "
            f"/ {self.route['mutation']} · statement: {self.route['statement']}"
        )
        if self.approved:
            return f"approved: {head} → {self.delivery.final_dir}"
        if self.rejected:
            return f"rejected: {head} → {self.rejected}"
        return f"prepared (no generation): {head}"


def _discover_signal(settings: Settings, llm, *, log: Log,
                     progress: Progress | None = None) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Volume-first discovery, then an intent gate over the volume leaders."""
    config = DiscoveryConfig(
        geo=settings.trends_geo, timeframe=settings.trends_timeframe,
        anchors=[], max_candidates=10_000, keep=1, use_llm=False, measure_social=True,
    )
    engine = DiscoveryEngine(settings, config=config, llm=None, log=log)
    report = volume_mod.discover(
        engine, timeframe=settings.trends_timeframe, log=log,
        progress=(lambda fraction, message: progress(0.05 + fraction * 0.25, message)) if progress else None,
    )
    report_path = volume_mod.write_report(report, settings.runs_dir)

    leaders = [report.selected.topic if report.selected else ""]
    leaders += [row.get("topic", "") for row in report.validated]
    leaders = [topic for topic in dict.fromkeys(leaders) if topic][:5]

    log("intent validation of the volume leaders")
    for candidate in leaders:
        intent = validate_intent(candidate, llm)
        log(
            f"  {candidate:<24} {intent['decision']:<20} confidence {float(intent['confidence']):.2f} "
            f"| ambiguity {intent['ambiguity']}"
        )
        if intent["decision"] == "use-broad-signal" and float(intent["confidence"]) >= MIN_INTENT_CONFIDENCE:
            evidence = {
                "chosen_by": "volume_first_plus_intent_validation",
                "relative_volume": report.selected_volume,
                "smart_score": report.selected_score,
                "growth_3m": report.selected.growth_3m if report.selected else 0.0,
                "social_heat": report.selected.social_heat if report.selected else 0.0,
                "competition": report.selected.competition if report.selected else 0.0,
                "sources": report.selected.sources if report.selected else [],
                "measurement_coverage": report.coverage,
                "report": str(report_path),
                "intent_validation": intent,
            }
            return candidate, intent, evidence

    raise HouseBlocked(
        "The highest-volume roots were all too ambiguous for a factual route. Nothing was generated "
        "and no credit was used. Give a topic explicitly, or run discovery again later."
    )


def run_session(
    settings: Settings | None = None,
    options: PipelineOptions | None = None,
    *,
    topic: str = "",
    render_options: RenderOptions | None = None,
    generate: bool = True,
    reset_style_lock: bool = True,
    progress: Progress | None = None,
    log: Log | None = None,
    cancel: Callable[[], bool] | None = None,
) -> HouseResult:
    settings = settings or Settings.from_env()
    log = log or (lambda message: None)
    progress = progress or (lambda fraction, message: None)

    render_options = render_options or RenderOptions(
        budget=settings.house_paid_budget,
        allow_controlled_edit=settings.house_allow_controlled_edit,
        allow_concept_retry=settings.house_allow_concept_retry,
        require_critic=settings.house_require_critic,
        print_statement=settings.house_print_statement,
        seed=settings.seed,
    )
    options = options or PipelineOptions(garment=settings.garment)

    llm = LLM(
        settings.openai_api_key, model=settings.openai_model, base_url=settings.openai_base_url,
        reasoning_effort=settings.openai_reasoning_effort,
        enabled=options.use_llm and settings.can_use_llm,
    )
    house_result = HouseResult()

    # 1 — the market signal ------------------------------------------------
    progress(0.02, "choosing a market signal")
    if topic.strip():
        market_signal = topic.strip()
        intent = validate_intent(market_signal, llm)
        intent.update({"decision": "use-broad-signal", "selected_by_user": True})
        house_result.discovery = {"chosen_by": "user_topic", "intent_validation": intent}
    else:
        market_signal, intent, house_result.discovery = _discover_signal(
            settings, llm, log=log, progress=progress
        )
    log(f"market signal: {market_signal}")

    # 2 — the creative route ----------------------------------------------
    progress(0.32, "building the creative route")
    route = build_route(
        market_signal, llm, intent=intent, anchor=settings.house_anchor, seed=settings.seed,
        statement_override=settings.house_statement_override,
    )
    house_result.route = route
    house_result.discovery.update({
        "market_signal": market_signal,
        "artistic_topic": route["artistic_topic"],
        "product_title": route["product_title"],
        "house_system": HOUSE_RULES["system_name"],
        "framework": HOUSE_RULES["version"],
        "statement": route["statement"],
        "silhouette": route.get("silhouette", {}),
        "creative_bridge": route,
    })
    log(
        f"route: {route['product_title']} | subject {route['real_subject']} | mutation {route['mutation']} "
        f"| silhouette {(route.get('silhouette') or {}).get('label')} | statement \"{route['statement']}\""
    )

    if reset_style_lock:
        from ..direction import clear_lock

        cleared = clear_lock(settings.runs_dir, settings.collection)
        log("previous collection style lock cleared" if cleared else "collection style lock starts clean")

    # 3 — the pipeline, narrowed by the route ------------------------------
    run_options = PipelineOptions(
        audience=route["buyer_identity"] or options.audience,
        garment=options.garment,
        aggressiveness=options.aggressiveness,
        variants=["B"],
        generate=False,               # generation is the house system's own stage
        include_text=False,
        build_mockup=options.build_mockup,
        use_llm=options.use_llm,
        discovery=house_result.discovery,
        house_route=route,
        context_roles=[],             # blueprint-only conditioning
    )
    result = run_pipeline(
        route["artistic_topic"], settings, run_options,
        progress=lambda fraction, message: progress(0.35 + fraction * 0.35, message),
        log=log, cancel=cancel,
    )
    house_result.result = result
    house_result.warnings.extend(result.warnings)

    concept = result.concept(result.recommended)
    if concept is None:
        raise HouseBlocked("the pipeline finished without a recommended concept")
    if not (concept.gate or {}).get("passed"):
        raise HouseBlocked(
            "the structural contract failed, so nothing was generated: "
            + ", ".join((concept.gate or {}).get("failing", []))
        )
    log("structural gate passed — generation is allowed to spend")

    # 4 — one paid generation, then local proof ----------------------------
    # Offline mode still runs the whole finishing chain, on a synthesised frame.
    if generate and (settings.can_generate or settings.offline):
        progress(0.72, "generating and proving")
        try:
            house_result.delivery = produce(
                result, concept, route, settings, run_options, render_options, log=log, llm=llm,
            )
        except HouseRejected as rejection:
            house_result.rejected = str(rejection.package)
            house_result.warnings.append(str(rejection))
            log(str(rejection))
    elif generate:
        house_result.warnings.append(
            "generation skipped — no BFL_API_KEY. The blueprint, prompt contract and listing were still written."
        )
        log("generation skipped: no BFL key configured")

    # 5 — delivery ---------------------------------------------------------
    progress(0.95, "writing the delivery")
    house_result.files = deliver.write_all(result, route, house_result.delivery)
    dump_json(result, Path(result.run_dir) / "manifest.json")
    progress(1.0, house_result.summary())
    log(house_result.summary())
    return house_result
