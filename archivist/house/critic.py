"""The visual critic — the only judge that looks at the actual pixels.

Everything else in the house system reasons about the brief. This sends the
garment mockup, the isolated artwork and an enlarged statement crop to a vision
model and asks whether the claim is *visible*. It is what caught the first paid
run: every deterministic gate passed, and the critic still scored
``subject_truth: 3`` because the mass read as generic rubble rather than the
named object.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .. import http
from ..llm import _extract_json, _text_from_responses
from .rules import ACCEPTANCE, CRITICAL_VISION_SCORES


class CriticUnavailable(RuntimeError):
    pass


def encode_image(path: Path | str, size: tuple[int, int] = (960, 960)) -> str:
    with Image.open(path) as source:
        preview = ImageOps.contain(source.convert("RGB"), size, Image.Resampling.LANCZOS)
        buffer = BytesIO()
        preview.save(buffer, format="JPEG", quality=90, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def instructions(route: dict[str, Any]) -> str:
    silhouette = (route.get("silhouette") or {}).get("label", "one nameable object")
    return (
        "You are the final skeptical buying committee for a premium independent apparel label. Judge only "
        "visible pixels. For every candidate you receive three proofs in order: garment mockup, isolated "
        "artwork, and enlarged statement crop. A brief is context, never evidence that a visual requirement "
        "passed. A rectangular canvas edge, watermark, stock-photo residue, generic diagram, centred layout, "
        "or unreadable statement is a hard commercial failure. Generic rubble, debris or an unnameable mass "
        "fails subject_truth even when the composition is strong.\n"
        f"Subject truth: {route['real_subject']} (silhouette must read as {silhouette}). "
        f"True property: {route['source_property']}. Mutation: {route['mutation']}. "
        f"Required visible statement: {route['statement']}.\n"
        "Score 0-10 for asymmetric_tension, thumbnail_read, subject_truth, artistic_mutation, "
        "brand_ownership, distinctiveness, wearability, statement_integration, print_feasibility, "
        f"artifact_control. Passed=true only when total >= {ACCEPTANCE['vision_total_min']:.0f} and "
        f"{', '.join(CRITICAL_VISION_SCORES)} are all >= {ACCEPTANCE['critical_vision_scores_min']:.0f}. "
        'Return strict JSON as {"candidates":[{"index":1,"scores":{},"total":0,"passed":false,"reason":"",'
        '"failure_class":"technical|local-edit|concept","repair_priority":"one specific correction"}]}'
    )


def review(candidates: list[dict[str, Any]], route: dict[str, Any], settings,
           *, required: bool = True, timeout: int = 150) -> dict[int, dict[str, Any]]:
    """Ask the vision model about each candidate. Returns {index: verdict}."""
    if not candidates:
        return {}
    if not settings.can_use_llm:
        if required:
            raise CriticUnavailable(
                "The visual critic is required but OPENAI_API_KEY is not set. Set the key, or run with "
                "the critic disabled to accept a candidate on deterministic proof alone."
            )
        return {}

    content: list[dict[str, Any]] = [{"type": "input_text", "text": instructions(route)}]
    for index, row in enumerate(candidates, 1):
        content.append({"type": "input_text", "text": f"Candidate {index}: garment mockup"})
        content.append({"type": "input_image", "image_url": encode_image(row["print_assets"]["mockup"])})
        content.append({"type": "input_text", "text": f"Candidate {index}: isolated artwork"})
        content.append({"type": "input_image", "image_url": encode_image(row["artwork_path"], (1024, 1024))})
        crop = (row.get("statement_spec") or {}).get("crop_path")
        if crop and Path(crop).is_file():
            content.append({"type": "input_text", "text": f"Candidate {index}: enlarged statement crop"})
            content.append({"type": "input_image", "image_url": encode_image(crop, (1200, 360))})

    payload = {
        "model": settings.openai_model,
        "instructions": (
            "Return strict JSON only. Penalise visible artifacts and genericness; never infer a pass "
            "from the written brief."
        ),
        "input": [{"role": "user", "content": content}],
        "max_output_tokens": 2600,
        "text": {"format": {"type": "json_object"}},
    }
    try:
        response = http.post_json(
            f"{settings.openai_base_url.rstrip('/')}/responses",
            payload,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
            retries=1,
        )
    except Exception as exc:
        if required:
            raise CriticUnavailable(f"The visual critic could not be reached: {type(exc).__name__}: {exc}") from exc
        return {}

    parsed = _extract_json(_text_from_responses(response))
    rows = parsed.get("candidates", []) if isinstance(parsed, dict) else []
    return {int(row.get("index", 0)): row for row in rows if isinstance(row, dict)}


def passed(verdict: dict[str, Any] | None) -> bool:
    """Strict reading of a verdict — a high total cannot carry a failed critical score."""
    if not verdict:
        return False
    scores = verdict.get("scores", {}) if isinstance(verdict, dict) else {}
    return (
        bool(verdict.get("passed"))
        and float(verdict.get("total", 0) or 0) >= ACCEPTANCE["vision_total_min"]
        and all(
            float(scores.get(name, 0) or 0) >= ACCEPTANCE["critical_vision_scores_min"]
            for name in CRITICAL_VISION_SCORES
        )
    )
