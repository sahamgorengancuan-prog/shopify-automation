"""Intent → creative route.

Google Trends gives demand, never a concept. Two guards live here:

* **intent validation** — the exact one-or-two word signal is checked for its
  dominant public meaning, so the pipeline cannot leap from a broad word to an
  unmeasured specialist system just because it sounds intellectual;
* **route jury** — three routes are produced (two authored by the model, one
  audited fallback) and a skeptical jury picks one, so a weak invented route can
  never win by default.

The result is a plain dict — the "creative bridge" — which every later stage
reads and which is written into the run directory verbatim.
"""

from __future__ import annotations

import json
import random
from typing import Any

from . import silhouette as silhouette_mod
from .rules import (
    ANCHORS,
    CRITICAL_ROUTE_SCORES,
    HOUSE_RULES,
    INK_RANGES,
    MUTATIONS,
    RENDERING_MODES,
    STATEMENT_LOCKUPS,
    statement_is_valid,
    valid_palette,
)

# What a route must say to be a design at all. V10.1 §11 leaves ``statement`` out
# on purpose: copy is opt-in, and a route with no copy is finished, not partial.
REQUIRED_FIELDS = (
    "real_subject", "source_property", "artistic_topic", "product_title", "mutation",
    "metaphor", "hero_motif", "signature_interruption", "placement_logic",
)


def choose_anchor(market_signal: str, *, anchor: str = "auto", seed: int = 0) -> str:
    if anchor in ANCHORS:
        return anchor
    return random.Random(f"house-anchor|{market_signal}|{seed}").choice(list(ANCHORS))


# --- routes ---------------------------------------------------------------
# V10.1 §6: the topic-family shortcut is gone. A route no longer starts from a
# house-owned idea keyed off a word in the topic — that is how `harbor` became a
# mooring bollard nobody had evidence for. It starts from the symbol Market
# Truth actually verified, or, in preview-only mode, from the literal topic
# clearly marked as unverified.

def _palette(market_signal: str, seed: int) -> list[str]:
    """Three inks, chosen deterministically so a signal keeps its identity."""
    choices = (
        ["#E5DED0", "#6F716E", "#A34B35"],
        ["#DDDCCF", "#66746D", "#B3573E"],
        ["#E4DED1", "#737572", "#A74332"],
        ["#E2DCCC", "#5F6B70", "#9C5330"],
    )
    return list(random.Random(f"house-palette|{market_signal}|{seed}").choice(choices))


def fallback_route(market_signal: str, *, market_truth: Any = None, anchor: str = "auto",
                   seed: int = 0) -> dict[str, Any]:
    """The route the system builds when no model writes one.

    With a passed Market Truth this is a real design: the subject is the symbol
    that was verified, the property comes from what the evidence said the
    community cares about, and the buyer is the one that was proved. Without it,
    the route is explicitly a *preview* of the literal topic — inspectable, and
    barred from live spend by the subject audit.
    """
    chosen_anchor = choose_anchor(market_signal, anchor=anchor, seed=seed)
    symbol = str(getattr(market_truth, "nameable_symbol", "") or "").strip()
    verified = bool(getattr(market_truth, "passed", False)) and bool(symbol)
    subject = symbol if verified else market_signal

    if verified:
        prop = (str(getattr(market_truth, "why_they_care", "")).strip()
                or str(getattr(market_truth, "exact_intent", "")).strip())
        buyer = str(getattr(market_truth, "buyer_identity", "")).strip()
    else:
        # Stated, not blank: a preview route must read as unverified rather than
        # as a route whose evidence merely went missing. The subject audit turns
        # this into a refusal if anyone tries to spend on it.
        prop = "unverified — no market evidence was audited for this preview"
        buyer = "unverified — no buyer community was evidenced"

    route: dict[str, Any] = {
        "real_subject": subject,
        "source_property": prop,
        "buyer_identity": buyer,
        "artistic_topic": subject.title(),
        "product_title": subject.title(),
        "mutation": random.Random(f"house-mutation|{subject}|{seed}").choice(list(MUTATIONS)),
        "cultural_tension": (
            f"what {subject} is for, and what it looks like once it has done the job"
        ),
        "metaphor": f"one {subject} carries the mark of the work it was made to take",
        "hero_motif": f"a single {subject}, its outline broken once along the line that carries load",
        "signature_interruption": "one edge stops where the material gave way, and is not resolved",
        "visual_treatment": "flat relief print with material tooth confined inside a decisive contour",
        "palette": _palette(market_signal, seed),
        "statement": "",                 # V10.1 §11: copy is opt-in
        "statement_meaning": "",
        "rendering_mode": "field",
        "product_hook": f"An asymmetric material study of a {subject}.",
        "evidence_source": "market_truth" if verified else "preview-only",
    }

    route["placement_logic"] = (
        f"the material body enters from {chosen_anchor}; its interruption points into the opposing "
        "empty field without creating a counterweight"
    )
    _finalise(route, market_signal, chosen_anchor)
    if market_truth is not None:
        route["market_truth"] = market_truth.as_dict() if hasattr(market_truth, "as_dict") else dict(market_truth)
    return route


