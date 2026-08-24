"""Market Truth — the gate that stands between a measured word and a paid image.

Every test here is one of the failures in the V10.1 framework's regression list.
The gate is deliberately conservative: a false negative costs a research cycle,
a false positive costs money and ships apparel about something nobody meant.
"""

from __future__ import annotations

import json

import pytest

from archivist.discovery import truth


class FakeLLM:
    """An auditor whose answer the test controls."""

    def __init__(self, answer, *, available: bool = True):
        self.answer = answer
        self.available = available
        self.prompts: list[str] = []

    def _json_call(self, prompt: str):
        self.prompts.append(prompt)
        return self.answer


class FakeSearch:
    def __init__(self, rows):
        self.rows = rows
        self.queries: list[str] = []

    def search(self, query: str, limit: int = 6):
        self.queries.append(query)
        return self.rows[:limit]


def rows_for(*specs) -> list[truth.EvidenceRow]:
    return [
        truth.EvidenceRow(id=f"E{index}", query="q", title=title, url=url, snippet=snippet)
        for index, (title, url, snippet) in enumerate(specs, start=1)
    ]


BOLLARD_ROWS = rows_for(
    ("Mooring bollards on the quay", "https://portstructures.org/bollards",
     "Cast iron mooring bollards secure vessels alongside a quay wall."),
    ("Harbour history society", "https://reddit.com/r/harbourhistory",
     "The harbour history society photographs mooring bollards, capstans and cranes."),
    ("Dock furniture survey", "https://maritimeheritage.org/dock-furniture",
     "A survey of surviving dock furniture including bollards and bitts."),
    ("Harbor the board game", "https://boardgamegeek.com/harbor",
     "A worker placement game named Harbor, unrelated to ports."),
)


def good_answer(**overrides):
    answer = {
        "exact_intent": "cast fittings on quays that secure ships",
        "ambiguity": "low",
        "buyer_identity": "harbour history society members",
        "buyer_evidence": ["E2", "E3"],
        "why_they_care": "they document surviving dock furniture before it is scrapped",
        "why_they_would_wear_it": "it signals membership of a small preservation community",
        "nameable_symbol": "mooring bollard",
        "symbol_evidence": ["E1", "E3"],
        "confidence": 0.86,
        "decision": "pass",
        "reason": "intent, community and symbol are all evidenced",
    }
    answer.update(overrides)
    return answer


def audit(answer, rows=None, **kwargs):
    return truth.audit("harbor", rows=rows if rows is not None else BOLLARD_ROWS,
                       llm=FakeLLM(answer), **kwargs)


# --- the happy path ------------------------------------------------------
def test_a_fully_evidenced_topic_passes_and_keeps_its_receipts():
    verdict = audit(good_answer())
    assert verdict.passed, verdict.reason
    assert verdict.nameable_symbol == "mooring bollard"
    assert verdict.source == "llm"
    assert len(verdict.independent_domains) >= 2, "a decision needs more than one source"
    assert len(verdict.evidence) == len(BOLLARD_ROWS), "the rows it judged are kept for review"


# --- regression 1: harbor ambiguity --------------------------------------
def test_high_ambiguity_fails_however_confident_the_auditor_is():
    verdict = audit(good_answer(ambiguity="high", confidence=0.99))
    assert not verdict.passed
    assert verdict.failure == "intent_ambiguity"


# --- regression 4 / §19: the semantic leap -------------------------------
def test_a_symbol_must_appear_in_the_rows_cited_for_it():
    """The exact V10 failure: cite a page about a game, name a bollard."""
    verdict = audit(good_answer(nameable_symbol="mooring bollard", symbol_evidence=["E4"]))
    assert not verdict.passed
    assert verdict.failure == "symbol_proof"
    assert "does not appear" in verdict.reason


def test_a_symbol_with_no_citation_at_all_fails():
    assert audit(good_answer(symbol_evidence=[])).failure == "symbol_proof"


# --- regression 3: the invented persona ----------------------------------
@pytest.mark.parametrize("persona", [
    "design-literate minimalists",
    "modern consumers",
    "aesthetes and creatives",
])
def test_a_taste_description_is_not_a_buyer(persona):
    verdict = audit(good_answer(buyer_identity=persona))
    assert not verdict.passed
    assert verdict.failure == "buyer_proof"


def test_a_buyer_must_appear_in_the_rows_cited_for_it():
    verdict = audit(good_answer(buyer_identity="competitive freediving instructors"))
    assert verdict.failure == "buyer_proof"
    assert "does not appear" in verdict.reason


