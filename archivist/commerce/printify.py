"""Printify product/fulfilment adapter."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, PublishError
from .models import CommercePackage, PublishResult
from .transport import Transport

BASE = "https://api.printify.com/v1"


class PrintifyAdapter:
    name = "printify"

    def __init__(self, settings, *, transport: Transport | None = None):
        self.settings = settings
        self.transport = transport or Transport(timeout=settings.http_timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.printify_token}", "Content-Type": "application/json"}

    def check(self) -> tuple[bool, str]:
        if not self.settings.printify_token:
            return False, "not configured"
        shops = self.transport.request("GET", f"{BASE}/shops.json", headers=self._headers())
        if not isinstance(shops, list):
            return False, "unexpected shops response"
        return True, f"{len(shops)} shop(s): " + ", ".join(str(x.get("sales_channel") or x.get("title") or x.get("id")) for x in shops[:4])

    def shop_id(self, channel: str = "") -> str:
        if channel == "etsy" and self.settings.printify_shop_etsy_id:
            return self.settings.printify_shop_etsy_id
        if channel == "shopify" and self.settings.printify_shop_shopify_id:
            return self.settings.printify_shop_shopify_id
        return self.settings.printify_shop_id

    def _validate(self, channel: str = "") -> None:
        fields = {
            "PRINTIFY_TOKEN": self.settings.printify_token,
            "PRINTIFY_SHOP_ID / channel shop id": self.shop_id(channel),
            "PRINTIFY_BLUEPRINT_ID": self.settings.printify_blueprint_id,
            "PRINTIFY_PROVIDER_ID": self.settings.printify_provider_id,
            "PRINTIFY_VARIANT_IDS": self.settings.printify_variant_ids,
        }
        missing = [k for k, v in fields.items() if not str(v)]
        if missing:
            raise ConfigurationError("Printify missing: " + ", ".join(missing))

    def _variant_ids(self) -> list[int]:
        return [int(x.strip()) for x in str(self.settings.printify_variant_ids).split(",") if x.strip().isdigit()]

    def _upload(self, path: Path) -> str:
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        row = self.transport.request(
            "POST", f"{BASE}/uploads/images.json", headers=self._headers(),
            json_body={"file_name": path.name, "contents": encoded},
        )
        image_id = str(row.get("id") or "")
        if not image_id:
            raise PublishError("Printify image upload returned no id")
        return image_id

    def payload(self, package: CommercePackage, *, image_id: str = "DRY_RUN_IMAGE") -> dict[str, Any]:
        ids = self._variant_ids() or [1]
        price_cents = int(round(float(package.variants[0].price if package.variants else self.settings.commerce_base_price) * 100))
        variants = [{"id": vid, "price": price_cents, "is_enabled": True} for vid in ids]
        return {
            "title": package.listing.title,
            "description": package.listing.description,
            "blueprint_id": int(self.settings.printify_blueprint_id or 0),
            "print_provider_id": int(self.settings.printify_provider_id or 0),
            "variants": variants,
            "print_areas": [{
                "variant_ids": ids,
                "placeholders": [{
                    "position": self.settings.printify_print_position,
                    "images": [{"id": image_id, "x": 0.5, "y": 0.5, "scale": float(self.settings.printify_scale), "angle": 0}],
                }],
            }],
        }

    def publish(self, package: CommercePackage, *, channel: str = "", dry_run: bool = True, publish_to_connected_channel: bool = False, audit_dir: Path | None = None) -> PublishResult:
        audit_dir = Path(audit_dir or Path(package.source_run_dir) / "commerce" / package.id / "publish")
        audit_dir.mkdir(parents=True, exist_ok=True)
        payload = self.payload(package)
        payload_path = audit_dir / f"printify_{channel or 'manual'}_request.json"
        payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if dry_run:
            return PublishResult("printify", True, "dry-run", message=f"Printify product prepared for {channel or 'manual/API'} shop", payload_path=str(payload_path))
        self._validate(channel)
        if not package.approved:
            raise PublishError("Printify publish blocked: package is not approved")
        image_id = self._upload(Path(package.print_file))
        payload = self.payload(package, image_id=image_id)
        shop = self.shop_id(channel)
        row = self.transport.request("POST", f"{BASE}/shops/{shop}/products.json", headers=self._headers(), json_body=payload)
        product_id = str(row.get("id") or "")
        if not product_id:
            raise PublishError("Printify create product returned no id")
        if publish_to_connected_channel:
            publish_payload = {"title": True, "description": True, "images": True, "variants": True, "tags": True, "keyFeatures": True, "shipping_template": channel == "etsy"}
            self.transport.request("POST", f"{BASE}/shops/{shop}/products/{product_id}/publish.json", headers=self._headers(), json_body=publish_payload, expected=(200, 201, 202))
        response_path = audit_dir / f"printify_{channel or 'manual'}_response.json"
        response_path.write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")
        return PublishResult("printify", True, "published-to-channel" if publish_to_connected_channel else "product-created",
                             remote_id=product_id, message="Printify product created; artwork uploaded to Media Library",
                             payload_path=str(payload_path), response_path=str(response_path), extra={"channel": channel, "image_id": image_id})
