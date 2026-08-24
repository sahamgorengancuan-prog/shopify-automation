"""Market Truth — the gate that decides whether a signal means anything.

A measured rise tells you a word got busier. It does not tell you what the word
*means*, whether anyone cares, or what could be drawn of it. V10 exists because
those three questions were once answered by assumption: `harbor` rose, an
auditor volunteered "mooring bollard", and money was spent on a subject nothing
in the evidence supported.

So this module separates four questions and demands citable evidence for each:

* **intent** — what does the term actually refer to, and how ambiguous is it?
* **buyer** — is there a real, nameable community, evidenced rather than imagined?
* **wear** — why would that community put this on clothing?
* **symbol** — which visible object is tied to that meaning?

The LLM here is an *evidence auditor*, never an evidence generator. It reads
numbered rows harvested from public search and must cite ``E#`` ids for every
claim. Everything it returns is then re-checked deterministically, because a
confident model is not the same thing as a true one. The deterministic guards
cost a research cycle when they are wrong; the alternative costs money and
produces apparel about something nobody meant.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

# Pages that sell printed products. They prove somebody already made a shirt —
# never that a community exists or that it would wear this.
MARKETPLACE_DOMAINS = (
    "etsy.com", "redbubble.com", "teepublic.com", "amazon.", "ebay.", "zazzle.com",
    "society6.com", "spreadshirt.", "displate.com", "printful.com", "aliexpress.",
    "shopee.", "tokopedia.", "merch.", "teespring.com", "threadless.com",
)

# Words too vague to constitute a buyer. "Design-literate minimalists" is the
# canonical invented persona: it describes a taste, not a findable community.
GENERIC_BUYER_WORDS = {
    "people", "everyone", "anyone", "consumers", "customers", "buyers", "fans",
    "enthusiasts", "lovers", "minimalists", "aesthetes", "creatives", "audience",
    "demographic", "millennials", "gen", "z", "adults", "youth", "men", "women",
    "design-literate", "style-conscious", "trend-aware", "modern", "urban",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with",
    "from", "that", "this", "it", "its", "as", "is", "are", "was", "were", "be",
    "who", "what", "which", "their", "they", "them", "about", "into", "over",
}

AMBIGUITY_LEVELS = ("low", "medium", "high")


class MarketTruthError(RuntimeError):
    """Raised when a caller asks for truth it cannot have."""


@dataclass
class EvidenceRow:
    """One numbered, citable piece of public evidence."""

    id: str                      # E1, E2, ...
    query: str
    title: str
    url: str
    snippet: str

    @property
    def domain(self) -> str:
        host = urlparse(self.url).netloc.lower()
        return host[4:] if host.startswith("www.") else host

    @property
    def is_marketplace(self) -> bool:
        return any(marker in self.domain for marker in MARKETPLACE_DOMAINS)

    @property
    def text(self) -> str:
        return f"{self.title} {self.snippet}".lower()

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "query": self.query, "title": self.title, "url": self.url,
                "domain": self.domain, "snippet": self.snippet[:400],
                "marketplace": self.is_marketplace}


@dataclass
class MarketTruth:
    """The verdict, and everything needed to argue with it."""

    topic: str = ""
    passed: bool = False
    failure: str = ""                       # machine-readable reason code
    reason: str = ""                        # one sentence a human can act on
    exact_intent: str = ""
    ambiguity: str = "high"
    buyer_identity: str = ""
    why_they_care: str = ""
    why_they_would_wear_it: str = ""
    nameable_symbol: str = ""
    symbol_evidence: list[str] = field(default_factory=list)
    buyer_evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0
    source: str = "fallback"                # llm | fallback
    independent_domains: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    checked_at: str = ""
    trend_claim_waived: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic, "passed": self.passed, "failure": self.failure,
            "reason": self.reason, "exact_intent": self.exact_intent, "ambiguity": self.ambiguity,
            "buyer_identity": self.buyer_identity, "why_they_care": self.why_they_care,
            "why_they_would_wear_it": self.why_they_would_wear_it,
            "nameable_symbol": self.nameable_symbol, "symbol_evidence": self.symbol_evidence,
            "buyer_evidence": self.buyer_evidence, "confidence": self.confidence,
            "source": self.source, "independent_domains": self.independent_domains,
            "evidence": self.evidence, "checked_at": self.checked_at,
            "trend_claim_waived": self.trend_claim_waived,
        }


# --- lexical grounding ----------------------------------------------------
def tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z][a-z\-']+", str(text).lower())
            if len(word) > 2 and word not in STOPWORDS}


def grounded_in(claim: str, rows: Iterable[EvidenceRow], *, minimum: int = 1) -> bool:
    """Does the claim share real vocabulary with the rows cited for it?

    This is the check that stops an auditor citing a page about a video game
    called "Harbor" while naming "mooring bollard" as the visual subject. It is
    lexical rather than semantic on purpose: it cannot be talked out of.
    """
    claim_tokens = tokens(claim)
    if not claim_tokens:
        return False
    for row in rows:
        if len(claim_tokens & tokens(row.text)) >= minimum:
            return True
    return False


def _cited(rows: list[EvidenceRow], ids: Iterable[Any]) -> list[EvidenceRow]:
    wanted = {str(value).strip().upper() for value in ids or []}
    return [row for row in rows if row.id.upper() in wanted]


# --- evidence harvesting ---------------------------------------------------
def harvest(topic: str, text_source, *, per_query: int = 6) -> list[EvidenceRow]:
    """Collect public rows for the four questions, as separate queries.

    The queries are deliberately plain. Leading them ("why do people love X")
    would manufacture the agreement the gate is supposed to test for.
    """
    topic = " ".join(str(topic).split())
    queries = [
        f"{topic}",
        f"what is {topic}",
        f"{topic} community forum",
        f"{topic} enthusiasts subreddit",
        f"{topic} equipment OR object OR structure",
        f"{topic} photographs",
    ]
    rows: list[EvidenceRow] = []
    seen: set[str] = set()
    for query in queries:
        try:
            results = text_source.search(query, limit=per_query) or []
        except Exception:
            continue
        for result in results:
            url = str(result.get("url", "")).strip()
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append(EvidenceRow(
                id=f"E{len(rows) + 1}", query=query,
                title=str(result.get("title", "")).strip(),
                url=url, snippet=str(result.get("snippet", "")).strip(),
            ))
    return rows


def render_evidence(rows: list[EvidenceRow]) -> str:
    return "\n".join(
        f"{row.id} [{row.domain}] {row.title} :: {row.snippet[:280]}" for row in rows
    )


# --- the auditor -----------------------------------------------------------
INSTRUCTIONS = """You are an evidence auditor for an apparel studio, not a copywriter.

