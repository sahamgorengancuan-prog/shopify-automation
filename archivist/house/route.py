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

REQUIRED_FIELDS = (
    "real_subject", "source_property", "artistic_topic", "product_title", "mutation",
    "metaphor", "hero_motif", "signature_interruption", "placement_logic", "statement",
)


def choose_anchor(market_signal: str, *, anchor: str = "auto", seed: int = 0) -> str:
    if anchor in ANCHORS:
        return anchor
    return random.Random(f"house-anchor|{market_signal}|{seed}").choice(list(ANCHORS))


# --- fallbacks -----------------------------------------------------------
# Each family is a genuinely designed route, not filler: when the model is
# unavailable or writes something weak, this is what ships.
_FAMILIES: tuple[tuple[tuple[str, ...], dict[str, Any]], ...] = (
    (
        ("harbor", "harbour", "tide", "port", "coast", "sea level", "quay", "dock"),
        {
            "real_subject": "tidal range gauge plates fixed to harbor walls",
            "source_property": "the marker stays fixed while the water level repeatedly crosses it",
            "buyer_identity": "design-literate wearers drawn to maritime infrastructure and restrained abstraction",
            "artistic_topic": "Measured Drift",
            "product_title": "Measured Drift",
            "mutation": "erode",
            "cultural_tension": "a fixed system tries to describe an environment that never stays still",
            "metaphor": "one interrupted measuring edge becomes the shoreline between permanence and change",
            "hero_motif": "a broad chipped enamel gauge plate cut by one displaced tidal edge",
            "signature_interruption": "one short horizontal datum stops before it meets the eroded field",
            "visual_treatment": "flat relief print with chipped enamel tooth confined inside a decisive silhouette",
            "palette": ["#F2EFE8", "#3F5667", "#A65A3A"],
            "statement": "The line stays. The tide doesn't.",
            "statement_meaning": "The fixed gauge and the moving tide describe the difference between reference and change.",
            "rendering_mode": "field",
            "product_hook": "A displaced tidal field where the fixed line matters because everything around it moves.",
        },
    ),
    (
        ("deep sea", "ocean", "bathym", "trench", "marine", "subsea", "seafloor"),
        {
            "real_subject": "abyssal trench bathymetry and layered seafloor strata",
            "source_property": "depth is assigned by measurement while the terrain continues beyond a readable edge",
            "buyer_identity": "design-literate wearers drawn to ocean science and unresolved terrain",
            "artistic_topic": "Hadal Scar",
            "product_title": "Hadal Scar",
            "mutation": "incise",
            "cultural_tension": "measurement promises an ending where the terrain only continues",
            "metaphor": "the deepest contour becomes an unresolved wound rather than a chart",
            "hero_motif": "one layered geological strata body broken by a narrow descending incision",
            "signature_interruption": "the incision stops before resolving the lower edge",
            "visual_treatment": "hand-cut geological relief with restrained dry ink and a clean outer field",
            "palette": ["#E6E0D4", "#777875", "#A64232"],
            "statement": "The bottom is only a measurement.",
            "statement_meaning": "Depth is a human reading, not proof that the terrain has ended.",
            "rendering_mode": "field",
            "product_hook": "A displaced geological field about the limit of measuring what lies below.",
        },
    ),
    (
        ("signal", "radio", "radar", "telemetry", "analog", "analogue", "satellite", "sonar",
         "navigation", "lighthouse", "beacon", "lens", "optics", "observatory", "antenna"),
        {
            "real_subject": "a steel signal mast carrying interrupted receiver traces",
            "source_property": "a transmission can arrive without producing a complete reception",
            "buyer_identity": "analogue technology collectors who prefer quiet conceptual graphics",
            "artistic_topic": "Unreceived",
            "product_title": "Unreceived",
            "mutation": "attenuate",
            "cultural_tension": "arrival is measurable while understanding is not guaranteed",
            "metaphor": "one signal body loses its terminal fragment across an active gap",
            "hero_motif": "a tapered signal mast split once below its detached terminal head",
            "signature_interruption": "one precise receiving gap remains visibly unresolved",
            "visual_treatment": "coarse relief waveform with a selective phosphor-like dry edge",
            "palette": ["#DDDCCF", "#66746D", "#B3573E"],
            "statement": "Arrival never guaranteed reception.",
            "statement_meaning": "Physical arrival and actual understanding are different events.",
            "rendering_mode": "linework",
            "product_hook": "An interrupted signal field about the distance between arrival and reception.",
        },
    ),
    (
        ("industrial", "machine", "machinery", "engineering", "infrastructure", "archaeology",
         "foundry", "shipyard", "railway", "bridge", "tunnel", "mining"),
        {
            "real_subject": "a riveted bridge truss carrying visible structural stress traces",
            "source_property": "the material keeps its deformation after the original load has gone",
            "buyer_identity": "people who read machines as material history rather than nostalgia",
            "artistic_topic": "Residual Load",
            "product_title": "Residual Load",
            "mutation": "fracture",
            "cultural_tension": "function ends while force remains legible in the material",
            "metaphor": "one compressed body retains the profile of an absent force",
            "hero_motif": "a riveted truss frame fractured along one displaced stress seam",
            "signature_interruption": "one stress seam exits the frame and stops in empty space",
            "visual_treatment": "mineral rubbing and oxidised relief edge inside a strong flat silhouette",
            "palette": ["#E5DED0", "#6F716E", "#A34B35"],
            "statement": "Force leaves. The shape remains.",
            "statement_meaning": "The material outlasts the event that changed it.",
            "rendering_mode": "dense-relief",
            "product_hook": "A displaced structural field about force remaining visible after the work ends.",
        },
    ),
)


