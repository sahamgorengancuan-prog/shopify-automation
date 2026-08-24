"""One house session, end to end.

    public-signal discovery → intent gate → creative route → pipeline (house mode)
    → structural gate → one paid generation → local proof → delivery

Nothing after the structural gate costs money until the gate passes, and nothing
is packaged as a final unless the proof accepts it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
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
    market_truth: Any = None
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
    """Dynamic public-signal discovery, then the intent gate over the leaders.

    V10.1 §2.1: autonomous discovery may not start from a house-preferred list.
    The engine harvests what the public is actually searching and posting about;
    the volume tool remains available as a diagnostic the caller drives, but it
    no longer decides what this bot is interested in.
    """
    config = DiscoveryConfig(
        geo=settings.trends_geo, timeframe=settings.trends_timeframe,
        max_candidates=settings.discovery_candidates, keep=max(5, settings.discovery_keep),
        use_llm=bool(llm), measure_social=True,
    )
    engine = DiscoveryEngine(settings, config=config, llm=llm, log=log)
    report = engine.discover(
        progress=(lambda fraction, message: progress(0.05 + fraction * 0.25, message)) if progress else None,
    )

    leaders = [row.topic for row in report.opportunities][:5]
    if not leaders:
        raise HouseBlocked(
            "Public signal discovery returned no measurable candidate. Nothing was generated "
            "and no credit was used. Check connectivity, widen the geo, or set a topic explicitly."
        )

    log("intent validation of the discovered leaders")
    for candidate in leaders:
        intent = validate_intent(candidate, llm)
        log(
            f"  {candidate:<24} {intent['decision']:<20} confidence {float(intent['confidence']):.2f} "
            f"| ambiguity {intent['ambiguity']} | judged by {intent.get('source', 'fallback')}"
        )
        judged = intent.get("source") == "llm"
        confident = float(intent["confidence"]) >= MIN_INTENT_CONFIDENCE
        # A model that judged must be confident; with no model the deterministic
        # verdict stands, otherwise discovery could never proceed without a key.
        if intent["decision"] == "use-broad-signal" and (confident or not judged):
            measured = next((row for row in report.opportunities if row.topic == candidate), None)
            evidence = {
                "chosen_by": "public_signal_discovery_plus_intent_validation",
                "opportunity_score": getattr(measured, "score", 0.0),
                "growth_3m": getattr(measured, "growth_3m", 0.0),
                "social_heat": getattr(measured, "social_heat", 0.0),
                "competition": getattr(measured, "competition", 0.0),
                "sources": getattr(measured, "sources", []),
                "report": str(settings.runs_dir / "_discovery" / "latest.json"),
                "intent_validation": intent,
            }
            return candidate, intent, evidence

    raise HouseBlocked(
        f"None of the {len(leaders)} discovered leaders survived the intent gate "
        f"({', '.join(leaders)}). Nothing was generated and no credit was used. Set a topic "
        "explicitly, widen the geo, or run discovery again later."
    )


def _market_truth(market_signal: str, settings: Settings, llm, *, log: Log,
                  trend_claim_waived: bool, user_topic: bool):
    """Audit what the signal means, and write the audit where it can be read."""
    from ..discovery import truth as truth_mod
    from ..sources.duckduckgo import DuckDuckGoText

    if settings.offline:
        from ..discovery.offline import market_truth_rehearsal

        verdict = market_truth_rehearsal(market_signal)
    else:
        verdict = truth_mod.audit(
            market_signal,
            text_source=DuckDuckGoText(user_agent=settings.user_agent, timeout=settings.http_timeout),
            llm=llm, min_confidence=settings.market_truth_min_confidence,
            trend_claim_waived=trend_claim_waived,
        )

    log(
        f"market truth: {'passed' if verdict.passed else 'BLOCKED (' + verdict.failure + ')'} "
        f"| intent {verdict.exact_intent or '—'} | symbol {verdict.nameable_symbol or '—'} "
        f"| buyer {verdict.buyer_identity or '—'}"
    )
    if not verdict.passed:
        log(f"  reason: {verdict.reason}")

    truth_mod.write_audit(
        verdict, settings.runs_dir,
        name="user_topic_market_truth_latest.json" if user_topic else "market_truth_latest.json",
    )
    return verdict


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

    # 1b — market truth ----------------------------------------------------
    # A user-supplied topic waives the claim that it is *trending*. It does not
    # waive what the topic means, who cares, or what could be drawn of it: those
    # are what a paid generation would otherwise be guessing at (V10.1 §5).
    progress(0.22, "auditing market truth")
    market_truth = _market_truth(
        market_signal, settings, llm, log=log,
        trend_claim_waived=bool(topic.strip()), user_topic=bool(topic.strip()),
    )
    house_result.market_truth = market_truth
    house_result.discovery["market_truth"] = market_truth.as_dict()
    if not market_truth.passed:
        house_result.warnings.append(
            f"market truth did not pass ({market_truth.failure}): {market_truth.reason}"
        )

    # 2 — the creative route ----------------------------------------------
    progress(0.32, "building the creative route")
    route = build_route(
        market_signal, llm, intent=intent, market_truth=market_truth,
        anchor=settings.house_anchor, seed=settings.seed,
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
    # House mode runs 16 targeted queries and keeps at most five references, so
    # mining a 60-candidate pool is wasted bandwidth (and, live, wasted requests).
    settings.max_queries = min(settings.max_queries, 16)
    settings.candidates_per_query = min(settings.candidates_per_query, 3)
    settings.max_candidates = min(settings.max_candidates, 24)
    settings.keep_references = min(settings.keep_references, 5)

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