You are given numbered public search rows (E1, E2, ...) about one topic. Decide
what the topic actually means and whether a real audience can be evidenced. You
may only state what the rows support. Every claim must cite the E# ids it rests
on. If the rows do not support a claim, say so and fail the audit — a refusal
costs one research cycle, a wrong pass costs money and ships misleading apparel.

Rules:
- exact_intent: what the term refers to in these rows, in one sentence.
- ambiguity: "low" if the rows agree on one meaning, "medium" if two meanings
  compete, "high" if they scatter or the term is a name shared by unrelated
  things. Do not smooth this over.
- buyer_identity: a specific, findable community named in the rows (a hobby, a
  profession, a fandom, a scene). Never a taste description such as
  "design-literate minimalists" or "modern consumers".
- why_they_care: what this community actually does or values here.
- why_they_would_wear_it: why identifying with this in public makes sense.
- nameable_symbol: one physical object a viewer could name on sight, which the
  cited rows actually mention. Not a mood, not a concept, not a colour.
- Shopping listings (Etsy, Redbubble, Amazon and similar) never prove a
  community exists. They only prove someone printed something.

Answer with JSON only:
{"exact_intent": "...", "ambiguity": "low|medium|high", "buyer_identity": "...",
 "buyer_evidence": ["E3"], "why_they_care": "...", "why_they_would_wear_it": "...",
 "nameable_symbol": "...", "symbol_evidence": ["E5"], "confidence": 0.0-1.0,
 "decision": "pass|fail", "reason": "one sentence"}"""


def _ask(topic: str, rows: list[EvidenceRow], llm) -> dict[str, Any] | None:
    if not llm or not getattr(llm, "available", False):
        return None
    payload = llm._json_call(
        f"{INSTRUCTIONS}\n\nTOPIC: {topic}\n\nEVIDENCE ROWS:\n{render_evidence(rows)}"
    )
    return payload if isinstance(payload, dict) else None


# --- the gate --------------------------------------------------------------
def audit(topic: str, *, text_source=None, llm=None, rows: list[EvidenceRow] | None = None,
          min_confidence: float = 0.70, trend_claim_waived: bool = False) -> MarketTruth:
    """Decide whether this topic has enough truth behind it to spend on."""
    topic = " ".join(str(topic).split())
    verdict = MarketTruth(
        topic=topic,
        checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        trend_claim_waived=bool(trend_claim_waived),
    )
    if not topic:
        verdict.failure, verdict.reason = "no_topic", "no topic was supplied to audit"
        return verdict

    if rows is None:
        if text_source is None:
            raise MarketTruthError("audit needs either evidence rows or a text source to harvest them")
        rows = harvest(topic, text_source)
    verdict.evidence = [row.as_dict() for row in rows]

    if len(rows) < 3:
        verdict.failure = "no_evidence"
        verdict.reason = (
            f"only {len(rows)} public rows could be collected for '{topic}'; there is nothing to audit"
        )
        return verdict

    answer = _ask(topic, rows, llm)
    if answer is None:
        # No auditor is not a pass. A signal nobody has read cannot be spent on.
        verdict.source = "fallback"
        verdict.failure = "no_auditor"
        verdict.reason = (
            "no evidence auditor is available (OPENAI_API_KEY unset), so intent, buyer and symbol "
            "are unproven. Research artefacts were written; live generation stays blocked."
        )
        verdict.exact_intent = ""
        return verdict

    verdict.source = "llm"
    verdict.exact_intent = str(answer.get("exact_intent", "")).strip()
    verdict.ambiguity = str(answer.get("ambiguity", "high")).strip().lower()
    verdict.buyer_identity = str(answer.get("buyer_identity", "")).strip()
    verdict.why_they_care = str(answer.get("why_they_care", "")).strip()
    verdict.why_they_would_wear_it = str(answer.get("why_they_would_wear_it", "")).strip()
    verdict.nameable_symbol = str(answer.get("nameable_symbol", "")).strip()
    verdict.symbol_evidence = [str(value) for value in (answer.get("symbol_evidence") or [])]
    verdict.buyer_evidence = [str(value) for value in (answer.get("buyer_evidence") or [])]
    try:
        verdict.confidence = max(0.0, min(1.0, float(answer.get("confidence", 0.0))))
    except (TypeError, ValueError):
        verdict.confidence = 0.0

    failure, reason = _deterministic_guards(verdict, rows, answer, min_confidence)
    if failure:
        verdict.failure, verdict.reason = failure, reason
        return verdict

    verdict.passed = True
    verdict.reason = str(answer.get("reason", "")).strip() or "intent, buyer, wear and symbol are evidenced"
    return verdict


def _deterministic_guards(verdict: MarketTruth, rows: list[EvidenceRow],
                          answer: dict[str, Any], min_confidence: float) -> tuple[str, str]:
    """Re-check the auditor against the rows. Confidence is not proof."""
    if str(answer.get("decision", "")).strip().lower() == "fail":
        return "auditor_refused", str(answer.get("reason", "")).strip() or "the auditor refused the topic"

    if verdict.ambiguity not in AMBIGUITY_LEVELS:
        verdict.ambiguity = "high"
    if verdict.ambiguity == "high":
        return "intent_ambiguity", (
            f"'{verdict.topic}' does not resolve to one meaning in the evidence, so any subject "
            "chosen for it would be a guess"
        )

    if verdict.confidence < min_confidence:
        return "low_confidence", (
            f"the auditor's confidence {verdict.confidence:.2f} is below the {min_confidence:.2f} floor"
        )

    if not verdict.exact_intent:
        return "no_intent", "the audit did not state what the topic actually refers to"

    if not verdict.why_they_care.strip():
        return "care_reason", "no reason was evidenced for why this community cares"

    if not verdict.why_they_would_wear_it.strip():
        return "wear_reason", "no reason was evidenced for why this would be worn"

    # --- buyer ------------------------------------------------------------
    buyer_words = tokens(verdict.buyer_identity)
    if not verdict.buyer_identity or not buyer_words:
        return "buyer_proof", "no buyer community was named"
    if buyer_words <= GENERIC_BUYER_WORDS:
        return "buyer_proof", (
            f"'{verdict.buyer_identity}' is a taste description, not a findable community"
        )

    buyer_rows = _cited(rows, verdict.buyer_evidence)
    if not buyer_rows:
        return "buyer_proof", "the buyer claim cites no evidence rows"
    if all(row.is_marketplace for row in buyer_rows):
        return "buyer_proof", (
            "the buyer claim rests only on marketplace listings, which prove somebody printed "
            "a shirt rather than that a community exists"
        )
    if not grounded_in(verdict.buyer_identity, buyer_rows):
        return "buyer_proof", (
            f"'{verdict.buyer_identity}' does not appear in the rows cited for it"
        )

    # --- symbol -----------------------------------------------------------
    if not verdict.nameable_symbol:
        return "symbol_proof", "no nameable visual symbol was identified"
    symbol_rows = _cited(rows, verdict.symbol_evidence)
    if not symbol_rows:
        return "symbol_proof", "the symbol claim cites no evidence rows"
    if not grounded_in(verdict.nameable_symbol, symbol_rows):
        return "symbol_proof", (
            f"'{verdict.nameable_symbol}' does not appear in the rows cited for it — this is the "
            "semantic leap V10 exists to block"
        )

    # --- independence -----------------------------------------------------
    supporting = {row.domain for row in (buyer_rows + symbol_rows) if row.domain}
    verdict.independent_domains = sorted(supporting)
    if len(supporting) < 2:
        return "single_source", (
            f"the decision rests on a single domain ({', '.join(supporting) or 'none'}); "
            "at least two independent sources are required"
        )

    return "", ""


# --- persistence -----------------------------------------------------------
def write_audit(verdict: MarketTruth, runs_dir: Path | str, *, name: str = "market_truth_latest.json",
                history: list[MarketTruth] | None = None) -> Path:
    """Write the audit where a human can go and read why money was or wasn't spent."""
    directory = Path(runs_dir) / "_discovery"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selected": verdict.as_dict(),
        "considered": [item.as_dict() for item in (history or [])],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