def fallback_route(market_signal: str, *, anchor: str = "auto", seed: int = 0) -> dict[str, Any]:
    lowered = market_signal.lower()
    chosen_anchor = choose_anchor(market_signal, anchor=anchor, seed=seed)

    route: dict[str, Any] | None = None
    for terms, body in _FAMILIES:
        if any(term in lowered for term in terms):
            route = dict(body)
            break
    if route is None:
        # The generic family still has to name a real object: a vague subject is
        # exactly what fails the visual critic's subject_truth check.
        route = {
            "real_subject": f"a bolted steel inspection plate on a {market_signal} installation",
            "source_property": "the plate keeps the impact marks of every inspection it has survived",
            "buyer_identity": "design-literate wearers who value research-driven abstraction",
            "artistic_topic": "Displaced Evidence",
            "product_title": "Displaced Evidence",
            "mutation": "displace",
            "cultural_tension": "an absent cause still determines how the remaining material is read",
            "metaphor": "one material body shifts because the missing portion still carries visual weight",
            "hero_motif": "a bolted steel plate, its outline broken once along the load edge",
            "signature_interruption": "one line exits the body and remains deliberately unfinished",
            "visual_treatment": "hand-cut relief with material grain confined inside a decisive contour",
            "palette": ["#E4DED1", "#737572", "#A74332"],
            "statement": "Missing weight still shifts the field.",
            "statement_meaning": "Absence continues to influence the balance of what remains.",
            "rendering_mode": "field",
            "product_hook": "An asymmetric material field in which absence remains physically active.",
        }

    route["placement_logic"] = (
        f"the material body enters from {chosen_anchor}; its interruption points into the opposing "
        "empty field without creating a counterweight"
    )
    _finalise(route, market_signal, chosen_anchor)
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
    anchor: str = "auto",
    seed: int = 0,
    statement_override: str = "",
    critic_note: str = "",
) -> dict[str, Any]:
    """Produce the creative bridge for one market signal."""
    fallback = fallback_route(market_signal, anchor=anchor, seed=seed)
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
    routes_payload = llm._json_call(
        "You are the creative director of ARCHIVIST, an independent premium art-apparel label.\n"
        f"Market demand signal: {market_signal}\n"
        f"Validated intent: {json.dumps(validated, ensure_ascii=False)}\n"
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
