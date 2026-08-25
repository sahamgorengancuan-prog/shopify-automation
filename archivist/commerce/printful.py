"""Printful Manual/API-store and external-sync adapter.

Printful's file objects are URL based, so a live run requires the approved print
asset to be reachable at ARCHIVIST_PUBLIC_ASSET_BASE_URL (or a custom signed URL
supplied by the caller).  Dry-run remains fully local.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote
from typing import Any

from .errors import ConfigurationError, PublishError
from .models import CommercePackage, PublishResult
from .transport import Transport

BASE = "https://api.printful.com"


class PrintfulAdapter:
    name = "printful"

    def __init__(self, settings, *, transport: Transport | None = None):
        self.settings = settings
        self.transport = transport or Transport(timeout=settings.http_timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.settings.printful_token}", "Content-Type": "application/json"}

    def check(self) -> tuple[bool, str]:
        if not self.settings.printful_token:
            return False, "not configured"
        row = self.transport.request("GET", f"{BASE}/stores", headers=self._headers())
        stores = row.get("result") if isinstance(row, dict) else None
        if not isinstance(stores, list):
            return False, "unexpected stores response"
        return True, f"{len(stores)} store(s): " + ", ".join(str(x.get("name") or x.get("id")) for x in stores[:4])

    def public_url(self, local_path: str) -> str:
        base = self.settings.public_asset_base_url.rstrip("/")
        if not base:
            return ""
        staged = Path(local_path)
        # The builder stores a collision-safe public copy in commerce/<id>/public.
        # The configured base URL should point at that directory (or an equivalent CDN prefix).
        return f"{base}/{quote(staged.name)}"

    def _validate(self) -> None:
        missing = []
        if not self.settings.printful_token: missing.append("PRINTFUL_TOKEN")
        if not self.settings.public_asset_base_url: missing.append("ARCHIVIST_PUBLIC_ASSET_BASE_URL")
        if not self.settings.printful_variant_ids: missing.append("PRINTFUL_VARIANT_IDS")
        if missing:
            raise ConfigurationError("Printful missing: " + ", ".join(missing))

    def _variant_ids(self) -> list[int]:
        return [int(x.strip()) for x in str(self.settings.printful_variant_ids).split(",") if x.strip().isdigit()]

    def payload(self, package: CommercePackage, *, print_url: str = "https://example.invalid/approved-print.png") -> dict[str, Any]:
        ids = self._variant_ids() or [4011]
        variants = []
        for i, vid in enumerate(ids):
            src = package.variants[min(i, len(package.variants)-1)] if package.variants else None
            variants.append({
                "variant_id": vid,
                "retail_price": src.price if src else self.settings.commerce_base_price,
                "sku": src.sku if src else f"{package.id}-{vid}",
                "files": [{"type": "default", "url": print_url}],
            })
        return {"sync_product": {"name": package.listing.title, "thumbnail": print_url}, "sync_variants": variants}

    def publish(self, package: CommercePackage, *, dry_run: bool = True, audit_dir: Path | None = None) -> PublishResult:
        audit_dir = Path(audit_dir or Path(package.source_run_dir) / "commerce" / package.id / "publish")
        audit_dir.mkdir(parents=True, exist_ok=True)
        payload = self.payload(package)
        payload_path = audit_dir / "printful_request.json"
        payload_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        if dry_run:
            warning = "Live Printful requires a public/signed URL for the approved print file"
            return PublishResult("printful", True, "dry-run", message=warning, payload_path=str(payload_path))
        self._validate()
        staged = str(package.metadata.get("public_print_stage") or package.print_file)
        print_url = self.public_url(staged)
        if not print_url:
            raise ConfigurationError("Printful requires ARCHIVIST_PUBLIC_ASSET_BASE_URL")
        payload = self.payload(package, print_url=print_url)
        row = self.transport.request("POST", f"{BASE}/store/products", headers=self._headers(), json_body=payload)
        result = row.get("result") or row
        product_id = str((result.get("sync_product") or {}).get("id") or result.get("id") or "") if isinstance(result, dict) else ""
        response_path = audit_dir / "printful_response.json"
        response_path.write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")
        return PublishResult("printful", True, "product-created", remote_id=product_id,
                             message="Printful Manual/API-store product created",
                             payload_path=str(payload_path), response_path=str(response_path))
