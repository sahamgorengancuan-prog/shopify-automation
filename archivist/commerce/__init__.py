"""Optional multi-commerce layer for ARCHIVIST.

Sales channels: Etsy, Shopify.
Fulfilment/product engines: Printful, Printify.
All are optional and the design pipeline remains runnable with none configured.
"""

from .builder import build_commerce_package
from .router import CommerceRouter
from .models import CommercePackage, CommerceReceipt, PublishResult

__all__ = ["build_commerce_package", "CommerceRouter", "CommercePackage", "CommerceReceipt", "PublishResult"]