def _finalise(route: dict[str, Any], market_signal: str, anchor: str) -> dict[str, Any]:
    """Apply the parts of the contract the model is never allowed to author."""
    shape = silhouette_mod.choose(str(route.get("real_subject", "")), str(route.get("hero_motif", "")))
    route.setdefault("intent_validation", {
        "source": "fallback",
        "market_signal": market_signal,
        "dominant_intent": f"broad visual and cultural interest around {market_signal}",
        "ambiguity": "unknown",
        "safe_visual_territory": market_signal,
        "forbidden_leap": "do not invent a narrow specialist application that was not measured",
        "decision": "use-broad-signal",
        "confidence": 0.5,
    })
    mode = silhouette_mod.cap_mode(shape, route.get("rendering_mode"))
    ink_low, ink_high = INK_RANGES.get(mode, INK_RANGES["field"])
    route.update({
        "market_signal": market_signal,
        "rendering_mode": mode,
        "asymmetry_anchor": anchor,
        "negative_space_target": "55-70%",
        "art_occupancy_target": f"{ink_low:.0f}-{min(72.0, ink_high):.0f}%",
        "statement_location": "printed microtype",
        "statement_lockup": "right-of-interruption" if "left" in anchor else "left-of-interruption",
        "placement_explanation_location": "product description only",
        "conditioning_policy": "blueprint-only",
        "silhouette": {"key": shape.key, "label": shape.label, "requirement": shape.prompt_note},
        "avoid": list(HOUSE_RULES["prohibited"]),
    })
    return route


# --- intent --------------------------------------------------------------
def validate_intent(market_signal: str, llm=None) -> dict[str, Any]:
    """Separate the dominant public meaning of a broad signal from a narrow one."""
    fallback = {
        "market_signal": market_signal,
        "dominant_intent": f"broad visual and cultural interest around {market_signal}",
        "ambiguity": "unknown",
        "safe_visual_territory": market_signal,
        "forbidden_leap": "do not invent a narrow specialist application that was not measured",
        "decision": "use-broad-signal",
        "confidence": 0.5,
        # 0.5 is a neutral prior, not a measurement — callers must not read it as
        # "probably ambiguous" when no model was available to judge.
        "source": "fallback",
    }
    if llm is None or not getattr(llm, "available", False):
        return fallback

    payload = llm._json_call(
        "Validate one broad Google Trends signal before it becomes apparel art.\n"
        f"Signal: {market_signal}\n\n"
        "Distinguish the dominant public meanings of the exact 1-2 word signal from narrow technical "
        "meanings. The design may enter a niche only when that niche is a direct, recognisable visual "
        "territory of the measured signal. Never jump from a broad signal to an unmeasured specialist "
        "system merely because it sounds intellectual.\n\n"
        "Return strict JSON with: market_signal, dominant_intent, ambiguity (low|medium|high), "
        "safe_visual_territory, forbidden_leap, decision (use-broad-signal|require-user-topic), "
        "confidence (0-1)."
    )
    if not isinstance(payload, dict):
        return fallback
    result = dict(fallback)
    for key in result:
        if payload.get(key) not in (None, ""):
            result[key] = payload[key]
    try:
        result["confidence"] = min(1.0, max(0.0, float(result["confidence"])))
    except (TypeError, ValueError):
        result["confidence"] = 0.5
    result["source"] = "llm"
    return result


