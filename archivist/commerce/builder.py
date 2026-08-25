"""Build the channel-neutral package consumed by every commerce adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..config import Settings
from ..llm import LLM
from .assets import build_storefront_assets
from .copywriter import build_listing_copy
from .errors import PackageBuildError
from .models import CommercePackage, CommerceVariant


def _json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except Exception:
        return {}


def _first(paths: list[Path]) -> Path | None:
    return next((p for p in paths if p.is_file()), None)


def _resolve(run_dir: Path, names: list[str]) -> Path | None:
    candidates: list[Path] = []
    for name in names:
        candidates.extend([run_dir / name, run_dir / "final" / name, run_dir / "FINAL" / name])
    p = _first(candidates)
    if p:
        return p
    for name in names:
        hits = list(run_dir.rglob(name))
        p = _first(hits)
        if p:
            return p
    return None


def _parse_variants(value: str | list[str] | tuple[str, ...], *, base_price: str, prefix: str) -> list[CommerceVariant]:
    if isinstance(value, str):
        pieces = [x.strip() for x in value.split(",") if x.strip()]
    else:
        pieces = [str(x).strip() for x in value if str(x).strip()]
    if not pieces:
        pieces = ["S", "M", "L", "XL"]
    out: list[CommerceVariant] = []
    for i, size in enumerate(pieces, 1):
        sku_size = "".join(c for c in size.upper() if c.isalnum())[:8] or str(i)
        out.append(CommerceVariant(sku=f"{prefix}-{sku_size}", size=size, price=base_price))
    return out


def _approval(run_dir: Path, route: dict[str, Any], truth: dict[str, Any]) -> tuple[bool, str]:
    """Did this run actually earn the right to become a listing?

    Read the run's own audit files rather than trusting a field on the route.
    Two things are easy to get wrong here and both end with an unproven design
    on sale: taking an *offline rehearsal* for market approval, and checking a
    key the pipeline does not write, which passes vacuously.
    """
    if not truth:
        return False, "the run carries no Market Truth verdict at all"
    if not truth.get("passed"):
        return False, (
            f"Market Truth did not pass ({truth.get('failure') or 'unknown'}): {truth.get('reason', '')}"
        )

    # An offline run never touched the network and never asked an auditor
    # anything. It is a rehearsal of the machinery, not evidence of a market.
    if str(truth.get("source", "")) == "offline-rehearsal":
        return False, (
            "this run was an offline rehearsal — no evidence was fetched and no auditor read "
            "anything, so it cannot become a live listing. Re-run online, or build a preview "
            "package with require_approved=False"
        )
    ranking = _json(run_dir / "candidate_ranking.json")
    if str(ranking.get("status", "")).startswith("offline-rehearsal"):
        return False, "the approved candidate is an offline rehearsal, not a market-approved design"

    # The pre-inference audit is where this pipeline records the gates that
    # stood between the route and a paid generation.
    audit = _json(run_dir / "preinference_audit.json")
    if audit:
        subject = audit.get("subject_audit") or {}
        director = audit.get("art_director_audit") or {}
        if not subject.get("passed", True):
            return False, f"the subject audit did not pass: {subject.get('reason', '')}"
        if not director.get("passed", True):
            return False, f"the authorship gate did not pass: {director.get('reason', '')}"
    elif (route.get("art_director_audit") or {}).get("failing"):
        return False, "the route records an art-director failure"

    return True, "market truth, subject and authorship gates all passed"


def build_commerce_package(
    run_dir: Path | str,
    settings: Settings | None = None,
    *,
    base_price: str | None = None,
    sizes: str | list[str] | tuple[str, ...] = ("S", "M", "L", "XL", "2XL"),
    brand: str | None = None,
    require_approved: bool = True,
    use_llm: bool = True,
) -> CommercePackage:
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise PackageBuildError(f"run directory does not exist: {run_dir}")
    settings = settings or Settings.from_env(run_dir)
    route = _json(run_dir / "creative_bridge.json")
    if not route:
        # Some callers point at final/ rather than its parent.
        route = _json(run_dir / "creative_bridge.json") or _json(run_dir.parent / "creative_bridge.json")
    truth = route.get("market_truth") or _json(run_dir / "market_truth.json")
    ref_audit = _json(run_dir / "reference_audit.json")

    approved, approval_reason = _approval(run_dir, route, truth)
    if require_approved and not approved:
        raise PackageBuildError(f"commerce publish package blocked: {approval_reason}")

    print_file = _resolve(run_dir, ["FINAL_print.png", "print.png", "print_ready.png"])
    artwork = _resolve(run_dir, ["FINAL_artwork.png", "artwork.png"])
    mockup = _resolve(run_dir, ["FINAL_mockup.png", "mockup.png"])
    missing = [name for name, path in (("print file", print_file), ("artwork", artwork), ("mockup", mockup)) if path is None]
    if missing:
        raise PackageBuildError("missing required approved asset(s): " + ", ".join(missing))

    topic = str(route.get("market_signal") or route.get("artistic_topic") or run_dir.name)
    digest = hashlib.sha256((str(run_dir) + topic + str(artwork.stat().st_size)).encode()).hexdigest()[:12]
    package_id = f"arc-{digest}"
    out_dir = run_dir / "commerce" / package_id
    out_dir.mkdir(parents=True, exist_ok=True)

    llm = LLM(
        settings.openai_api_key, model=settings.openai_model, base_url=settings.openai_base_url,
        reasoning_effort=settings.openai_reasoning_effort, enabled=bool(use_llm and settings.can_use_llm),
    )
    listing = build_listing_copy(topic, route, truth, llm=llm, brand=brand or settings.commerce_brand)
    storefront = build_storefront_assets(
        run_dir, out_dir / "gallery", package_id=package_id, topic=topic, route=route,
        mockup=mockup, artwork=artwork,
    )
    if not listing.alt_texts:
        listing.alt_texts = [asset.alt_text for asset in storefront.gallery]

    variants = _parse_variants(
        sizes, base_price=str(base_price or settings.commerce_base_price), prefix=package_id.upper().replace("ARC-", "ARC")
    )
    # A stable public staging copy is created for URL-only POD APIs such as Printful.
    # This directory is inert until the operator exposes it behind a configured HTTPS base URL.
    public_dir = out_dir / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    public_print = public_dir / f"{package_id}_approved_print.png"
    if not public_print.exists() or public_print.stat().st_size != print_file.stat().st_size:
        import shutil
        shutil.copy2(print_file, public_print)

    package = CommercePackage(
        id=package_id,
        source_run_dir=str(run_dir),
        topic=topic,
        collection=str(route.get("collection") or settings.collection),
        approved=approved,
        approval_reason=approval_reason,
        print_file=str(print_file),
        artwork_file=str(artwork),
        base_mockup=str(mockup),
        listing=listing,
        storefront=storefront,
        variants=variants,
        route=route,
        market_truth=truth,
        reference_audit=ref_audit,
        metadata={
            "commerce_schema": "10.2",
            "publish_default": "draft",
            "front_end_strategy": "platform-aware generated media order + unique featured collection tile",
            "public_print_stage": str(public_print),
        },
    )
    manifest = out_dir / "commerce_package.json"
    manifest.write_text(json.dumps(package.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    # Human-readable copy preview.
    (out_dir / "listing_preview.md").write_text(
        f"# {listing.title}\n\n{listing.description}\n\n## SEO\n\n**Title:** {listing.seo_title}\n\n"
        f"**Description:** {listing.seo_description}\n\n**Tags:** {', '.join(listing.tags)}\n",
        encoding="utf-8",
    )
    return package


def package_from_json(path: Path | str) -> CommercePackage:
    from .models import GalleryAsset, ListingCopy, StorefrontPlan
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    listing = ListingCopy(**data["listing"])
    storefront_data = data["storefront"]
    storefront = StorefrontPlan(
        signature=storefront_data["signature"],
        collection_tile=storefront_data["collection_tile"],
        gallery=[GalleryAsset(**row) for row in storefront_data.get("gallery", [])],
        palette=storefront_data.get("palette", []),
        composition_notes=storefront_data.get("composition_notes", []),
        reference_policy=storefront_data.get("reference_policy", "licensed-only"),
    )
    return CommercePackage(
        id=data["id"], source_run_dir=data["source_run_dir"], topic=data["topic"],
        collection=data.get("collection", "default"), approved=bool(data.get("approved")),
        approval_reason=data.get("approval_reason", ""), print_file=data["print_file"],
        artwork_file=data["artwork_file"], base_mockup=data["base_mockup"], listing=listing,
        storefront=storefront, variants=[CommerceVariant(**x) for x in data.get("variants", [])],
        route=data.get("route", {}), market_truth=data.get("market_truth", {}),
        reference_audit=data.get("reference_audit", {}), metadata=data.get("metadata", {}),
    )
