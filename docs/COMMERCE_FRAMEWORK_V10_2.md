# ARCHIVIST V10.2 — Multi-Commerce + Storefront Art Direction Framework

## 0. Purpose

V10.2 turns the approved ARCHIVIST apparel output into a **channel-neutral commerce package** and then routes it to any combination of:

- **Etsy** — optional sales channel
- **Shopify** — optional owned storefront / sales channel
- **Printful** — optional POD product / fulfilment engine
- **Printify** — optional POD product / fulfilment engine

None of these services is a dependency of the design engine. The core still ends at a measured, approved apparel design. Commerce starts only after that boundary.

The design-side rule remains absolute:

```text
trend signal
  → intent truth
  → buyer / reason-to-wear proof
  → factual visual research
  → one art-directed concept
  → owned blueprint
  → generation
  → print proof + vision critic
  → APPROVED
  → only now: COMMERCE
```

This prevents marketplace pressure from pushing a weak or unverified concept through the art system.

---

# 1. V10.2 architecture

```text
                           ARCHIVIST HOUSE V10
                                  │
                         APPROVED DELIVERY ONLY
                                  │
                                  ▼
                        COMMERCE PACKAGE BUILDER
                    ┌─────────────┼──────────────┐
                    │             │              │
               COPY ENGINE   GALLERY ENGINE  VARIANT PROFILE
                    │             │              │
                    └─────────────┼──────────────┘
                                  ▼
                         CommercePackage.json
                                  │
                ┌─────────────────┴─────────────────┐
                │                                   │
          SALES-CHANNEL ROUTER                POD ROUTER
        ┌────────────┐                       ┌─────────────┐
        │            │                       │             │
       ETSY       SHOPIFY                PRINTFUL       PRINTIFY
        │            │                       │             │
        └──── frontend/listing ──────────────┴── product/fulfilment
```

The normalized object is `archivist.commerce.models.CommercePackage`.

It holds:

- approved print file
- approved artwork
- base garment mockup
- evidence-bound listing copy
- SEO title and description
- tags
- variants/SKUs/prices
- generated storefront gallery
- storefront layout signature
- Market Truth evidence snapshot
- reference-use audit
- platform-neutral metadata

Adapters never reach backward into the creative pipeline to reinterpret the subject.

---

# 2. Why commerce is downstream, not inside generation

The old failure mode was effectively:

```text
trend-ish word → aesthetic invention → generated image → find a reason to sell it
```

V10.2 does not allow a commerce adapter to rescue bad artwork with SEO. If Market Truth or the art director gate failed, `build_commerce_package()` raises `PackageBuildError` by default.

A rehearsal package can be created only with an explicit `allow_rehearsal` / `require_approved=False`; it remains an unpublished preview and is not evidence of market validity.

---

# 3. The storefront is art-directed too

A listing is not represented by one PNG anymore.

Every approved design is converted into a **five-image minimum editorial sequence**:

1. `00_collection_tile.jpg`
   - Shopify-first featured media
   - deliberately more editorial
   - intended to make collection grids behave like a controlled collage

2. `01_garment_hero.jpg`
   - garment remains dominant and legible
   - framing changes by design signature so Etsy thumbnails do not look cloned
   - Etsy-first media

3. `02_garment_perspective.jpg`
   - whole garment proof receives a light perspective transform
   - the actual artwork is never independently warped

4. `03_artwork_detail.jpg`
   - close crop showing print texture/composition

5. `04_process_study.jpg`
   - uses approved artwork plus selected raw/process frames from the run
   - makes the listing feel authored, not like a single AI output dropped on a shirt

6. Optional `05_licensed_reference.jpg`
   - generated only when a local reference is explicitly declared commerce-safe
   - never generated from ordinary research references automatically

This satisfies two distinct jobs:

- **conversion clarity** — buyer immediately understands the physical product;
- **art direction** — the shop feels like an editorial collection, not a POD template factory.

---

# 4. Cross-listing collage logic

Each package receives one deterministic layout signature from six families:

- `border-break`
- `offset-contact-sheet`
- `split-frame`
- `editorial-overlap`
- `vertical-filmstrip`
- `corner-window`

The signature is hashed from the package identity, so:

- the same listing stays visually stable on rebuild;
- adjacent listings naturally rotate through different compositions;
- no random UI jitter occurs every time the application starts.

The signature changes **framing**, not the underlying artwork.

## Shopify

Shopify receives the editorial collection tile first and the signature is written as:

