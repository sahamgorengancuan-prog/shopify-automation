"""Optional creative-director assist — OpenAI (GPT-5.1).

Every stage works without it: the LLM only *refines* what the deterministic
pipeline already produced, and any failure silently falls back. That keeps runs
reproducible offline and stops a missing key from breaking a scheduled job.

Transport: the Responses API first (what the GPT-5 family is built around), with
Chat Completions as the fallback so OpenAI-compatible gateways, Azure-style
proxies and older deployments keep working.
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import http
from .models import ArtDirection, Cluster, NicheLadder, Reference, VisualDNA

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-5.1"

# Models worth offering in the UI. The first entry is the default.
KNOWN_MODELS = ["gpt-5.1", "gpt-5.1-mini", "gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini"]

SYSTEM = (
    "You are an art director for an independent apparel label that publishes designs as if they "
    "were records from a fictional institution. You refine briefs; you never widen them. "
    "Reply with JSON only, no prose, no markdown fence."
)


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
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


def _text_from_responses(payload: dict) -> str:
    """Pull the assistant text out of a Responses API result.

    Reasoning models return a list of output items; only the message items carry
    text, and `output_text` is a convenience field some deployments add.
    """
    if isinstance(payload.get("output_text"), str) and payload["output_text"].strip():
        return payload["output_text"]

    chunks: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content", []) or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                chunks.append(str(part.get("text", "")))
    return "".join(chunks)


def _text_from_chat(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # some gateways return content parts
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content or "")


class LLM:
    """Thin OpenAI wrapper with graceful degradation."""

    def __init__(
        self,
        api_key: str = "",
        model: str = DEFAULT_MODEL,
        *,
        base_url: str = DEFAULT_BASE_URL,
        reasoning_effort: str = "low",
        timeout: int = 60,
        max_tokens: int = 2000,
        enabled: bool = True,
    ):
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.reasoning_effort = reasoning_effort
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.enabled = enabled
        self.last_error = ""
        # Learned at runtime so a deployment is only probed once per process.
        self._use_chat_api = False

    @property
    def available(self) -> bool:
        return bool(self.api_key) and self.enabled

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # -- transport --------------------------------------------------------
    def _responses(self, prompt: str, max_tokens: int, *, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": SYSTEM,
            "input": prompt,
            "max_output_tokens": max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning"] = {"effort": self.reasoning_effort}
        if json_mode:
            payload["text"] = {"format": {"type": "json_object"}}

        try:
            result = http.post_json(
                f"{self.base_url}/responses", payload, headers=self.headers,
                timeout=self.timeout, retries=2,
            )
        except http.HttpError as exc:
            # Drop the optional knobs an older model or gateway may reject, once.
            if exc.status == 400 and ("reasoning" in exc.body or "text.format" in exc.body or "format" in exc.body):
                payload.pop("reasoning", None)
                payload.pop("text", None)
                result = http.post_json(
                    f"{self.base_url}/responses", payload, headers=self.headers,
                    timeout=self.timeout, retries=1,
                )
            else:
                raise
        return _text_from_responses(result)

    def _chat(self, prompt: str, max_tokens: int, *, json_mode: bool) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            result = http.post_json(
                f"{self.base_url}/chat/completions", payload, headers=self.headers,
                timeout=self.timeout, retries=2,
            )
        except http.HttpError as exc:
            if exc.status == 400 and "max_completion_tokens" in exc.body:
                payload.pop("max_completion_tokens")
                payload["max_tokens"] = max_tokens
                result = http.post_json(
                    f"{self.base_url}/chat/completions", payload, headers=self.headers,
                    timeout=self.timeout, retries=1,
                )
            else:
                raise
        return _text_from_chat(result)

    def complete(self, prompt: str, *, max_tokens: int | None = None, json_mode: bool = True) -> str:
        budget = max_tokens or self.max_tokens
        if not self._use_chat_api:
            try:
                return self._responses(prompt, budget, json_mode=json_mode)
            except http.HttpError as exc:
                # 404/405 means this deployment has no Responses API — remember that.
                if exc.status not in (404, 405):
                    raise
                self._use_chat_api = True
        return self._chat(prompt, budget, json_mode=json_mode)

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

    # -- discovery --------------------------------------------------------
    def extract_topics(self, titles: list[str], *, limit: int = 12) -> list[str]:
        """Turn a pile of Reddit headlines into candidate *topics*.

        A headline is an event; a topic is the thing underneath it that could
        still be interesting in six months.
        """
        data = self._json_call(
            "These are hot Reddit post titles. Extract the underlying recurring topics — the "
            "objects, practices, places or subcultures behind them, never the news event, the "
            "person, or the brand. Skip anything about celebrities, politics, tragedy, sport "
            "fixtures or trademarked properties.\n"
            f"titles: {json.dumps(titles[:60], ensure_ascii=False)}\n"
            f'Reply as {{"topics":[str,...]}} with at most {limit} short noun phrases.'
        )
        if not isinstance(data, dict):
            return []
        return [str(topic).strip() for topic in data.get("topics", [])[:limit] if str(topic).strip()]

    def refine_seeds(self, terms: list[str]) -> dict[str, str]:
        """Rewrite raw search strings into topics a designer can work with.

        Returns ``{original: replacement}``; unchanged terms may be omitted.
        """
        data = self._json_call(
            "These are raw trending search strings. Rewrite each one as a short, concrete topic "
            "suitable for an apparel graphic: drop question words, filler and site names, keep "
            "the subject. If a string cannot become a design subject, map it to an empty string.\n"
            f"terms: {json.dumps(terms[:40], ensure_ascii=False)}\n"
            'Reply as {"terms":{"<original>":"<rewritten or empty>"}}'
        )
        if not isinstance(data, dict):
            return {}
        mapping = data.get("terms", {})
        if not isinstance(mapping, dict):
            return {}
        return {str(key): str(value).strip() for key, value in mapping.items() if str(value).strip()}

    def judge_topics(self, candidates: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Score wearability and propose an angle for each measured candidate.

        The model sees the measurements, so its judgement is about the *design*
        question the numbers cannot answer: does this make a shirt somebody wants,
        does it survive the season, and does printing it create a rights problem.
        """
        data = self._json_call(
            "You are choosing subjects for an independent apparel label that publishes designs as "
            "records from a fictional institution. For each candidate below decide whether it can "
            "become a graphic people would wear.\n"
            f"candidates: {json.dumps(candidates, ensure_ascii=False)}\n"
            'Reply as {"verdicts":[{"topic":str,"apparel_fit":0-10,"angle":str,"audience":str,'
            '"durability":"fad|seasonal|lasting","risk":str,"drop":bool,"reason":str}]}\n'
            "Set drop=true for anything that needs someone else's trademark, a real person's "
            "likeness, a live news event, or that has no visual world of its own. "
            "angle is one sentence describing the design direction, not a slogan."
        )
        if not isinstance(data, dict):
            return {}
        verdicts: dict[str, dict[str, Any]] = {}
        for row in data.get("verdicts", []):
            if isinstance(row, dict) and row.get("topic"):
                verdicts[str(row["topic"])] = row
        return verdicts

    def check(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "OPENAI_API_KEY not set (optional — pipeline runs without it)"
        try:
            text = self.complete('Reply with {"ok":true} and nothing else.', max_tokens=600)
        except http.HttpError as exc:
            if exc.status in (401, 403):
                return False, "key rejected (HTTP 401/403)"
            if exc.status == 404:
                return False, f"model '{self.model}' not available to this key"
            return False, str(exc)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        data = _extract_json(text)
        transport = "chat completions" if self._use_chat_api else "responses"
        if isinstance(data, dict) and data.get("ok"):
            return True, f"ok — {self.model} responded via the {transport} API"
        return bool(text.strip()), f"{self.model} responded ({transport} API): {text.strip()[:60]}"
