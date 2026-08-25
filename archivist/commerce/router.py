"""Orchestrate optional sales channels and POD providers without coupling them.

Safety defaults:
* prepare only / dry-run unless explicitly asked to publish;
* draft listings unless explicitly asked to activate;
* no channel or fulfilment provider is required;
* third-party research reference pixels never reach public galleries unless an
  explicit commerce_reference_manifest marks them commerce_safe.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .errors import CommerceError
from .etsy import EtsyAdapter
from .models import CommercePackage, CommerceReceipt, PublishResult
from .printful import PrintfulAdapter
from .printify import PrintifyAdapter
from .shopify import ShopifyAdapter


class CommerceRouter:
    def __init__(self, settings, *, transports: dict[str, object] | None = None):
        self.settings = settings
        transports = transports or {}
        self.etsy = EtsyAdapter(settings, transport=transports.get("etsy"))
        self.shopify = ShopifyAdapter(settings, transport=transports.get("shopify"))
        self.printful = PrintfulAdapter(settings, transport=transports.get("printful"))
        self.printify = PrintifyAdapter(settings, transport=transports.get("printify"))

    def publish(
        self,
        package: CommercePackage,
        *,
        channels: Iterable[str] = (),
        fulfillment: str = "none",
        dry_run: bool = True,
        active: bool = False,
        pod_native_channel: bool = False,
    ) -> CommerceReceipt:
        channels = [c.lower().strip() for c in channels if c and c.lower().strip() in {"etsy", "shopify"}]
        fulfillment = (fulfillment or "none").lower().strip()
        if fulfillment not in {"none", "printful", "printify"}:
            raise ValueError("fulfillment must be none, printful or printify")

        # A preview package exists so an unproven design can be *inspected*. Dry
        # running it is the point; putting it in front of buyers is not, and the
        # builder's approval decision would be worth nothing if this step could
        # quietly overrule it.
        if not dry_run and not package.approved:
            raise CommerceError(
                f"refusing to publish an unapproved package ({package.approval_reason}). "
                "Dry-run it to inspect the payloads, or re-run the design so the gates pass."
            )
        receipt = CommerceReceipt(package.id, dry_run, channels, fulfillment)
        audit_dir = Path(package.source_run_dir) / "commerce" / package.id / "publish"
        audit_dir.mkdir(parents=True, exist_ok=True)

        # Native Printify publish can create on a connected Etsy/Shopify sales
        # channel. It is opt-in because direct channel publish gives ARCHIVIST
        # tighter control over the storefront gallery and SEO.
        if fulfillment == "printify" and pod_native_channel and channels:
            for channel in channels:
                try:
                    receipt.results.append(self.printify.publish(
                        package, channel=channel, dry_run=dry_run,
                        publish_to_connected_channel=True, audit_dir=audit_dir,
                    ))
                except Exception as exc:
                    receipt.results.append(PublishResult("printify", False, "failed", message=f"{channel}: {type(exc).__name__}: {exc}"))
            receipt.warnings.append(
                "Printify native-channel mode lets Printify own the product/channel binding. "
                "Use direct-channel mode when ARCHIVIST's exact gallery ordering is the priority."
            )
        else:
            for channel in channels:
                adapter = self.etsy if channel == "etsy" else self.shopify
                try:
                    receipt.results.append(adapter.publish(package, dry_run=dry_run, active=active, audit_dir=audit_dir))
                except Exception as exc:
                    receipt.results.append(PublishResult(channel, False, "failed", message=f"{type(exc).__name__}: {exc}"))

            if fulfillment == "printify":
                try:
                    receipt.results.append(self.printify.publish(package, dry_run=dry_run, audit_dir=audit_dir))
                    receipt.warnings.append(
                        "Direct-channel + Printify creates the POD product but does not claim an order binding unless your Printify store/channel integration is configured. "
                        "Use --pod-native-channel for Printify-owned channel publishing."
                    )
                except Exception as exc:
                    receipt.results.append(PublishResult("printify", False, "failed", message=f"{type(exc).__name__}: {exc}"))
            elif fulfillment == "printful":
                try:
                    receipt.results.append(self.printful.publish(package, dry_run=dry_run, audit_dir=audit_dir))
                    receipt.warnings.append(
                        "Printful Manual/API product creation requires public artwork URLs. For automatic Etsy/Shopify order fulfilment, connect that sales channel to Printful and map/sync the resulting variants in Printful."
                    )
                except Exception as exc:
                    receipt.results.append(PublishResult("printful", False, "failed", message=f"{type(exc).__name__}: {exc}"))

        path = audit_dir / "commerce_receipt.json"
        path.write_text(json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return receipt
