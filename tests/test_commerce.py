from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from archivist.config import Settings
from archivist.commerce.assets import SIGNATURES
from archivist.commerce.builder import build_commerce_package
from archivist.commerce.copywriter import ETSY_TAG_COUNT, ETSY_TAG_MAX, ETSY_TITLE_MAX, ETSY_TITLE_WORD_TARGET
from archivist.commerce.errors import PackageBuildError
from archivist.commerce.etsy import EtsyAdapter
from archivist.commerce.printful import PrintfulAdapter
from archivist.commerce.printify import PrintifyAdapter
from archivist.commerce.router import CommerceRouter
from archivist.commerce.shopify import ShopifyAdapter


def make_run(tmp_path: Path, *, passed=True) -> Path:
    route = {
        "market_signal": "railway switch stand",
        "collection": "switchgear",
        "real_subject": "railway switch stand",
        "source_property": "mechanical lever travel",
        "artistic_topic": "switch stand mechanics",
        "product_title": "Switch Stand Study",
        "metaphor": "lever travel becomes the composition axis",
        "mutation": "compress mechanical travel into one controlled offset",
        "market_truth": {
            "passed": passed,
            "status": "passed" if passed else "rejected",
            "dominant_intent": "railway switch stand hardware",
            "buyer_identity": "railway preservation enthusiasts",
            "why_they_care": "The switch stand is a recognisable operating object in railway infrastructure",
            "why_wear": "It signals a specific interest in railway operating hardware",
            "nameable_symbol": "railway switch stand",
        },
        "art_director_audit": {"failing": []},
    }
    (tmp_path / "creative_bridge.json").write_text(json.dumps(route), encoding="utf-8")
    (tmp_path / "reference_audit.json").write_text(json.dumps({"references": []}), encoding="utf-8")
    for name, bg in (("FINAL_print.png", "white"), ("FINAL_artwork.png", "black"), ("FINAL_mockup.png", "gray")):
        im = Image.new("RGB", (900, 1100), bg)
        d = ImageDraw.Draw(im)
        d.rectangle((180, 140, 720, 900), outline="red", width=25)
        d.line((160, 900, 760, 300), fill="blue", width=20)
        im.save(tmp_path / name)
    # An internal raw candidate should become process material, not a new design.
    Image.new("RGB", (600, 800), "navy").save(tmp_path / "B_paid_01_raw.png")
    return tmp_path


def settings() -> Settings:
    return Settings(offline=True, commerce_brand="ARCHIVIST", commerce_base_price="37.00")


def test_package_requires_approval(tmp_path: Path):
    run = make_run(tmp_path, passed=False)
    with pytest.raises(PackageBuildError):
        build_commerce_package(run, settings(), use_llm=False)


def test_package_builds_platform_gallery_and_safe_copy(tmp_path: Path):
    run = make_run(tmp_path)
    p = build_commerce_package(run, settings(), use_llm=False)
    assert p.approved
    assert p.storefront.signature in SIGNATURES
    assert len(p.storefront.gallery) >= 5
    roles = {a.role for a in p.storefront.gallery}
    assert {"collection_tile", "garment_hero", "garment_perspective", "artwork_detail", "process_study"} <= roles
    assert all(Path(a.path).is_file() for a in p.storefront.gallery)
    assert len(p.listing.title) <= ETSY_TITLE_MAX
    assert len(p.listing.title.split()) <= ETSY_TITLE_WORD_TARGET
    assert len(p.listing.tags) <= ETSY_TAG_COUNT
    assert all(len(t) <= ETSY_TAG_MAX for t in p.listing.tags)
    assert "AI disclosure:" in p.listing.description
    assert "Production:" in p.listing.description
    assert Path(p.metadata["public_print_stage"]).is_file()


def test_research_reference_not_republished_without_explicit_manifest(tmp_path: Path):
    run = make_run(tmp_path)
    Image.new("RGB", (500, 500), "green").save(run / "reference_nearest.jpg")
    p = build_commerce_package(run, settings(), use_llm=False)
    assert all(a.role != "licensed_reference" for a in p.storefront.gallery)


def test_explicit_commerce_safe_reference_is_carded(tmp_path: Path):
    run = make_run(tmp_path)
    ref = run / "owned_ref.jpg"
    Image.new("RGB", (500, 500), "green").save(ref)
    (run / "commerce_reference_manifest.json").write_text(json.dumps({"assets": [{"path": ref.name, "commerce_safe": True}]}), encoding="utf-8")
    p = build_commerce_package(run, settings(), use_llm=False)
    assert any(a.role == "licensed_reference" for a in p.storefront.gallery)


def test_adapter_payloads_are_channel_specific(tmp_path: Path):
    p = build_commerce_package(make_run(tmp_path), settings(), use_llm=False)
    s = settings()
    s.etsy_taxonomy_id = "123"; s.etsy_shipping_profile_id = "456"; s.etsy_readiness_state_id = "789"
    s.printify_blueprint_id = "12"; s.printify_provider_id = "34"; s.printify_variant_ids = "101,102"
    s.printful_variant_ids = "4011,4012"
    etsy = EtsyAdapter(s).payload(p)
    assert etsy["state"] == "draft" and etsy["title"] == p.listing.title
    shopify = ShopifyAdapter(s).product_input(p)
    assert shopify["seo"]["title"] == p.listing.seo_title
    assert any(m["key"] == "layout_signature" for m in shopify["metafields"])
    printify = PrintifyAdapter(s).payload(p)
    assert printify["blueprint_id"] == 12 and len(printify["variants"]) == 2
    printful = PrintfulAdapter(s).payload(p)
    assert len(printful["sync_variants"]) == 2