# --- normalisation -------------------------------------------------------
def normalise_route(payload: Any, fallback: dict[str, Any], *, statement_override: str = "") -> dict[str, Any]:
    """Accept a model route only where it is complete and legal; else fall back."""
    route = dict(fallback)
    if isinstance(payload, dict):
        for key in route:
            if payload.get(key) not in (None, "", []):
                route[key] = payload[key]

    if not all(str(route.get(key, "")).strip() for key in REQUIRED_FIELDS):
        route = dict(fallback)

    if str(route.get("mutation", "")).strip().lower() not in MUTATIONS:
        route["mutation"] = fallback["mutation"]
    else:
        route["mutation"] = str(route["mutation"]).strip().lower()

    if not statement_is_valid(str(route["statement"])):
        route["statement"] = fallback["statement"]
        route["statement_meaning"] = fallback["statement_meaning"]

    if not valid_palette(route.get("palette")):
        route["palette"] = list(fallback["palette"])

    if route.get("rendering_mode") not in RENDERING_MODES:
        route["rendering_mode"] = fallback.get("rendering_mode", "field")

    if route.get("statement_lockup") not in STATEMENT_LOCKUPS:
        route["statement_lockup"] = fallback.get("statement_lockup", "right-of-interruption")

    if statement_override.strip():
        if not statement_is_valid(statement_override.strip()):
            raise ValueError(
                "The statement override must be 4-8 words, at most 58 characters, with no "
                "exclamation mark, colon, pronoun or slogan vocabulary."
            )
        route["statement"] = statement_override.strip()
        route["statement_meaning"] = "Author-written statement; its interpretation belongs in the product description."

    _finalise(route, fallback["market_signal"], fallback["asymmetry_anchor"])
    return route