def test_marketplace_listings_do_not_prove_a_community():
    """Someone printed a shirt. That is not evidence anyone wanted one."""
    rows = rows_for(
        ("Mooring bollard tee", "https://www.etsy.com/listing/1/bollard-shirt",
         "Mooring bollard t-shirt for harbour history society fans."),
        ("Bollard print", "https://www.redbubble.com/i/bollard",
         "Mooring bollard design for the harbour history society."),
        ("Dock furniture survey", "https://maritimeheritage.org/dock-furniture",
         "A survey of surviving dock furniture including mooring bollards."),
    )
    verdict = audit(good_answer(buyer_evidence=["E1", "E2"], symbol_evidence=["E3"]), rows=rows)
    assert not verdict.passed
    assert verdict.failure == "buyer_proof"
    assert "marketplace" in verdict.reason


# --- §19: the remaining deterministic guards -----------------------------
def test_a_missing_care_reason_fails():
    assert audit(good_answer(why_they_care="  ")).failure == "care_reason"


def test_a_missing_wear_reason_fails():
    assert audit(good_answer(why_they_would_wear_it="")).failure == "wear_reason"


def test_confidence_below_the_floor_fails():
    verdict = audit(good_answer(confidence=0.5), min_confidence=0.70)
    assert verdict.failure == "low_confidence"


def test_an_auditor_that_refuses_is_believed():
    verdict = audit(good_answer(decision="fail", reason="the rows describe three unrelated things"))
    assert not verdict.passed
    assert verdict.failure == "auditor_refused"
    assert "unrelated" in verdict.reason


def test_one_domain_supporting_everything_is_not_two_sources():
    rows = rows_for(
        ("Bollards", "https://portstructures.org/bollards", "Mooring bollards secure vessels."),
        ("Society", "https://portstructures.org/society",
         "The harbour history society documents mooring bollards."),
        ("More", "https://portstructures.org/more", "Further mooring bollard records."),
    )
    verdict = audit(good_answer(buyer_evidence=["E2"], symbol_evidence=["E1"]), rows=rows)
    assert verdict.failure == "single_source"


# --- no auditor is not a pass --------------------------------------------
def test_without_an_auditor_the_gate_blocks_rather_than_waves_through():
    verdict = truth.audit("harbor", rows=BOLLARD_ROWS, llm=None)
    assert not verdict.passed
    assert verdict.failure == "no_auditor"
    assert verdict.source == "fallback"


def test_too_little_evidence_is_not_something_to_audit():
    verdict = truth.audit("harbor", rows=BOLLARD_ROWS[:1], llm=FakeLLM(good_answer()))
    assert verdict.failure == "no_evidence"


def test_an_empty_topic_is_refused():
    assert truth.audit("", rows=BOLLARD_ROWS, llm=FakeLLM(good_answer())).failure == "no_topic"


# --- harvesting ----------------------------------------------------------
def test_harvest_numbers_rows_and_drops_duplicate_urls():
    source = FakeSearch([
        {"title": "A", "url": "https://a.test/1", "snippet": "one"},
        {"title": "B", "url": "https://b.test/2", "snippet": "two"},
    ])
    rows = truth.harvest("mooring bollard", source)

    assert [row.id for row in rows] == ["E1", "E2"], "each url appears once, numbered for citation"
    assert len(source.queries) > 1, "the four questions are asked separately"
    assert not any("why do people love" in query for query in source.queries), \
        "leading queries would manufacture the agreement the gate is testing for"


def test_harvest_survives_a_search_source_that_throws():
    class Broken:
        def search(self, query, limit=6):
            raise RuntimeError("network down")

    assert truth.harvest("anything", Broken()) == []


def test_audit_without_rows_or_a_source_is_a_programming_error():
    with pytest.raises(truth.MarketTruthError):
        truth.audit("harbor")


# --- persistence ---------------------------------------------------------
def test_the_audit_is_written_where_a_human_can_read_it(tmp_path):
    verdict = audit(good_answer())
    rejected = audit(good_answer(ambiguity="high"))
    path = truth.write_audit(verdict, tmp_path, history=[verdict, rejected])

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name == "market_truth_latest.json"
    assert payload["selected"]["passed"] is True
    assert [row["failure"] for row in payload["considered"]] == ["", "intent_ambiguity"], \
        "rejected candidates are kept — that is the point of an audit trail"