```text
product.metafields.archivist.layout_signature
```

It also receives the extracted palette as JSON.

The repository includes:

```text
integrations/shopify_theme/archivist-collage-grid.liquid
```

Install this theme section once. After that, per-listing grid variation is automatic: the section reads the metafield and changes card span/aspect ratio. This is the true “clean Instagram collage between listings” mode.

ARCHIVIST does **not** silently mutate Shopify theme files through the commerce token. Theme-code access has a different risk/permission boundary. A one-time explicit theme installation is safer; every product after that is automatic.

### Shopify product-page editorial section

V10.2 ships a second optional one-time theme section:

```text
integrations/shopify_theme/archivist-product-editorial.liquid
```

It reads the same `archivist.layout_signature` written by the API adapter, but applies it to the **product detail page** rather than only the collection grid. The six composition families change grid spans, edge breaks, overlap, crop hierarchy and negative-space rhythm around the product media. The underlying artwork pixels are never warped. The section also contains a real Shopify product form, variant selector and add-to-cart button, so the editorial presentation does not replace commerce functionality.

This is the answer to the “every listing should feel designed, not templated” requirement: one one-time theme install, then each listing gets a deterministic visual grammar derived from its package ID and media sequence.

## Etsy

Etsy controls the marketplace/shop-grid CSS. An API client cannot make Etsy's own grid masonry or change card spans.

Therefore V10.2 does the maximum honest automation available:

- a per-listing first-image composition is generated;
- garment clarity is preserved;
- background, border break, overlap geometry, crop rhythm and inset treatment vary by signature;
- subsequent listing images continue the editorial sequence.

No code claims to control Etsy CSS that Etsy does not expose.

---

# 5. Raw mockup reuse

The gallery engine searches the approved run for internal files matching patterns such as:

```text
*raw*.png
*candidate*.png
*mockup*.png
*proof*.png
*artwork*.png
```

It selects a small number of valid process frames and uses them inside the process-study composition.

The raw frame is not presented as another final design. It is clearly framed as process/source material.

This gives listings visual depth without generating unnecessary extra paid images.

---

# 6. Reference-image policy

Research relevance is not a commercial-use licence.

Therefore normal reference-board images are **never automatically posted** to Etsy or Shopify.

If a reference is owned, licensed, public-domain, or otherwise cleared, create in the run directory:

```json
{
  "assets": [
    {
      "path": "refs/owned_reference.jpg",
      "commerce_safe": true
    }
  ]
}
```

Save it as:

```text
commerce_reference_manifest.json
```

Only then may the gallery engine create a licensed-reference card.

This is intentionally stricter than the internal research pipeline.

---

# 7. Copy / SEO engine

`archivist.commerce.copywriter` receives only:

- exact market signal
- Market Truth dominant intent
- evidenced buyer identity
- evidenced reason to care
- evidenced reason to wear
- nameable symbol
- approved physical property
- approved visual mutation/metaphor
- seller brand

The LLM may rewrite this information, but it may not add facts.

Forbidden inventions include:

- fake heritage
- fake dates
- fake geography
- fake subcultures
- unproved materials
- sustainability claims
- scarcity
- fake production techniques
- unproved buyer persona
- “limited edition” unless the operator actually configured it
- vague AI poetry
- keyword stuffing

A deterministic copywriter is always available if OpenAI is disabled.

## Etsy constraints enforced locally

Etsy's April 2026 seller guidance is also reflected in the copy layer: titles are kept clear and scan-friendly, targeted at **15 words or fewer** where possible instead of using the old keyword-chain style. Search relevance is distributed across the title, all relevant tags, description, category/attributes and first image. The hard API title limit remains enforced as a second safety boundary.


- title <= 140 characters
- maximum 13 tags
- every tag <= 20 characters
- physical-listing disclosure language retained
- AI-assisted design disclosure retained

## Shopify constraints

- dedicated `seo.title`
- concise SEO description target <= 160 characters
- product title/description/tags kept separately from SEO fields
- layout signature and palette stored in product metafields

## Tone

The target is:

```text
specific + editorial + restrained + readable
```

not:

```text
SEO sludge + fashion clichés + artificial luxury language
```

---

# 8. Etsy integration

Module:

```text
archivist/commerce/etsy.py
```

Live path:

```text
create draft physical listing
  → upload curated listing images
  → update size/SKU inventory
  → optional activate
```

Required configuration:

