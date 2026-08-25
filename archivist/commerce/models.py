"""Commerce-domain models.

The design engine never talks directly to a sales channel.  It produces a
``CommercePackage`` which can be rendered differently for Etsy, Shopify,
Printful and Printify without contaminating the creative pipeline with API
quirks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CommerceVariant:
    sku: str
    size: str = ""
    color: str = ""
    price: str = "34.00"
    currency: str = "USD"
    quantity: int = 999
    external_variant_id: str = ""
    printful_variant_id: int | None = None
    printify_variant_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ListingCopy:
    title: str
    description: str
    seo_title: str
    seo_description: str
    tags: list[str] = field(default_factory=list)
    materials: list[str] = field(default_factory=list)
    alt_texts: list[str] = field(default_factory=list)
    handle: str = ""
    product_type: str = "Graphic T-Shirt"
    vendor: str = "ARCHIVIST"
    ai_disclosure: str = ""
    production_disclosure: str = ""
    evidence_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GalleryAsset:
    path: str
    role: str
    rank: int
    alt_text: str = ""
    source_kind: str = "owned"
    commerce_safe: bool = True
    platform_hint: str = ""

    @property
    def exists(self) -> bool:
        return bool(self.path and Path(self.path).is_file())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StorefrontPlan:
    signature: str
    collection_tile: str
    gallery: list[GalleryAsset]
    palette: list[str] = field(default_factory=list)
    composition_notes: list[str] = field(default_factory=list)
    reference_policy: str = "licensed-only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature,
            "collection_tile": self.collection_tile,
            "gallery": [asset.to_dict() for asset in self.gallery],
            "palette": self.palette,
            "composition_notes": self.composition_notes,
            "reference_policy": self.reference_policy,
        }


@dataclass
class CommercePackage:
    id: str
    source_run_dir: str
    topic: str
    collection: str
    approved: bool
    approval_reason: str
    print_file: str
    artwork_file: str
    base_mockup: str
    listing: ListingCopy
    storefront: StorefrontPlan
    variants: list[CommerceVariant]
    route: dict[str, Any] = field(default_factory=dict)
    market_truth: dict[str, Any] = field(default_factory=dict)
    reference_audit: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_run_dir": self.source_run_dir,
            "topic": self.topic,
            "collection": self.collection,
            "approved": self.approved,
            "approval_reason": self.approval_reason,
            "print_file": self.print_file,
            "artwork_file": self.artwork_file,
            "base_mockup": self.base_mockup,
            "listing": self.listing.to_dict(),
            "storefront": self.storefront.to_dict(),
            "variants": [variant.to_dict() for variant in self.variants],
            "route": self.route,
            "market_truth": self.market_truth,
            "reference_audit": self.reference_audit,
            "metadata": self.metadata,
        }


@dataclass
class PublishResult:
    platform: str
    ok: bool
    status: str
    remote_id: str = ""
    remote_url: str = ""
    message: str = ""
    payload_path: str = ""
    response_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommerceReceipt:
    package_id: str
    dry_run: bool
    channels: list[str]
    fulfillment: str
    results: list[PublishResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(result.ok for result in self.results)

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "dry_run": self.dry_run,
            "channels": self.channels,
            "fulfillment": self.fulfillment,
            "results": [result.to_dict() for result in self.results],
            "warnings": self.warnings,
            "ok": self.ok,
        }
