"""The gates between a passed Market Truth and a paid generation.

Market Truth proves the topic is real. These two decide whether the *design* has
a reason to exist and whether its physical claim is more than prose — both
before any credit is spent, because both are cheap to catch in words and
expensive to catch in pixels.
"""

from __future__ import annotations

import pytest

from archivist.discovery.truth import EvidenceRow, MarketTruth
from archivist.house import artdirector, evidence
from archivist.models import Cluster, Reference


class FakeLLM:
    def __init__(self, answer, *, available: bool = True):
        self.answer = answer
        self.available = available

    def _json_call(self, prompt: str):
        return self.answer


def route(**overrides):
    base = {
        "real_subject": "mooring bollard",
        "source_property": "the collar carries the rope load that would otherwise slip the head",
        "hero_motif": "a cast bollard head split once under mooring load",
        "signature_interruption": "one rope groove stops where the casting failed",
        "visual_treatment": "flat relief print with cast iron tooth",
        "placement_logic": "the body enters low-right where the quay edge would be",
        "mutation": "fracture",
        "statement": "",
        "silhouette": {"key": "bollard", "label": "mooring bollard"},
    }
    base.update(overrides)
    return base


# --- authorship: the AI tells --------------------------------------------
def test_a_physically_caused_route_passes():
    audit = artdirector.review(route())
    assert audit.passed, audit.reason
    assert audit.tells == {}


@pytest.mark.parametrize("field,text,expected", [
    ("hero_motif", "a bollard with flowing waves around its base", "arbitrary_waves"),
    ("visual_treatment", "scattered fragments drifting across the field", "floating_fragments"),
    ("hero_motif", "an amorphous abstract shape suggesting a harbour", "mystery_blob"),
    ("visual_treatment", "heavy grunge and vintage distress over everything", "generic_distress"),
    ("signature_interruption", "a cryptic symbol marks the break", "pseudo_symbol"),
    ("visual_treatment", "schematic overlay with measurement marks", "pseudo_diagram"),
])
def test_decorative_tells_are_refused_before_anything_is_spent(field, text, expected):
    audit = artdirector.review(route(**{field: text}))
    assert not audit.passed
    assert expected in audit.tells
    assert any(expected in failure for failure in audit.failures)


def test_a_route_with_no_physical_cause_is_refused():
    """Distress that follows nothing is decoration wearing a brief."""
    audit = artdirector.review(route(
        source_property="it feels industrial and mysterious",
        hero_motif="a shape that reads as maritime",
        signature_interruption="a break somewhere in the form",
        placement_logic="placed off-centre for balance",
        visual_treatment="flat print",
    ))
    assert not audit.passed
    assert any("no_physical_cause" in failure for failure in audit.failures)


def test_copy_cannot_stand_in_for_a_missing_hero():
    audit = artdirector.review(route(hero_motif="", statement="The line stays."))
    assert not audit.passed
    assert any("copy_rescue" in failure for failure in audit.failures)


def test_no_copy_is_not_a_fault():
    assert artdirector.review(route(statement="")).passed


# --- authorship: the art director ----------------------------------------
def _scores(**overrides):
    scores = {name: 9.0 for name in (
        "subject_recognition", "physical_logic", "composition_necessity",
        "reduction_discipline", "originality", "human_authorship", "wearability",
        "copy_necessity")}
    scores.update(overrides)
    return {"scores": scores, "worst_problem": "", "verdict": "pass"}


def test_a_weak_critical_score_fails_however_high_the_rest_are():
    audit = artdirector.review(route(), FakeLLM(_scores(subject_recognition=4.0)))
    assert not audit.passed
    assert audit.source == "llm"
    assert any("low_subject_recognition" in failure for failure in audit.failures)


def test_a_weak_non_critical_score_is_a_warning_not_a_block():
    audit = artdirector.review(route(), FakeLLM(_scores(reduction_discipline=6.0)))
    assert audit.passed
    assert audit.warnings and "reduction_discipline" in audit.warnings[0]


def test_the_art_director_can_refuse_outright():
    audit = artdirector.review(route(), FakeLLM(
        {**_scores(), "verdict": "fail", "worst_problem": "this is a genre, not a design"}))
    assert not audit.passed
    assert audit.reason == "this is a genre, not a design"


def test_deterministic_tells_are_checked_before_the_model_is_asked():
    """A route that admits to swooshes never reaches a paid reviewer."""
    audit = artdirector.review(route(hero_motif="a swoosh over the quay"),
                               FakeLLM(_scores()))
    assert not audit.passed
    assert audit.source == "deterministic"


# --- subject and property evidence ---------------------------------------
def _reference(title: str) -> Reference:
    return Reference(id=title[:8], source="test", query="bollard", cluster=Cluster.LITERAL,
                     title=title, page_url="https://example.test/x",
                     image_url="https://example.test/x.jpg")


def _truth(**overrides) -> MarketTruth:
    verdict = MarketTruth(topic="mooring bollard", passed=True)
    verdict.exact_intent = "cast fittings on quays that secure ships"
    verdict.why_they_care = "they document dock furniture"
    verdict.evidence = [EvidenceRow("E1", "q", "Bollard collars", "https://a.test/1",
                                    "The collar carries rope load so the line cannot slip.").as_dict()]
    for key, value in overrides.items():
        setattr(verdict, key, value)
    return verdict


def test_a_supported_property_passes():
    audit = evidence.audit(route(), references=[_reference("Bollard rope load collar detail")],
                           market_truth=_truth())
    assert audit.passed, audit.reason
    assert audit.property_supported
    assert audit.silhouette_key == "bollard"


def test_plausible_prose_is_not_proof():
    audit = evidence.audit(
        route(source_property="the harbour remembers every ship that ever left"),
        references=[_reference("Bollard casting photographs")], market_truth=_truth(),
    )
    assert not audit.passed
    assert "unsupported_property" in audit.failures


def test_a_generic_mass_can_be_previewed_but_never_paid_for():
    """Regression 4: the blob that made the model guess the object."""
    unknown = route(real_subject="ineffable vibes", hero_motif="a form",
                    silhouette={"key": "mass", "label": "irregular material body"})

    live = evidence.audit(unknown, references=[_reference("x")], market_truth=_truth(), live=True)
    assert not live.passed
    assert "unsupported_silhouette" in live.failures
    assert not live.supports_live_spend

    preview = evidence.audit(unknown, references=[_reference("x")], market_truth=_truth(), live=False)
    assert "unsupported_silhouette" not in preview.failures, "previewing a vague route is allowed"


def test_a_route_with_no_subject_or_no_property_fails_loudly():
    assert "no_subject" in evidence.audit(route(real_subject="")).failures
    assert "no_property" in evidence.audit(route(source_property="")).failures


def test_market_evidence_alone_can_support_the_property():
    """The claim may be proved by the truth rows even with no image research yet."""
    audit = evidence.audit(route(), references=[], market_truth=_truth())
    assert audit.passed, audit.reason
    assert audit.support
