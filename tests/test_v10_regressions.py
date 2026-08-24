"""The ten failures V10.1 exists to prevent, as executable checks.

These mirror section 15 of the framework document one for one. They are written
against the seams the failure actually passed through, not against the modules
that happen to implement them today — a refactor should keep them meaningful.

The original chain was: `harbor` rises → an auditor volunteers "mooring bollard"
→ a generic blob conditions the model → the model invents something → a strong
composition ships with no subject in it. Every link below is one of those.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from archivist.discovery import fit, truth, volume
from archivist.discovery.engine import DEFAULT_ANCHORS
from archivist.house import artdirector, critic, evidence, render, route, rules, silhouette
from archivist.house.render import RenderOptions, SpendBlocked, produce
from archivist.house.session import run_session
from archivist.pipeline import PipelineOptions


class FakeLLM:
    def __init__(self, answer):
        self.answer = answer
        self.available = True

    def _json_call(self, prompt: str):
        return self.answer


HARBOR_ROWS = [
    truth.EvidenceRow("E1", "q", "Harbor the board game", "https://boardgamegeek.com/harbor",
                      "A worker placement game named Harbor."),
    truth.EvidenceRow("E2", "q", "Harbor freight tools", "https://harborfreight.example/store",
                      "Discount tool retailer."),
    truth.EvidenceRow("E3", "q", "Pearl Harbor anniversary", "https://history.example/pearl-harbor",
                      "Commemorations of the attack."),
]


# --- 1. harbor ambiguity --------------------------------------------------
def test_1_an_ambiguous_keyword_cannot_pass_however_confident_the_auditor():
    """The first link: `harbor` means four things, and none of them is a bollard."""
    verdict = truth.audit("harbor", rows=HARBOR_ROWS, llm=FakeLLM({
        "exact_intent": "a sheltered body of water for ships",
        "ambiguity": "high",
        "buyer_identity": "maritime history enthusiasts",
        "buyer_evidence": ["E3"], "why_they_care": "they study ports",
        "why_they_would_wear_it": "identity", "nameable_symbol": "mooring bollard",
        "symbol_evidence": ["E1"], "confidence": 0.97, "decision": "pass",
    }))
    assert not verdict.passed
    assert verdict.failure == "intent_ambiguity"


# --- 2. a cultural count is not a trend score ----------------------------
def test_2_evidence_count_is_never_reported_as_a_trend_number():
    """Counting pages that mention a word is not measuring demand for it."""
    verdict = truth.audit("harbor", rows=HARBOR_ROWS, llm=None)
    payload = verdict.as_dict()

    numeric = {key: value for key, value in payload.items()
               if isinstance(value, (int, float)) and not isinstance(value, bool)}
    assert set(numeric) <= {"confidence"}, (
        f"Market Truth exposed {sorted(set(numeric) - {'confidence'})} — a count of cultural "
        "evidence must never be presented where a trend measurement belongs"
    )
    assert len(verdict.evidence) not in numeric.values(), "the row count is not a score"
    for word in ("growth", "trend_score", "interest", "volume", "momentum"):
        assert word not in json.dumps(payload).lower(), (
            f"'{word}' appears in a Market Truth verdict — measurement vocabulary belongs to the "
            "discovery report, never to an evidence audit"
        )


# --- 3. the invented persona ---------------------------------------------
def test_3_a_generic_aesthetic_demographic_is_not_buyer_proof():
    rows = [
        truth.EvidenceRow("E1", "q", "Bollard survey", "https://ports.example/bollards",
                          "Cast mooring bollards along the quay."),
        truth.EvidenceRow("E2", "q", "Dock furniture", "https://heritage.example/dock",
                          "Surviving dock furniture including bollards."),
        truth.EvidenceRow("E3", "q", "Quay fittings", "https://ports.example/quay",
                          "Bollards, bitts and capstans along working quays."),
    ]
    verdict = truth.audit("mooring bollard", rows=rows, llm=FakeLLM({
        "exact_intent": "cast fittings that secure ships", "ambiguity": "low",
        "buyer_identity": "design-literate minimalists", "buyer_evidence": ["E1", "E2"],
        "why_they_care": "they like clean design", "why_they_would_wear_it": "taste",
        "nameable_symbol": "mooring bollard", "symbol_evidence": ["E1", "E2"],
        "confidence": 0.9, "decision": "pass",
    }))
    assert not verdict.passed
    assert verdict.failure == "buyer_proof"


# --- 4. the unsupported object -------------------------------------------
def test_4_a_generic_mass_can_be_previewed_but_never_spend_credit():
    """The blob that made the model guess the object."""
    assert not silhouette.supports_live_spend("mass")

    vague = route.fallback_route("ineffable vibes", seed=0)
    assert vague["silhouette"]["key"] == "mass", "an unknown subject falls back to the shrug"

    live = evidence.audit(vague, live=True)
    assert not live.passed and "unsupported_silhouette" in live.failures
    assert "unsupported_silhouette" not in evidence.audit(vague, live=False).failures


# --- 5. random water marks -----------------------------------------------
@pytest.mark.parametrize("motif", [
    "a bollard with flowing waves around its base",
    "a swoosh sweeping past the quay edge",
    "scattered fragments drifting across the field",
])
def test_5_waves_swooshes_and_filler_are_route_anti_patterns(motif):
    assert not artdirector.review({**_route(), "hero_motif": motif}).passed
    assert "swoosh" in " ".join(rules.HOUSE_RULES["prohibited"])


def test_5b_the_critic_is_told_to_refuse_them_in_the_pixels_too():
    text = critic.instructions(_route())
    for tell in ("swoosh", "floating", "distress", "meaningless holes", "measurement marks"):
        assert tell in text.lower(), f"the critic was not warned about {tell}"


# --- 6. fake distress -----------------------------------------------------
def test_6_material_wear_must_follow_a_physical_cause():
    decorative = {**_route(),
                  "source_property": "it feels weathered and mysterious",
                  "hero_motif": "a form suggesting the sea",
                  "signature_interruption": "a break somewhere",
                  "placement_logic": "off-centre for balance",
                  "visual_treatment": "flat print"}
    audit = artdirector.review(decorative)
    assert not audit.passed
    assert any("no_physical_cause" in failure for failure in audit.failures)


# --- 7. mandatory AI poetry ----------------------------------------------
def test_7_no_copy_is_a_valid_finished_state():
    built = route.fallback_route("mooring bollard", seed=0)
    assert built["statement"] == ""
    assert rules.statement_is_valid("")
    assert rules.ACCEPTANCE["statement_required"] is False
    assert "statement" not in route.REQUIRED_FIELDS
    assert artdirector.review(built).passed or built["statement"] == ""


# --- 8. reference leakage -------------------------------------------------
def test_8_searched_pixels_never_reach_the_generator(settings, tmp_path):
    result = run_session(settings, PipelineOptions(garment="dark"), topic="mooring bollard",
                         render_options=RenderOptions(require_critic=False, seed=2), generate=True)
    assert result.approved, result.warnings

    audit = json.loads((tmp_path / "x").parent.joinpath(
        result.result.run_dir, "preinference_audit.json").read_text(encoding="utf-8"))
    assert audit["blueprint"]["searched_reference_pixels_used"] is False
    assert audit["blueprint"]["owned_conditioning_asset"] is True
    assert all(reference.attributes.get("house_conditioning_allowed") is False
               for reference in result.result.references)


# --- 9. false vision status ----------------------------------------------
def test_9_a_skipped_vision_review_is_recorded_as_skipped(settings):
    result = run_session(settings, PipelineOptions(garment="dark"), topic="mooring bollard",
                         render_options=RenderOptions(require_critic=True, seed=3), generate=True)
    assert result.approved
    assert result.delivery.selected["vision_reviewed"] is False

    ranking = json.loads(result.delivery.ranking_path.read_text(encoding="utf-8"))
    assert ranking["status"] == "offline-rehearsal-approved", \
        "a rehearsal must not be recorded as market approval"


# --- 10. best of a bad batch ---------------------------------------------
def test_10_a_failing_candidate_cannot_be_promoted_by_its_total():
    assert rules.ACCEPTANCE["best_of_bad_batch_is_forbidden"] is True
    high_total_weak_critical = {
        "total": 95.0,
        "scores": {name: 9.5 for name in rules.CRITICAL_VISION_SCORES},
        "passed": True,
    }
    high_total_weak_critical["scores"]["subject_truth"] = 3.0
    high_total_weak_critical["scores"]["thumbnail_read"] = 4.0
    assert not critic.passed(high_total_weak_critical), \
        "a critical score below the floor must sink the candidate whatever the total says"


# --- the architecture-level invariants -----------------------------------
def test_no_curated_trend_nouns_seed_autonomous_discovery():
    """§2.1 — the house may not decide in advance what it is interested in."""
    assert fit.VOLUME_ROOTS == []
    with pytest.raises(volume.VolumeDiscoveryError):
        volume.normalise_roots()

    house_nouns = {"harbor", "lighthouse", "radar", "railway", "sonar", "shipyard"}
    assert not house_nouns & {anchor.lower() for anchor in DEFAULT_ANCHORS}
    assert fit.topic_hygiene("harbor") == fit.topic_hygiene("lichen"), \
        "no topic may score higher merely for being a house noun"


def test_live_generation_without_a_passed_market_truth_is_refused(settings, tmp_path):
    """§14/§19 — absence of a truth object is a failure, not permission."""
    prepared = run_session(settings, PipelineOptions(garment="dark"), topic="mooring bollard",
                           render_options=RenderOptions(require_critic=False, seed=4), generate=False)
    live = replace(settings, offline=False)
    stripped = {key: value for key, value in prepared.route.items() if key != "market_truth"}

    with pytest.raises(SpendBlocked) as raised:
        produce(prepared.result, prepared.result.concept("B"), stripped, live,
                PipelineOptions(garment="dark"), RenderOptions(require_critic=False, seed=4))
    assert "no market truth object at all" in str(raised.value)
    assert "no credit was used" in str(raised.value)


def test_the_route_cannot_narrow_past_the_verified_symbol():
    """§23.4 — a confirmed symbol is what the design is about, not a starting point."""
    verdict = truth.MarketTruth(topic="harbor", passed=True)
    verdict.nameable_symbol = "mooring bollard"
    verdict.buyer_identity = "harbour history society members"
    verdict.why_they_care = "they record dock furniture before it is scrapped"

    built = route.fallback_route("harbor", market_truth=verdict, seed=0)
    assert built["real_subject"] == "mooring bollard"
    assert built["silhouette"]["key"] == "bollard", "the verified subject selects real geometry"
    assert built["evidence_source"] == "market_truth"


def _route() -> dict:
    return {
        "real_subject": "mooring bollard",
        "source_property": "the collar carries the rope load that would otherwise slip the head",
        "hero_motif": "a cast bollard head split once under mooring load",
        "signature_interruption": "one rope groove stops where the casting failed",
        "visual_treatment": "flat relief print with cast iron tooth",
        "placement_logic": "the body enters low-right where the quay edge would be",
        "mutation": "fracture", "statement": "",
        "silhouette": {"key": "bollard", "label": "mooring bollard"},
    }