```text
ETSY_API_KEY
ETSY_ACCESS_TOKEN
ETSY_SHOP_ID
ETSY_TAXONOMY_ID
ETSY_SHIPPING_PROFILE_ID
ETSY_READINESS_STATE_ID
```

The adapter deliberately creates a draft first because an active Etsy listing requires image/physical-listing prerequisites.

Gallery order is Etsy-specific:

```text
garment hero
→ perspective
→ detail
→ process
→ other safe assets
```

This differs from Shopify on purpose.

For an owner operating only their own shop, Etsy's current Seller App path is the appropriate API path; a broader multi-seller product has different access rules.

---

# 9. Shopify integration

Module:

```text
archivist/commerce/shopify.py
```

The adapter uses the **Admin GraphQL API**, not the legacy REST Admin API.

Default API version:

```text
2026-07
```

Live path:

```text
local curated image
  → stagedUploadsCreate
  → binary upload to Shopify staged target
  → productCreate + media
  → productVariantsBulkCreate
  → SEO fields
  → ARCHIVIST metafields
  → DRAFT or ACTIVE product
```

Required configuration:

```text
SHOPIFY_STORE_DOMAIN=store.myshopify.com
SHOPIFY_ACCESS_TOKEN=...
SHOPIFY_API_VERSION=2026-07
```

The product receives:

```text
archivist.layout_signature
archivist.palette
archivist.market_truth
```

The first Shopify image is the collection tile, making ordinary product grids more visually varied even without the optional collage theme section.

---

# 10. Printify integration

Module:

```text
archivist/commerce/printify.py
```

Printify is both a POD catalog/product layer and, when its shop is connected to a supported sales channel, a possible channel-publishing owner.

Configuration:

```text
PRINTIFY_TOKEN
PRINTIFY_SHOP_ID
PRINTIFY_SHOP_ETSY_ID
PRINTIFY_SHOP_SHOPIFY_ID
PRINTIFY_BLUEPRINT_ID
PRINTIFY_PROVIDER_ID
PRINTIFY_VARIANT_IDS
PRINTIFY_PRINT_POSITION=front
PRINTIFY_SCALE=0.85
```

ARCHIVIST uploads the approved print file to Printify Media Library as base64, then creates the product with blueprint/provider/variant IDs.

## Two routing modes

### A. Direct-channel mode — storefront control first

```text
ARCHIVIST → Etsy/Shopify directly
ARCHIVIST → Printify product separately
```

Benefits:

- exact ARCHIVIST gallery order
- exact SEO and metafields
- direct listing control

Caveat:

A separately created Printify product is not magically an order binding. Your Printify/channel connection or a separate order bridge must own fulfilment.

### B. Printify native-channel mode — zero-touch binding first

```text
ARCHIVIST → Printify connected Etsy/Shopify shop → channel
```

Enable with:

```text
--pod-native-channel
```

or:

```text
ARCHIVIST_COMMERCE_POD_NATIVE_CHANNEL=1
```

Benefits:

- Printify owns the platform/POD relationship;
- best zero-touch path when fulfilment binding is the priority.

Trade-off:

- Printify has more control over the channel product lifecycle/media than the direct ARCHIVIST adapter.

V10.2 intentionally exposes this decision instead of pretending both ownership models can simultaneously be authoritative.

---

# 11. Printful integration

Module:

```text
archivist/commerce/printful.py
```

Printful's product/file APIs support URL-addressable print files. V10.2 therefore creates a collision-safe staging copy:

```text
commerce/<package-id>/public/<package-id>_approved_print.png
```

Set:

```text
ARCHIVIST_PUBLIC_ASSET_BASE_URL=https://your-public-prefix.example
```

The base must resolve to the directory containing that staged file.

For development, ARCHIVIST includes:

```bash
python -m archivist commerce-assets <public-directory> --host 0.0.0.0 --port 8090
```

In production, put HTTPS in front of it using Caddy/nginx/Cloudflare Tunnel/object storage/CDN.

Configuration:

```text
PRINTFUL_TOKEN
PRINTFUL_VARIANT_IDS
ARCHIVIST_PUBLIC_ASSET_BASE_URL
```

The adapter creates a Printful Manual/API store product using the approved print file URL and configured catalog variant IDs.

For a Shopify/Etsy store already connected to Printful, order automation should remain owned by that native Printful store connection and its synchronized variants. The commerce router does not falsely claim that merely creating a second Printful API product has bound an arbitrary external listing to fulfillment.

---

# 12. Optionality matrix

