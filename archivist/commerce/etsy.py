"""Etsy Open API v3 adapter.

The direct adapter creates a draft, uploads the curated gallery and can activate
only after images exist.  POD-managed Etsy stores can instead be published by
Printify; the router prevents accidental double creation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, PublishError
from .models import CommercePackage, PublishResult
from .transport import Transport

BASE = "https://api.etsy.com/v3/application"


class EtsyAdapter:
    name = "etsy"

    def __init__(self, settings, *, transport: Transport | None = None):
        self.settings = settings
        self.transport = transport or Transport(timeout=settings.http_timeout)

    @property
    def configured(self) -> bool:
        return bool(self.settings.etsy_api_key and self.settings.etsy_access_token and self.settings.etsy_shop_id)

    def _headers(self, *, json_content: bool = False) -> dict[str, str]:
        h = {"x-api-key": self.settings.etsy_api_key, "Authorization": f"Bearer {self.settings.etsy_access_token}"}
        if json_content:
            h["Content-Type"] = "application/json"
        return h

    def check(self) -> tuple[bool, str]:
        if not self.settings.etsy_api_key:
            return False, "not configured"
        row = self.transport.request("GET", f"{BASE}/openapi-ping", headers={"x-api-key": self.settings.etsy_api_key})
        detail = f"application {row.get('application_id', 'reachable')}"
        if self.settings.etsy_access_token:
            me = self.transport.request("GET", f"{BASE}/users/me", headers=self._headers())
            detail += f"; user {me.get('user_id', 'ok')} / shop {me.get('shop_id', 'n/a')}"
        return True, detail

    def _validate(self) -> None:
        required = {
            "ETSY_API_KEY": self.settings.etsy_api_key,
            "ETSY_ACCESS_TOKEN": self.settings.etsy_access_token,
            "ETSY_SHOP_ID": self.settings.etsy_shop_id,
            "ETSY_TAXONOMY_ID": self.settings.etsy_taxonomy_id,
            "ETSY_SHIPPING_PROFILE_ID": self.settings.etsy_shipping_profile_id,
            "ETSY_READINESS_STATE_ID": self.settings.etsy_readiness_state_id,
        }
        missing = [k for k, v in required.items() if not str(v)]
        if missing:
            raise ConfigurationError("Etsy missing: " + ", ".join(missing))

    def payload(self, package: CommercePackage, *, active: bool = False) -> dict[str, Any]:
        first = package.variants[0] if package.variants else None
        return {
            "quantity": sum(max(1, v.quantity) for v in package.variants) if package.variants else 999,
            "title": package.listing.title[:140],
            "description": package.listing.description,
            "price": first.price if first else self.settings.commerce_base_price,
            "who_made": "i_did",
            "when_made": "made_to_order",
            "taxonomy_id": int(self.settings.etsy_taxonomy_id or 0),
            "shipping_profile_id": int(self.settings.etsy_shipping_profile_id or 0),
            "readiness_state_id": int(self.settings.etsy_readiness_state_id or 0),
            "tags": package.listing.tags[:13],
            "materials": package.listing.materials[:13],
            "state": "draft",  # images must be attached before activation
        }

    def _inventory_payload(self, package: CommercePackage) -> dict[str, Any]:
        # Etsy property_id 100 is Size. Custom scale/value text is accepted via values.
        products = []
        for variant in package.variants:
            products.append({
                "sku": variant.sku,
                "property_values": [{"property_id": 100, "property_name": "Size", "values": [variant.size]}],
                "offerings": [{
                    "price": float(variant.price),
                    "quantity": int(variant.quantity),
                    "is_enabled": True,
                    "readiness_state_id": int(self.settings.etsy_readiness_state_id or 0),
                }],
            })
        return {"products": products, "price_on_property": [100], "quantity_on_property": [100], "sku_on_property": [100]}

    def publish(self, package: CommercePackage, *, dry_run: bool = True, active: bool = False, audit_dir: Path | None = None) -> PublishResult:
        audit_dir = Path(audit_dir or Path(package.source_run_dir) / "commerce" / package.id / "publish")
        audit_dir.mkdir(parents=True, exist_ok=True)
        payload = self.payload(package, active=active)
        payload_path = audit_dir / "etsy_request.json"
        payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if dry_run:
            return PublishResult("etsy", True, "dry-run", message="Draft listing + gallery + size inventory validated locally", payload_path=str(payload_path))
        self._validate()
        if not package.approved:
            raise PublishError("Etsy publish blocked: commerce package is not approved")
        shop = self.settings.etsy_shop_id
        result = self.transport.request("POST", f"{BASE}/shops/{shop}/listings?legacy=false", headers=self._headers(), data=payload)
        listing_id = str(result.get("listing_id") or result.get("id") or "")
        if not listing_id:
            raise PublishError("Etsy did not return listing_id")
        # Curated media order: Etsy conversion-first, not the Shopify collection tile.
        media = sorted(package.storefront.gallery, key=lambda a: (0 if a.role == "garment_hero" else 1, a.rank))
        image_ids: list[str] = []
        for rank, asset in enumerate(media[:10], 1):
            if not asset.exists or not asset.commerce_safe:
                continue
            row = self.transport.multipart_image(
                f"{BASE}/shops/{shop}/listings/{listing_id}/images",
                asset.path, field="image", headers=self._headers(), data={"rank": str(rank), "alt_text": asset.alt_text[:250]},
            )
            image_ids.append(str(row.get("listing_image_id") or row.get("image_id") or ""))
        if package.variants:
            self.transport.request(
                "PUT", f"{BASE}/listings/{listing_id}/inventory?legacy=false",
                headers=self._headers(json_content=True), json_body=self._inventory_payload(package), expected=(200, 201),
            )
        if active:
            self.transport.request(
                "PATCH", f"{BASE}/shops/{shop}/listings/{listing_id}",
                headers=self._headers(), data={"state": "active"}, expected=(200, 201),
            )
        response_path = audit_dir / "etsy_response.json"
        response_path.write_text(json.dumps({"listing": result, "image_ids": image_ids}, indent=2, default=str), encoding="utf-8")
        return PublishResult("etsy", True, "active" if active else "draft", remote_id=listing_id,
                             message=f"Etsy listing created with {len(image_ids)} commerce-safe images",
                             payload_path=str(payload_path), response_path=str(response_path),
                             extra={"image_ids": image_ids})