# --- the jury ------------------------------------------------------------
def build_route(
    market_signal: str,
    llm=None,
    *,
    intent: dict[str, Any] | None = None,
    market_truth: Any = None,
    anchor: str = "auto",
    seed: int = 0,
    statement_override: str = "",
    critic_note: str = "",
) -> dict[str, Any]:
    """Produce the creative bridge for one market signal.

    ``market_truth`` is what the route is allowed to be about. Without it the
    route is a preview: inspectable, and blocked from live spend downstream.
    """
    fallback = fallback_route(market_signal, market_truth=market_truth, anchor=anchor, seed=seed)
    if statement_override.strip():
        fallback = normalise_route(None, fallback, statement_override=statement_override)
    validated = intent or validate_intent(market_signal, llm)
    fallback["intent_validation"] = validated

    if llm is None or not getattr(llm, "available", False):
        fallback["route_candidates"] = [dict(fallback)]
        fallback["route_jury"] = {"selected_index": 1, "mode": "fallback"}
        return fallback

    repair = (
        f"\nA previous attempt on this signal was rejected by the visual critic: {critic_note}\n"
        "Choose a subject whose silhouette proves itself without a caption.\n"
        if critic_note else ""
    )
    verified_symbol = str(getattr(market_truth, "nameable_symbol", "") or "").strip()
    evidence_brief = ""
    if getattr(market_truth, "passed", False):
        evidence_brief = (
            f"VERIFIED SUBJECT (do not substitute): {verified_symbol}\n"
            f"Verified buyer: {getattr(market_truth, 'buyer_identity', '')}\n"
            f"Why they care: {getattr(market_truth, 'why_they_care', '')}\n"
            f"Why they would wear it: {getattr(market_truth, 'why_they_would_wear_it', '')}\n"
            "Every route must be about that subject. Narrowing to a different object is the "
            "semantic leap this system exists to prevent.\n"
        )
    routes_payload = llm._json_call(
        "You are the creative director of ARCHIVIST, an independent premium art-apparel label.\n"
        f"Market demand signal: {market_signal}\n"
        f"Validated intent: {json.dumps(validated, ensure_ascii=False)}\n"
        + evidence_brief +
        "House system: ASYMMETRIC ABSTRACT FIELD.\n" + repair +
        "\nCreate exactly three genuinely different creative routes. Every route must follow this sequence:\n"
        "1. EVIDENCE — one real, photographable subject inside the validated visual territory. The source "
        "property must be literally true and visible in a reference photograph.\n"
        "2. MUTATION — one physical transformation only: " + ", ".join(MUTATIONS) + ".\n"
        "3. COMPOSITION — one substantial irregular field, not an icon and not stacked decorative blocks. "
        "Shift its visual centre 6-14% off centre. Keep 55-70% quiet space and one interruption.\n"
        "4. STATEMENT — one calm 4-8 word sentence, factually anchored, permitting a second reading. No "
        "adverbs, no motivational language, no pronouns.\n"
        "5. PRODUCT — memorable at 90px and plausible as premium streetwear.\n\n"
        "The real_subject must be a single nameable object whose outline a stranger could identify without "
        "reading anything — never 'debris', 'fragments', 'rubble' or an unnamed mass.\n"
        "Never invent an institution, date, serial number, archive, declassification story, label, document, "
        "chart page, badge or pseudo-text. Do not copy the market signal as a headline.\n"
        f"statement_lockup must be one of {list(STATEMENT_LOCKUPS)}; rendering_mode one of {list(RENDERING_MODES)}.\n\n"
        'Return strict JSON as {"routes":[...]}. Each route contains: real_subject, source_property, '
        "buyer_identity, artistic_topic, product_title, mutation, cultural_tension, metaphor, hero_motif, "
        "signature_interruption, placement_logic, visual_treatment, palette (exactly three hex colours), "
        "statement, statement_meaning, statement_lockup, rendering_mode, product_hook.\n\n"
        f"Fallback quality benchmark: {json.dumps({k: v for k, v in fallback.items() if k != 'route_candidates'}, ensure_ascii=False)}"
    )
    raw_routes = routes_payload.get("routes", []) if isinstance(routes_payload, dict) else []
    # Two authored routes plus the audited fallback: the jury can never be forced
    # to pick a weak invention because nothing else was on the table.
    routes = [
        normalise_route(item, fallback, statement_override=statement_override)
        for item in raw_routes[:2] if isinstance(item, dict)
    ]
    routes.append(dict(fallback))

    jury = llm._json_call(
        "Act as a skeptical apparel buying director and factual editor. Select one route for ARCHIVIST.\n"
        "Reject routes that are literal, decorative, thin, archive-themed, generic AI abstraction, or "
        "dependent on explanation. Reject any source_property that mixes two mechanisms or cannot be seen "
        "in a real reference. Reject any real_subject a stranger could not name from its outline.\n"
        "Score each route 0-10 for: " + ", ".join(CRITICAL_ROUTE_SCORES) + ", asymmetric_tension and print_feasibility.\n"
        f"The selected route must score at least 8 on: {', '.join(CRITICAL_ROUTE_SCORES)}. Do not reward verbose writing.\n"
        'Return strict JSON: {"selected_index":1,"evaluations":[{"index":1,"scores":{},"total":0,"passed":true,"reason":""}]}.\n'
        f"Routes: {json.dumps(routes, ensure_ascii=False)}"
    )

    selected_index = _jury_choice(jury, routes, fallback)
    selected = dict(routes[selected_index - 1])
    selected["intent_validation"] = validated
    selected["route_candidates"] = routes
    selected["route_jury"] = jury if isinstance(jury, dict) else {"selected_index": selected_index, "mode": "fallback"}
    return selected


def _jury_choice(jury: Any, routes: list[dict[str, Any]], fallback: dict[str, Any]) -> int:
    eligible: list[tuple[float, int]] = []
    for row in (jury.get("evaluations", []) if isinstance(jury, dict) else []):
        if not isinstance(row, dict):
            continue
        scores = row.get("scores", {}) if isinstance(row.get("scores"), dict) else {}
        try:
            index = int(row.get("index", 0))
        except (TypeError, ValueError):
            continue
        if 1 <= index <= len(routes) and all(
            float(scores.get(name, 0) or 0) >= 8 for name in CRITICAL_ROUTE_SCORES
        ):
            eligible.append((float(row.get("total", 0) or 0), index))
    if eligible:
        return max(eligible)[1]
    # Nothing cleared the bar: fall back to the audited route rather than the
    # highest-scoring failure.
    return next(
        (index for index, route in enumerate(routes, 1) if route["real_subject"] == fallback["real_subject"]),
        len(routes),
    )