| Etsy | Shopify | Printful | Printify | Valid? | Meaning |
|---|---|---|---|---|---|
| off | off | off | off | yes | design pipeline only |
| on | off | off | off | yes | Etsy direct listing |
| off | on | off | off | yes | Shopify direct listing |
| on | on | off | off | yes | multi-channel listing |
| off | off | on | off | yes | Printful API product only |
| off | off | off | on | yes | Printify API product only |
| on | off | off | on | yes | Etsy + Printify strategy chosen by router |
| off | on | on | off | yes | Shopify + Printful strategy chosen by router |
| on | on | off | on | yes | two storefronts + Printify; direct or native mode |

No branch of the creative system requires a channel key.

---

# 13. Safe publishing defaults

The following are defaults:

```text
commerce auto-publish = OFF
CLI commerce-publish = DRY RUN
storefront listing = DRAFT
research reference republishing = OFF
```

To perform writes:

```bash
python -m archivist commerce-publish <package.json> \
  --channels etsy shopify \
  --fulfillment printify \
  --live
```

To activate listings immediately:

```bash
... --live --active
```

This is separate from “prepare,” so inspecting the payload costs nothing and creates no marketplace object.

---

# 14. Zero-touch mode after House approval

V10.2 can be fully automatic, but only after the user explicitly enables it.

```text
ARCHIVIST_COMMERCE_AUTO_PUBLISH=1
ARCHIVIST_COMMERCE_AUTO_CHANNELS=etsy,shopify
ARCHIVIST_COMMERCE_AUTO_FULFILLMENT=printify
ARCHIVIST_COMMERCE_AUTO_ACTIVE=0
ARCHIVIST_COMMERCE_POD_NATIVE_CHANNEL=1
```

When enabled:

```text
House Market Truth PASS
  → structural gate PASS
  → image/print proof PASS
  → final delivery
  → commerce package generated
  → configured commerce route runs live
  → commerce_receipt.json written
```

Commerce failure does **not** invalidate a good artwork. It creates a warning and an audit receipt so the listing can be retried without paying for another image generation.

This is important: production/API failure and creative failure are different failure classes.

---

# 15. UI workflow

The Gradio control room now has:

```text
① Setup
② Connection
③ Discovery
④ Studio
⑤ Monitor
⑥ Schedule
⑦ House V10
⑧ Commerce
⑨ Deploy
```

Commerce tab supports:

- save optional Etsy credentials
- save optional Shopify credentials
- save optional Printful profile
- save optional Printify profile
- set brand/base price
- configure public asset URL
- configure zero-touch automation
- select latest House output
- prepare SEO/gallery package
- preview generated gallery
- inspect listing copy
- choose channels
- choose POD provider
- dry run
- draft/active state
- Printify native-channel strategy
- inspect request/response audit files

---

# 16. CLI workflow

## Prepare only

```bash
python -m archivist commerce-prepare /path/to/approved/final \
  --price 34.00 \
  --sizes S,M,L,XL,2XL
```

Outputs:

```text
commerce/<package-id>/
├── commerce_package.json
├── listing_preview.md
├── gallery/
│   ├── 00_collection_tile.jpg
│   ├── 01_garment_hero.jpg
│   ├── 02_garment_perspective.jpg
│   ├── 03_artwork_detail.jpg
│   ├── 04_process_study.jpg
│   └── 05_licensed_reference.jpg   (only if explicitly safe)
├── public/
│   └── <package-id>_approved_print.png
└── publish/
    └── ... dry/live request/response audit
```

## Dry-run multi-channel route

```bash
python -m archivist commerce-publish commerce_package.json \
  --channels etsy shopify \
  --fulfillment printify
```

## Live but draft

```bash
python -m archivist commerce-publish commerce_package.json \
  --channels etsy shopify \
  --fulfillment printify \
  --live
```

## Live + immediately active

```bash
python -m archivist commerce-publish commerce_package.json \
  --channels etsy shopify \
  --fulfillment none \
  --live --active
```

## Printify native connected-channel ownership

```bash
python -m archivist commerce-publish commerce_package.json \
  --channels etsy \
  --fulfillment printify \
  --pod-native-channel \
  --live
```

---

# 17. Secrets and auditability

Commerce secrets are redacted by `Settings.redacted()` just like image-generation credentials.

The following values never belong in a run manifest:

```text
ETSY_API_KEY
ETSY_ACCESS_TOKEN
SHOPIFY_ACCESS_TOKEN
PRINTFUL_TOKEN
PRINTIFY_TOKEN
```

