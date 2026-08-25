# Shopify editorial storefront add-on — ARCHIVIST V10.2

The API integration works without these theme files. These sections are the optional **front-end art-direction layer** for a Shopify-owned storefront.

## 1. Collection collage

Copy `archivist-collage-grid.liquid` into the Shopify theme's `sections/` directory, then add **ARCHIVIST collage grid** in the theme editor and select the product collection.

The adapter writes `product.metafields.archivist.layout_signature` for every product. The section maps the six signatures to different spans/aspect ratios so adjacent products build a controlled, dense editorial collage rather than a repeated ecommerce card grid.

## 2. Product-page editorial gallery

Copy `archivist-product-editorial.liquid` into `sections/`, then add **ARCHIVIST product editorial** to the product template once.

The same per-product signature changes media rhythm, controlled overlap, edge breaks and crop hierarchy. It still renders a real Shopify product form, variant selector and add-to-cart button. The source artwork is not warped; only the presentation layer changes.

## Why install is explicit

ARCHIVIST does **not** silently mutate Shopify theme code through the commerce token. Theme write permissions are broader than product-publishing permissions. Keeping theme installation a one-time explicit step avoids turning a product automation credential into a theme-administration credential.

After these two files are installed once, newly published ARCHIVIST products need no per-listing front-end work.
