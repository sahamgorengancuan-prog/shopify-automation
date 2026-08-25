"""Evidence-grounded commerce copy for Etsy/Shopify/POD channels.

Copy is derived from Market Truth and the approved route.  The LLM may polish
language, but it is not allowed to invent a buyer, provenance, historical
claim, scarcity claim or product property.  A deterministic fallback keeps
commerce preparation usable with no OpenAI key.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from .models import ListingCopy

ETSY_TITLE_MAX = 140
ETSY_TAG_MAX = 20
ETSY_TAG_COUNT = 13
SHOPIFY_SEO_TITLE_MAX = 70
SHOPIFY_SEO_DESCRIPTION_MAX = 160
ETSY_TITLE_WORD_TARGET = 15

_STOP = {
    "the", "and", "for", "with", "from", "that", "this", "shirt", "tshirt",
    "t-shirt", "graphic", "design", "art", "apparel", "wear", "wearing",
}


def slugify(text: str) -> str:
    raw = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    raw = re.sub(r"[^a-zA-Z0-9]+", "-", raw.lower()).strip("-")
    return raw[:80] or "archivist-piece"


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _keywords(topic: str, route: dict[str, Any], truth: dict[str, Any]) -> list[str]:
    seeds = [
        topic,
        truth.get("dominant_intent"),
        truth.get("buyer_identity"),
        truth.get("nameable_symbol"),
        truth.get("safe_visual_territory"),
        route.get("real_subject"),
        route.get("source_property"),
        route.get("artistic_topic"),
        route.get("product_title"),
    ]
    out: list[str] = []
    seen: set[str] = set()
    for seed in seeds:
        words = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9'&/-]*", _clean(seed)) if w.lower() not in _STOP]
        phrase = " ".join(words[:4]).strip(" -/")
        for candidate in (phrase, *words):
            key = candidate.lower()
            if len(candidate) < 3 or key in seen:
                continue
            seen.add(key)
            out.append(candidate)
    return out[:24]


def _etsy_tags(keywords: list[str], subject: str) -> list[str]:
    candidates = [subject, *keywords, "artist made tee", "editorial t shirt", "graphic t shirt"]
    tags: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        raw = _clean(raw).lower().replace("t-shirt", "t shirt")
        raw = re.sub(r"[^a-z0-9 &'/-]", "", raw).strip()
        if not raw:
            continue
        # Etsy tags are deliberately short. Truncate on word boundaries.
        if len(raw) > ETSY_TAG_MAX:
            words: list[str] = []
            for word in raw.split():
                next_value = " ".join([*words, word])
                if len(next_value) > ETSY_TAG_MAX:
                    break
                words.append(word)
            raw = " ".join(words)
        key = raw.strip()
        if len(key) < 2 or key in seen:
            continue
        seen.add(key)
        tags.append(key)
        if len(tags) >= ETSY_TAG_COUNT:
            break
    return tags


def _fallback(topic: str, route: dict[str, Any], truth: dict[str, Any], *, brand: str) -> ListingCopy:
    subject = _clean(truth.get("nameable_symbol") or route.get("real_subject") or topic)
    property_ = _clean(route.get("source_property"))
    title_seed = _clean(route.get("product_title")) or f"{subject} Study"
    title = title_seed
    if "shirt" not in title.lower() and "tee" not in title.lower():
        title = f"{title} — Graphic T-Shirt"
    # Etsy's 2026 seller guidance favors short, scannable titles (roughly <15 words)
    # and a holistic listing instead of keyword-stuffed titles. Keep the hard API
    # character limit too, but optimize for humans first.
    words = title.split()
    if len(words) > ETSY_TITLE_WORD_TARGET:
        title = " ".join(words[:ETSY_TITLE_WORD_TARGET])
    title = title[:ETSY_TITLE_MAX].rstrip(" -—,/")

    why_care = _clean(truth.get("why_they_care"))
    why_wear = _clean(truth.get("why_wear"))
    visual = _clean(route.get("metaphor") or route.get("mutation"))
    body: list[str] = [
        f"An original {brand} graphic built around {subject}.",
    ]
    if property_:
        body.append(f"The composition studies {property_.lower()} as a physical design constraint rather than decorative texture.")
    if visual:
        body.append(f"Art direction: {visual.rstrip('.') }.")
    if why_care:
        body.append(why_care.rstrip(".") + ".")
    if why_wear:
        body.append(why_wear.rstrip(".") + ".")
    body.extend([
        "The artwork is intentionally composed for the garment: negative space, scale and placement are part of the piece and should not be auto-centered.",
        "Garment, printing and fulfilment specifications follow the production profile selected for the live listing; this copy does not invent material or production claims.",
    ])
    ai_disclosure = "AI-assisted image generation was used as one step in an original seller-directed design process; research, selection, composition and print preparation are curated by the seller."
    production = "If a production partner is used for this listing, the configured partner fulfils the seller's original design and must be disclosed on the sales channel."
    description = "\n\n".join(body + [f"AI disclosure: {ai_disclosure}", f"Production: {production}"])

    keywords = _keywords(topic, route, truth)
    tags = _etsy_tags(keywords, subject)
    seo_title = title_seed[:SHOPIFY_SEO_TITLE_MAX].rstrip(" -—,/")
    seo_description = _clean(f"Original {subject} graphic by {brand}. {property_ or why_care}")[:SHOPIFY_SEO_DESCRIPTION_MAX].rstrip()
    return ListingCopy(
        title=title,
        description=description,
        seo_title=seo_title,
        seo_description=seo_description,
        tags=tags,
        materials=[],
        alt_texts=[],
        handle=slugify(title_seed),
        vendor=brand,
        ai_disclosure=ai_disclosure,
        production_disclosure=production,
        evidence_keywords=keywords,
    )


def build_listing_copy(
    topic: str,
    route: dict[str, Any],
    truth: dict[str, Any],
    *,
    llm=None,
    brand: str = "ARCHIVIST",
) -> ListingCopy:
    """Return restrained marketplace copy.  Facts remain bound to route/truth."""
    base = _fallback(topic, route, truth, brand=brand)
    if llm is None or not getattr(llm, "available", False):
        return base

    allowed = {
        "topic": topic,
        "subject": truth.get("nameable_symbol") or route.get("real_subject"),
        "physical_property": route.get("source_property"),
        "why_care": truth.get("why_they_care"),
        "why_wear": truth.get("why_wear"),
        "dominant_intent": truth.get("dominant_intent"),
        "visual_idea": route.get("metaphor") or route.get("mutation"),
        "brand": brand,
        "fallback": base.to_dict(),
    }
    data = llm._json_call(
        "You are an editorial ecommerce copy editor. Rewrite only from ALLOWED FACTS below. "
        "Never invent heritage, dates, locations, materials, scarcity, sustainability claims, buyers, subcultures, "
        "product specifications or cultural meanings. No fake poetry, no hype, no 'must-have', no keyword stuffing. "
        "The voice is concise, classy, specific and visually literate. The title must name the recognisable subject. "
        "Keep the Etsy title clear and buyer-readable, ideally under 15 words and always <=140 characters; "
        "front-load what the object actually is, not keyword chains. SEO title <=70; SEO description <=160; "
        "max 13 tags and every tag <=20 characters. "
        "The description must preserve explicit AI-assisted-design and production-partner disclosures from fallback. "
        f"ALLOWED FACTS:\n{json.dumps(allowed, ensure_ascii=False, default=str)}\n"
        'Reply JSON only: {"title":str,"description":str,"seo_title":str,"seo_description":str,"tags":[str,...],"alt_texts":[str,...]}'
    )
    if not isinstance(data, dict):
        return base

    title = _clean(data.get("title"))[:ETSY_TITLE_MAX].rstrip(" -—,/") or base.title
    if len(title.split()) > ETSY_TITLE_WORD_TARGET:
        title = " ".join(title.split()[:ETSY_TITLE_WORD_TARGET]).rstrip(" -—,/")
    seo_title = _clean(data.get("seo_title"))[:SHOPIFY_SEO_TITLE_MAX].rstrip(" -—,/") or base.seo_title
    seo_description = _clean(data.get("seo_description"))[:SHOPIFY_SEO_DESCRIPTION_MAX].rstrip() or base.seo_description
    description = str(data.get("description") or base.description).strip()
    # Always force the legal/marketplace-facing disclosures even if the LLM omitted them.
    if base.ai_disclosure.lower() not in description.lower():
        description += f"\n\nAI disclosure: {base.ai_disclosure}"
    if base.production_disclosure.lower() not in description.lower():
        description += f"\n\nProduction: {base.production_disclosure}"

    tags = _etsy_tags([str(x) for x in data.get("tags", []) if x], _clean(truth.get("nameable_symbol") or route.get("real_subject") or topic))
    if not tags:
        tags = base.tags
    return ListingCopy(
        title=title,
        description=description,
        seo_title=seo_title,
        seo_description=seo_description,
        tags=tags,
        materials=base.materials,
        alt_texts=[_clean(x)[:250] for x in data.get("alt_texts", []) if _clean(x)][:10],
        handle=slugify(seo_title or title),
        product_type=base.product_type,
        vendor=base.vendor,
        ai_disclosure=base.ai_disclosure,
        production_disclosure=base.production_disclosure,
        evidence_keywords=base.evidence_keywords,
    )
