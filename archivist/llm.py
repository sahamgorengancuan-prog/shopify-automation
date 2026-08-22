"""Optional creative-director assist.

Every stage works without it — the LLM only *refines* what the deterministic
pipeline already produced, and any failure silently falls back. That keeps the
run reproducible offline and stops a missing key from breaking a scheduled job.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import http
from .models import ArtDirection, Cluster, NicheLadder, Reference, VisualDNA

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

SYSTEM = (
    "You are an art director for an independent apparel label that publishes designs as if they "
    "were records from a fictional institution. You refine briefs; you never widen them. "
    "Reply with JSON only, no prose, no markdown fence."
)


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n|\n```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


class LLM:
    """Thin Anthropic Messages wrapper with graceful degradation."""

    def __init__(self, api_key: str = "", model: str = "claude-opus-5", *, timeout: int = 60,
                 max_tokens: int = 1500, enabled: bool = True):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.enabled = enabled
        self.last_error = ""

    @property
    def available(self) -> bool:
        return bool(self.api_key) and self.enabled

    def complete(self, prompt: str, *, max_tokens: int | None = None) -> str:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        }
        response = http.post_json(
            API_URL,
            payload,
            headers={"x-api-key": self.api_key, "anthropic-version": API_VERSION},
            timeout=self.timeout,
            retries=2,
        )
        parts = response.get("content", [])
        return "".join(part.get("text", "") for part in parts if part.get("type") == "text")

    def _json_call(self, prompt: str) -> Any:
        if not self.available:
            return None
        try:
            return _extract_json(self.complete(prompt))
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return None

    # -- refinements ------------------------------------------------------
    def refine_ladder(self, ladder: NicheLadder, *, topic: str, audience: str = "") -> NicheLadder | None:
        data = self._json_call(
            "Sharpen this niche ladder for an apparel design. Keep the escalation from generic to "
            "micro-niche; make the micro-niche specific enough that almost nobody else occupies it.\n"
            f"topic: {topic}\naudience: {audience or 'unspecified'}\n"
            f"current: {json.dumps(ladder.to_dict(), ensure_ascii=False)}\n"
            'Reply as {"generic":str,"better":str,"niche":str,"micro_niche":str,"cultural_signals":[str,...]}'
        )
        if not isinstance(data, dict):
            return None
        return NicheLadder(
            trend=ladder.trend,
            generic=str(data.get("generic") or ladder.generic),
            better=str(data.get("better") or ladder.better),
            niche=str(data.get("niche") or ladder.niche),
            micro_niche=str(data.get("micro_niche") or ladder.micro_niche),
            cultural_signals=[str(s) for s in data.get("cultural_signals", [])] or ladder.cultural_signals,
            audience=ladder.audience,
        )

    def extra_queries(self, *, topic: str, ladder: NicheLadder, existing: list[str]) -> list[tuple[str, Cluster]]:
        data = self._json_call(
            "Propose image-search queries that would surface visual ingredients (not finished designs) "
            f"for this niche: {ladder.micro_niche} (topic: {topic}).\n"
            f"Do not repeat or paraphrase these: {json.dumps(existing[:30], ensure_ascii=False)}\n"
            'Reply as {"queries":[{"text":str,"cluster":"A_literal_subject|B_historical_archival|'
            'C_visual_language|D_texture|E_typography|F_composition"}]} with at most 6 items.'
        )
        if not isinstance(data, dict):
            return []
        out: list[tuple[str, Cluster]] = []
        for row in data.get("queries", [])[:6]:
            try:
                out.append((str(row["text"]), Cluster(row.get("cluster", "C_visual_language"))))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    def refine_dna(self, dna: VisualDNA, *, ladder: NicheLadder, references: list[Reference]) -> VisualDNA | None:
        measured = [
            {"role": r.role.value if r.role else None, "attrs": {
                k: r.attributes.get(k) for k in ("contrast", "grain", "shadow_share", "text_likeness", "palette")
            }}
            for r in references if r.role
        ]
        data = self._json_call(
            "Rewrite this Visual DNA so each field is concrete and directive for an image model. "
            "Stay consistent with the measurements; do not invent references.\n"
            f"niche: {ladder.micro_niche}\nmeasurements: {json.dumps(measured, ensure_ascii=False)}\n"
            f"current: {json.dumps(dna.to_dict(), ensure_ascii=False)}\n"
            "Reply with the same keys and string values (palette stays a list of hex strings)."
        )
        if not isinstance(data, dict):
            return None
        merged = dna.to_dict()
        for key, value in data.items():
            if key in merged and value:
                merged[key] = value
        try:
            return VisualDNA(**merged)
        except TypeError:
            return None

    def refine_direction(self, direction: ArtDirection, *, ladder: NicheLadder) -> ArtDirection | None:
        data = self._json_call(
            "Improve this art direction. The style name must describe the visual system, not the subject. "
            "Keep it wearable and printable.\n"
            f"niche: {ladder.micro_niche}\n"
            f"current: {json.dumps({k: v for k, v in direction.to_dict().items() if k != 'dna'}, ensure_ascii=False)}\n"
            "Reply with the same keys (descriptors is a list of short strings)."
        )
        if not isinstance(data, dict):
            return None
        payload = direction.to_dict()
        payload.pop("dna", None)
        for key, value in data.items():
            if key in payload and value:
                payload[key] = value
        payload["dna"] = direction.dna
        try:
            return ArtDirection(**payload)
        except TypeError:
            return None

    def check(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "ANTHROPIC_API_KEY not set (optional — pipeline runs without it)"
        try:
            text = self.complete('Reply with {"ok":true} and nothing else.', max_tokens=32)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return ("ok" in text.lower()), f"ok — model {self.model} responded"