Commerce writes produce inspectable files instead:

```text
etsy_request.json
etsy_response.json
shopify_request.json
shopify_response.json
printify_*_request.json
printify_*_response.json
printful_request.json
printful_response.json
commerce_receipt.json
```

The receipt is the canonical answer to:

- what was attempted?
- which platform succeeded?
- what remote ID was returned?
- draft or active?
- which POD strategy was used?
- what still needs operator action?

---

# 18. Failure taxonomy

Commerce failures never trigger another image generation.

```text
CONFIGURATION FAILURE
missing token / shop ID / catalog ID
→ stop that adapter
→ $0 generation spend

MEDIA FAILURE
upload rejected / bad file URL
→ keep approved design
→ retry media only

LISTING FAILURE
marketplace schema validation
→ keep package
→ patch request/copy only

FULFILMENT BINDING FAILURE
POD product exists but sales-channel binding is absent
→ warn explicitly
→ do not claim automatic fulfillment

CREATIVE FAILURE
occurs only before CommercePackage exists
→ handled by House gate, not commerce
```

---

# 19. What “all-in integration” means in V10.2

A successful live route can now cover:

```text
PUBLIC SIGNAL
→ MARKET TRUTH
→ DESIGN
→ PRINT PROOF
→ RAW/PROCESS ASSET SELECTION
→ STORE GALLERY ART DIRECTION
→ PER-LISTING FRONT-END SIGNATURE
→ SEO / TITLE / DESCRIPTION / TAGS
→ PRODUCT VARIANTS / SKU / PRICE
→ ETSY AND/OR SHOPIFY
→ PRINTFUL AND/OR PRINTIFY
→ AUDIT RECEIPT
```

What it deliberately does **not** fake:

- Etsy does not expose arbitrary shop CSS control.
- a random research image is not automatically licensed for a storefront.
- a separately created POD product is not automatically an order binding to an unrelated marketplace listing.
- Printful URL-file requirements are not hidden.
- theme-code mutation is not bundled into an ordinary Shopify product token.

Those constraints are treated as architecture, not inconveniences to hand-wave away.

---

# 20. Current API assumptions / official documentation

Implementation was designed against the current public documentation available in August 2026:

- Etsy Open API v3 listings tutorial: `https://developers.etsy.com/documentation/tutorials/listings/`
- Etsy Open API v3 reference: `https://developers.etsy.com/documentation/reference`
- Printify API: `https://developers.printify.com/`
- Printful API: `https://developers.printful.com/docs/`
- Shopify Admin GraphQL: `https://shopify.dev/docs/api/admin-graphql/2026-07`

Shopify is GraphQL-first because the REST Admin API is legacy for new public apps.

---

# 21. Regression contract added in V10.2

`tests/test_commerce.py` verifies:

1. an unapproved design cannot create a publish package;
2. a passed House route produces the full storefront sequence;
3. Etsy title/tag limits are enforced;
4. AI/production disclosures survive deterministic copy generation;
5. research references do not leak into storefronts;
6. an explicitly commerce-safe local reference can be used;
7. Etsy/Shopify/Printful/Printify receive platform-specific payloads;
8. all integrations can remain unconfigured and the design pipeline still works;
9. commerce secrets are redacted;
10. Shopify HTML copy is escaped before GraphQL submission;
11. both the collection and product-page editorial theme sections are present and wired to `archivist.layout_signature`.

The existing engine/discovery/scheduler tests remain separate so a commerce refactor cannot silently weaken Market Truth.

---

# 22. Recommended production configuration

For the first commercial test:

```text
Sales channel: Etsy
POD: Printify native-channel OR existing Printful Etsy connection
Listing activation: draft first
ARCHIVIST auto publish: OFF until one complete dry-run is inspected
```

For a branded owned store:

```text
Sales channel: Shopify
Install ARCHIVIST collage section once
POD: Printful or Printify native Shopify connection
ARCHIVIST product adapter: exact SEO + media + metafields
```

For multi-channel scale:

```text
ARCHIVIST House
→ CommercePackage
→ Shopify direct
→ Etsy direct or POD-native route
→ POD binding owned by exactly one provider
→ one commerce_receipt per package
```

The key principle is **one source of truth for the design, one source of truth for the storefront object, one source of truth for fulfillment**. V10.2 exposes those boundaries instead of allowing duplicate systems to silently fight each other.
