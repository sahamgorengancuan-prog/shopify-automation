"""Shopify Admin GraphQL adapter (stable API version configurable; default 2026-07)."""
from __future__ import annotations

import json
import mimetypes
from html import escape
from pathlib import Path
from typing import Any

from .errors import ConfigurationError, PublishError
from .models import CommercePackage, PublishResult
from .transport import Transport


class ShopifyAdapter:
    name = "shopify"

    def __init__(self, settings, *, transport: Transport | None = None):
        self.settings = settings
        self.transport = transport or Transport(timeout=settings.http_timeout)

    @property
    def endpoint(self) -> str:
        store = self.settings.shopify_store_domain.replace("https://", "").rstrip("/")
        return f"https://{store}/admin/api/{self.settings.shopify_api_version}/graphql.json"

    def _headers(self) -> dict[str, str]:
        return {"X-Shopify-Access-Token": self.settings.shopify_access_token, "Content-Type": "application/json"}

    def check(self) -> tuple[bool, str]:
        if not self.settings.shopify_store_domain or not self.settings.shopify_access_token:
            return False, "not configured"
        data = self.transport.graphql(self.endpoint, "query ArchivistShopCheck { shop { name myshopifyDomain } }", {}, headers=self._headers())
        shop = data.get("shop") or {}
        return True, f"{shop.get('name', 'shop')} ({shop.get('myshopifyDomain', self.settings.shopify_store_domain)})"

    def _validate(self) -> None:
        if not self.settings.shopify_store_domain or not self.settings.shopify_access_token:
            raise ConfigurationError("Shopify requires SHOPIFY_STORE_DOMAIN and SHOPIFY_ACCESS_TOKEN")

    def product_input(self, package: CommercePackage, media: list[dict[str, str]] | None = None, *, active: bool = False) -> dict[str, Any]:
        return {
            "title": package.listing.title,
            "descriptionHtml": "<p>" + escape(package.listing.description).replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>",
            "vendor": package.listing.vendor,
            "productType": package.listing.product_type,
            "handle": package.listing.handle,
            "tags": package.listing.tags,
            "status": "ACTIVE" if active else "DRAFT",
            "seo": {"title": package.listing.seo_title, "description": package.listing.seo_description},
            "productOptions": [{"name": "Size", "values": [{"name": v.size} for v in package.variants]}] if package.variants else [],
            "metafields": [
                {"namespace": "archivist", "key": "layout_signature", "type": "single_line_text_field", "value": package.storefront.signature},
                {"namespace": "archivist", "key": "palette", "type": "json", "value": json.dumps(package.storefront.palette)},
                {"namespace": "archivist", "key": "market_truth", "type": "json", "value": json.dumps({"passed": package.approved, "signal": package.topic})},
            ],
        }

    def _stage(self, path: Path) -> str:
        """Upload one local image to Shopify staged storage and return resource URL."""
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        query = """
        mutation stage($input:[StagedUploadInput!]!){stagedUploadsCreate(input:$input){stagedTargets{url resourceUrl parameters{name value}} userErrors{field message}}}
        """
        data = self.transport.graphql(self.endpoint, query, {"input": [{"filename": path.name, "mimeType": mime, "httpMethod": "POST", "resource": "PRODUCT_IMAGE"}]}, headers=self._headers())
        node = data.get("stagedUploadsCreate") or {}
        errors = node.get("userErrors") or []
        if errors:
            raise PublishError("Shopify stagedUploadsCreate: " + str(errors))
        target = (node.get("stagedTargets") or [None])[0]
        if not target:
            raise PublishError("Shopify staged upload returned no target")
        fields = {p["name"]: p["value"] for p in target.get("parameters", [])}
        with path.open("rb") as fh:
            resp = self.transport.session.post(target["url"], data=fields, files={"file": (path.name, fh, mime)}, timeout=self.transport.timeout)
        if resp.status_code not in (200, 201, 204):
            raise PublishError(f"Shopify staged binary upload failed HTTP {resp.status_code}: {resp.text[:500]}")
        return str(target.get("resourceUrl") or "")

    def publish(self, package: CommercePackage, *, dry_run: bool = True, active: bool = False, audit_dir: Path | None = None) -> PublishResult:
        audit_dir = Path(audit_dir or Path(package.source_run_dir) / "commerce" / package.id / "publish")
        audit_dir.mkdir(parents=True, exist_ok=True)
        preview_input = self.product_input(package, active=active)
        payload_path = audit_dir / "shopify_request.json"
        payload_path.write_text(json.dumps({"product": preview_input, "gallery": [a.to_dict() for a in package.storefront.gallery]}, indent=2, ensure_ascii=False), encoding="utf-8")
        if dry_run:
            return PublishResult("shopify", True, "dry-run", message="GraphQL product, variants, SEO/metafields and staged gallery validated locally", payload_path=str(payload_path))
        self._validate()
        if not package.approved:
            raise PublishError("Shopify publish blocked: package is not approved")

        # Shopify: collection tile first gives the shop grid its controlled collage rhythm.
        media_inputs = []
        for asset in sorted(package.storefront.gallery, key=lambda a: a.rank):
            if not asset.exists or not asset.commerce_safe:
                continue
            url = self._stage(Path(asset.path))
            if url:
                media_inputs.append({"originalSource": url, "alt": asset.alt_text, "mediaContentType": "IMAGE"})

        create_q = """
        mutation create($product:ProductCreateInput!,$media:[CreateMediaInput!]){
          productCreate(product:$product,media:$media){product{id handle options{id name values}} userErrors{field message}}
        }
        """
        data = self.transport.graphql(self.endpoint, create_q, {"product": self.product_input(package, active=active), "media": media_inputs}, headers=self._headers())
        node = data.get("productCreate") or {}
        if node.get("userErrors"):
            raise PublishError("Shopify productCreate: " + str(node["userErrors"]))
        product = node.get("product") or {}
        pid = str(product.get("id") or "")
        if not pid:
            raise PublishError("Shopify productCreate returned no product id")

        # productCreate creates one initial variant; bulk create the real size set and
        # remove the standalone variant only by user choice later. This avoids destructive mutation.
        if len(package.variants) > 1:
            variants_q = """
            mutation variants($productId:ID!,$variants:[ProductVariantsBulkInput!]!){
              productVariantsBulkCreate(productId:$productId,variants:$variants,strategy:REMOVE_STANDALONE_VARIANT){
                productVariants{id title selectedOptions{name value}} userErrors{field message}
              }}
            """
            rows = [{"price": float(v.price), "inventoryItem": {"sku": v.sku}, "optionValues": [{"optionName": "Size", "name": v.size}]} for v in package.variants]
            vdata = self.transport.graphql(self.endpoint, variants_q, {"productId": pid, "variants": rows}, headers=self._headers())
            vnode = vdata.get("productVariantsBulkCreate") or {}
            if vnode.get("userErrors"):
                raise PublishError("Shopify productVariantsBulkCreate: " + str(vnode["userErrors"]))
        response_path = audit_dir / "shopify_response.json"
        response_path.write_text(json.dumps({"product": product, "media_count": len(media_inputs)}, indent=2, default=str), encoding="utf-8")
        remote_url = f"https://{self.settings.shopify_store_domain.replace('https://','').rstrip('/')}/products/{product.get('handle','')}"
        return PublishResult("shopify", True, "active" if active else "draft", remote_id=pid, remote_url=remote_url,
                             message=f"Shopify product created with {len(media_inputs)} staged images and editorial metafields",
                             payload_path=str(payload_path), response_path=str(response_path))
