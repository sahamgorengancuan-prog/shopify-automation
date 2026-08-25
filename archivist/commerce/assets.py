"""Platform-aware storefront art direction.

These assets are deliberately generated *after* design approval.  They never
change the artwork.  Instead they turn the approved print, proof and selected
raw frames into a coherent product-gallery sequence and distinctive collection
thumbnail.  The first image policy differs by channel: Shopify may lead with a
collection tile; Etsy leads with a garment proof for purchase clarity.
"""

from __future__ import annotations

import colorsys
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps, ImageStat

from .models import GalleryAsset, StorefrontPlan

SIGNATURES = (
    "border-break",
    "offset-contact-sheet",
    "split-frame",
    "editorial-overlap",
    "vertical-filmstrip",
    "corner-window",
)


def _font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _fit(path: Path, size: tuple[int, int], *, contain: bool = False) -> Image.Image:
    im = Image.open(path).convert("RGB")
    if contain:
        canvas = Image.new("RGB", size, "#efede7")
        fitted = ImageOps.contain(im, size)
        canvas.paste(fitted, ((size[0] - fitted.width) // 2, (size[1] - fitted.height) // 2))
        return canvas
    return ImageOps.fit(im, size, Image.Resampling.LANCZOS)


def _palette(path: Path, count: int = 4) -> list[str]:
    try:
        im = Image.open(path).convert("RGB").resize((96, 96))
        colors = im.quantize(colors=count, method=Image.Quantize.MEDIANCUT).convert("RGB").getcolors(96 * 96) or []
        colors.sort(reverse=True)
        return ["#%02x%02x%02x" % rgb for _n, rgb in colors[:count]]
    except Exception:
        return ["#171717", "#e9e4d8", "#82765f", "#b7b1a5"]


def _contrast(hex_color: str) -> str:
    raw = hex_color.lstrip("#")
    r, g, b = [int(raw[i:i+2], 16) for i in (0, 2, 4)]
    lum = (0.2126*r + 0.7152*g + 0.0722*b) / 255
    return "#111111" if lum > .58 else "#f5f3ed"


def _subject(route: dict[str, Any], topic: str) -> str:
    truth = route.get("market_truth") or {}
    return str(truth.get("nameable_symbol") or route.get("real_subject") or topic).strip()


def _signature(package_id: str) -> str:
    return SIGNATURES[int(hashlib.sha256(package_id.encode()).hexdigest()[:8], 16) % len(SIGNATURES)]


def _raw_candidates(run_dir: Path, exclude: set[Path], limit: int = 3) -> list[Path]:
    patterns = ("*raw*.png", "*candidate*.png", "*mockup*.png", "*proof*.png", "*artwork*.png")
    out: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for p in sorted(run_dir.rglob(pattern)):
            if not p.is_file() or p in exclude or p in seen or "commerce" in p.parts:
                continue
            try:
                if p.stat().st_size < 10_000:
                    continue
            except OSError:
                continue
            seen.add(p)
            out.append(p)
            if len(out) >= limit:
                return out
    return out


def _reference_manifest(run_dir: Path) -> list[Path]:
    """Only explicitly licensed/owned local references may enter a storefront.

    Searching a reference for research is *not* permission to republish it. A
    user can opt a local file in with ``commerce_reference_manifest.json``:
      {"assets":[{"path":"refs/x.jpg","commerce_safe":true}]}
    """
    manifest = run_dir / "commerce_reference_manifest.json"
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return []
    out: list[Path] = []
    for row in data.get("assets", []):
        if not row.get("commerce_safe"):
            continue
        p = Path(str(row.get("path", "")))
        if not p.is_absolute():
            p = run_dir / p
        if p.is_file():
            out.append(p)
    return out[:2]


def _save(im: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, quality=94)
    return path


def _make_listing_hero(mockup: Path, art: Path, out: Path, signature: str, palette: list[str]) -> Path:
    """Conversion-clear garment image with a restrained signature-specific frame.

    The shirt remains dominant. The variation lives in framing/background so
    adjacent marketplace thumbnails do not look like template clones.
    """
    bg = palette[1] if len(palette) > 1 else "#ece8df"
    fg = _contrast(bg)
    accent = palette[2] if len(palette) > 2 else "#706653"
    c = Image.new("RGB", (1800, 1800), bg)
    d = ImageDraw.Draw(c)
    m = _fit(mockup, (1220, 1580), contain=True)
    x = {"border-break":80,"offset-contact-sheet":260,"split-frame":100,"editorial-overlap":180,"vertical-filmstrip":350,"corner-window":160}.get(signature,160)
    c.paste(m, (x, 110))
    if signature in {"border-break", "corner-window"}:
        d.rectangle((70, 70, 1730, 1730), outline=fg, width=8)
        d.rectangle((0, 1320, 520, 1800), fill=bg)  # deliberate border interruption
    elif signature == "vertical-filmstrip":
        d.rectangle((70, 80, 250, 1720), fill=accent)
        for y in range(130, 1670, 230): d.rectangle((98, y, 222, y+130), outline=fg, width=4)
    elif signature == "split-frame":
        d.line((910, 0, 910, 1800), fill=accent, width=9)
    else:
        d.rectangle((120, 1250, 1680, 1640), outline=accent, width=10)
    # One small artwork crop creates authorship/process context without hiding product.
    a = _fit(art, (390, 480))
    c.paste(a, (1320, 1180))
    d.rectangle((1300, 1160, 1730, 1680), outline=fg, width=5)
    d.text((85, 85), "ARCHIVIST / GARMENT PROOF", font=_font(22, True), fill=fg)
    return _save(c, out)


def _make_perspective(mockup: Path, out: Path) -> Path:
    base = Image.open(mockup).convert("RGB")
    base = ImageOps.fit(base, (1600, 2000), Image.Resampling.LANCZOS)
    # Gentle physical perspective, never bend artwork itself: transform whole proof.
    quad = (100, 80, 1540, 0, 1600, 1930, 0, 2000)
    warped = base.transform((1600, 2000), Image.Transform.QUAD, quad, Image.Resampling.BICUBIC)
    bg = Image.new("RGB", (1600, 2000), "#e9e5dc")
    shadow = Image.new("L", (1600, 2000), 0)
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((120, 130, 1510, 1930), 48, fill=115)
    shadow = shadow.filter(ImageFilter.GaussianBlur(38))
    bg.paste(Image.new("RGB", bg.size, "#252423"), mask=shadow)
    bg.paste(warped, mask=Image.new("L", warped.size, 244))
    return _save(bg, out)


def _make_detail(art: Path, out: Path) -> Path:
    im = Image.open(art).convert("RGB")
    w, h = im.size
    crop = im.crop((int(w*.18), int(h*.15), int(w*.86), int(h*.83)))
    crop = ImageOps.fit(crop, (1600, 2000), Image.Resampling.LANCZOS)
    crop = ImageEnhance.Contrast(crop).enhance(1.04)
    return _save(crop, out)


def _make_process(raws: list[Path], art: Path, out: Path, subject: str, palette: list[str]) -> Path:
    bg = palette[1] if len(palette) > 1 else "#e9e5dc"
    fg = _contrast(bg)
    canvas = Image.new("RGB", (1600, 2000), bg)
    draw = ImageDraw.Draw(canvas)
    draw.text((96, 92), "SOURCE → FORM", font=_font(34, True), fill=fg)
    draw.text((96, 148), subject.upper()[:48], font=_font(22), fill=fg)
    slots = [(96, 260, 760, 1000), (840, 360, 1510, 1160), (280, 1220, 1320, 1870)]
    imgs = [*raws[:2], art]
    for i, (p, box) in enumerate(zip(imgs, slots)):
        frame = _fit(p, (box[2]-box[0], box[3]-box[1]))
        canvas.paste(frame, (box[0], box[1]))
        draw.rectangle(box, outline=fg, width=4)
        draw.text((box[0]+12, box[1]+12), f"0{i+1}", font=_font(22, True), fill=fg)
    draw.text((96, 1930), "APPROVED PROCESS STUDY / NOT A SECOND DESIGN", font=_font(19), fill=fg)
    return _save(canvas, out)


def _tile(package_id: str, signature: str, mockup: Path, art: Path, out: Path, subject: str, palette: list[str]) -> Path:
    """Generate a square collection tile whose layout rotates across listings."""
    bg = palette[0] if palette else "#171717"
    fg = _contrast(bg)
    accent = palette[2] if len(palette) > 2 else ("#c7ad72" if fg == "#f5f3ed" else "#695d47")
    c = Image.new("RGB", (1800, 1800), bg)
    d = ImageDraw.Draw(c)
    m = _fit(mockup, (950, 1280))
    a = _fit(art, (730, 920))

    if signature == "border-break":
        c.paste(m, (90, 270)); c.paste(a, (1030, -80)); d.rectangle((1000, 40, 1750, 1680), outline=fg, width=5)
    elif signature == "offset-contact-sheet":
        c.paste(m, (-80, 160)); c.paste(a, (1050, 690)); d.rectangle((990, 620, 1760, 1680), fill=accent); c.paste(a, (1020, 650))
    elif signature == "split-frame":
        c.paste(_fit(mockup, (880, 1800)), (0, 0)); c.paste(_fit(art, (920, 1800)), (880, 0)); d.line((880, 0, 880, 1800), fill=fg, width=6)
    elif signature == "editorial-overlap":
        c.paste(m, (120, 150)); a2 = a.rotate(-5, expand=True, fillcolor=bg); c.paste(a2, (970, 700)); d.rectangle((1010, 715, 1700, 1630), outline=accent, width=20)
    elif signature == "vertical-filmstrip":
        c.paste(_fit(mockup, (1120, 1500)), (340, 150)); small = _fit(art, (380, 470));
        for y in (90, 665, 1240): c.paste(small, (30, y))
        d.line((440, 0, 440, 1800), fill=accent, width=8)
    else:  # corner-window
        c.paste(_fit(art, (1800, 1800)), (0, 0)); d.rectangle((70, 70, 1730, 1730), outline=fg, width=12); c.paste(_fit(mockup, (760, 980)), (940, 750))

    d.rectangle((68, 70, 810, 240), fill=bg)
    d.text((92, 92), "ARCHIVIST", font=_font(34, True), fill=fg)
    d.text((92, 148), subject.upper()[:38], font=_font(25), fill=fg)
    d.text((92, 1710), package_id[-10:].upper(), font=_font(19), fill=fg)
    return _save(c, out)


def _reference_card(ref: Path, out: Path, subject: str) -> Path:
    canvas = Image.new("RGB", (1600, 2000), "#f2efe7")
    frame = _fit(ref, (1320, 1500), contain=True)
    canvas.paste(frame, (140, 180))
    d = ImageDraw.Draw(canvas)
    d.rectangle((90, 110, 1510, 1710), outline="#151515", width=5)
    d.text((110, 1760), "LICENSED / OWNED VISUAL REFERENCE", font=_font(22, True), fill="#151515")
    d.text((110, 1810), subject[:70], font=_font(20), fill="#151515")
    d.text((110, 1880), "Included for provenance; reference pixels were not used as a hidden claim of authorship.", font=_font(17), fill="#151515")
    return _save(canvas, out)


def build_storefront_assets(
    run_dir: Path,
    out_dir: Path,
    *,
    package_id: str,
    topic: str,
    route: dict[str, Any],
    mockup: Path,
    artwork: Path,
) -> StorefrontPlan:
    out_dir.mkdir(parents=True, exist_ok=True)
    subject = _subject(route, topic)
    palette = _palette(artwork)
    signature = _signature(package_id)
    raws = _raw_candidates(run_dir, {mockup, artwork}, limit=3)
    refs = _reference_manifest(run_dir)

    hero = _make_listing_hero(mockup, artwork, out_dir / "01_garment_hero.jpg", signature, palette)
    perspective = _make_perspective(mockup, out_dir / "02_garment_perspective.jpg")
    detail = _make_detail(artwork, out_dir / "03_artwork_detail.jpg")
    process = _make_process(raws, artwork, out_dir / "04_process_study.jpg", subject, palette)
    tile = _tile(package_id, signature, mockup, artwork, out_dir / "00_collection_tile.jpg", subject, palette)

    gallery = [
        GalleryAsset(str(tile), "collection_tile", 0, f"Editorial collection tile for {subject}", platform_hint="shopify-first"),
        GalleryAsset(str(hero), "garment_hero", 1, f"{subject} graphic T-shirt front view", platform_hint="etsy-first"),
        GalleryAsset(str(perspective), "garment_perspective", 2, f"{subject} T-shirt perspective view"),
        GalleryAsset(str(detail), "artwork_detail", 3, f"Detail of the {subject} artwork"),
        GalleryAsset(str(process), "process_study", 4, f"Approved process study for the {subject} artwork"),
    ]
    if refs:
        ref_card = _reference_card(refs[0], out_dir / "05_licensed_reference.jpg", subject)
        gallery.append(GalleryAsset(str(ref_card), "licensed_reference", 5, f"Licensed visual reference related to {subject}", source_kind="licensed-reference", commerce_safe=True))

    return StorefrontPlan(
        signature=signature,
        collection_tile=str(tile),
        gallery=gallery,
        palette=palette,
        composition_notes=[
            "Shopify collection grid uses the editorial tile first so adjacent listings form a varied collage.",
            "Etsy uses garment hero first for product clarity, then perspective/detail/process imagery.",
            "Layout signature is deterministic per listing but rotates across six composition families.",
            "Third-party research references are never republished unless explicitly opted in as commerce_safe.",
        ],
        reference_policy="licensed-or-owned-only; research references are excluded by default",
    )