def test_router_all_optional_dry_run(tmp_path: Path):
    p = build_commerce_package(make_run(tmp_path), settings(), use_llm=False)
    receipt = CommerceRouter(settings()).publish(p, channels=["etsy", "shopify"], fulfillment="printify", dry_run=True)
    assert receipt.ok
    assert [r.platform for r in receipt.results] == ["etsy", "shopify", "printify"]


def test_router_can_do_no_channel_no_pod(tmp_path: Path):
    p = build_commerce_package(make_run(tmp_path), settings(), use_llm=False)
    receipt = CommerceRouter(settings()).publish(p, channels=[], fulfillment="none", dry_run=True)
    assert receipt.results == []
    assert not receipt.ok


def test_secret_redaction_includes_commerce_tokens():
    s = settings()
    s.etsy_access_token = "secret"; s.shopify_access_token = "secret"; s.printful_token = "secret"; s.printify_token = "secret"
    redacted = s.redacted()
    for key in ("etsy_access_token", "shopify_access_token", "printful_token", "printify_token"):
        assert redacted[key] == "set"


def test_shopify_theme_addon_has_collection_and_product_sections():
    root = Path(__file__).resolve().parents[1] / "integrations" / "shopify_theme"
    collage = (root / "archivist-collage-grid.liquid").read_text(encoding="utf-8")
    product = (root / "archivist-product-editorial.liquid").read_text(encoding="utf-8")
    assert "archivist.layout_signature" in collage
    assert "archivist.layout_signature" in product
    assert "form 'product'" in product
    assert "arc-product--editorial-overlap" in product


def test_shopify_description_is_html_escaped(tmp_path: Path):
    pck = build_commerce_package(make_run(tmp_path), settings(), use_llm=False)
    pck.listing.description = "A <mechanical> study & garment"
    html = ShopifyAdapter(settings()).product_input(pck)["descriptionHtml"]
    assert "&lt;mechanical&gt;" in html and "&amp;" in html
    assert "<mechanical>" not in html


# --- the boundary between a rehearsal and a listing ----------------------
def _audit(run: Path, *, subject=True, director=True) -> None:
    (run / "preinference_audit.json").write_text(json.dumps({
        "live_generation": True,
        "subject_audit": {"passed": subject, "reason": "" if subject else "generic mass"},
        "art_director_audit": {"passed": director, "reason": "" if director else "arbitrary waves"},
    }), encoding="utf-8")


def test_an_offline_rehearsal_cannot_become_a_live_listing(tmp_path):
    """Offline fetched nothing and asked nobody. It is not market approval."""
    run = make_run(tmp_path)
    route = json.loads((run / "creative_bridge.json").read_text(encoding="utf-8"))
    route["market_truth"]["source"] = "offline-rehearsal"
    (run / "creative_bridge.json").write_text(json.dumps(route), encoding="utf-8")

    with pytest.raises(PackageBuildError) as raised:
        build_commerce_package(run, require_approved=True, use_llm=False)
    assert "offline rehearsal" in str(raised.value)

    # It may still be built for inspection — and is marked unapproved.
    package = build_commerce_package(run, require_approved=False, use_llm=False)
    assert package.approved is False
    assert "offline rehearsal" in package.approval_reason


def test_a_rehearsal_ranking_is_caught_even_if_the_verdict_looks_clean(tmp_path):
    run = make_run(tmp_path)
    (run / "candidate_ranking.json").write_text(
        json.dumps({"status": "offline-rehearsal-approved"}), encoding="utf-8")
    with pytest.raises(PackageBuildError):
        build_commerce_package(run, require_approved=True, use_llm=False)


@pytest.mark.parametrize("failing_gate", ["subject", "director"])
def test_a_failed_pre_inference_gate_blocks_the_package(tmp_path, failing_gate):
    """The gates are read from the run's own audit, not from a field on the route."""
    run = make_run(tmp_path)
    _audit(run, subject=failing_gate != "subject", director=failing_gate != "director")

    with pytest.raises(PackageBuildError) as raised:
        build_commerce_package(run, require_approved=True, use_llm=False)
    assert ("subject audit" if failing_gate == "subject" else "authorship gate") in str(raised.value)


def test_a_passed_run_with_a_full_audit_builds_and_says_why(tmp_path):
    run = make_run(tmp_path)
    _audit(run)
    package = build_commerce_package(run, require_approved=True, use_llm=False)
    assert package.approved
    assert "market truth, subject and authorship" in package.approval_reason


def test_publishing_an_unapproved_package_live_is_refused(tmp_path):
    """A preview may be dry-run all day. It may not reach a buyer."""
    from archivist.commerce.errors import CommerceError

    run = make_run(tmp_path, passed=False)
    package = build_commerce_package(run, require_approved=False, use_llm=False)
    assert not package.approved

    router = CommerceRouter(Settings.from_env(tmp_path))
    dry = router.publish(package, channels=["etsy"], dry_run=True)
    assert dry.results, "a dry run of a preview is exactly what previews are for"

    with pytest.raises(CommerceError) as raised:
        router.publish(package, channels=["etsy"], dry_run=False)
    assert "unapproved package" in str(raised.value)
