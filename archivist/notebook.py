"""Helpers for the one-run notebook.

The notebook is a *runner*, not an application: fill in the parameter cell, choose
Run all, and one pipeline executes end to end. Everything it needs that is not
pipeline logic lives here, so the cells stay short enough to read at a glance and
this behaviour is covered by the test suite like everything else.

Three jobs:

* **bootstrap** — clone or update this repository from GitHub and install only
  what a headless run actually needs (no UI stack);
* **secrets** — resolve keys from Colab Secrets, the parameter cell, the
  environment or ``.env``, and report where each one came from without ever
  printing a value;
* **presentation** — the creative contract, the proof table, the preview images
  and one downloadable package at the end.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_URL = "https://github.com/sahamgorengancuan-prog/shopify-automation.git"
REPO_BRANCH = "claude/apparel-design-pipeline-6e3g0q"
REPO_WEB = "https://github.com/sahamgorengancuan-prog/shopify-automation"

# name, required-for, what happens without it
SECRET_SPECS: tuple[tuple[str, str, str], ...] = (
    ("HF_TOKEN", "image generation (the default provider)",
     "the run stops after the blueprint and prompt contract — nothing is rendered"),
    ("OPENAI_API_KEY", "market truth, the creative route and the visual critic",
     "market truth cannot pass, so live generation stays blocked and the run is research only"),
    ("BFL_API_KEY", "image generation, only with ARCHIVIST_IMAGE_PROVIDER=bfl",
     "ignored unless the bfl provider is selected"),
    ("PEXELS_API_KEY", "reference photography",
     "reference mining falls back to DuckDuckGo alone"),
    ("REDDIT_CLIENT_ID", "social heat (with the secret)",
     "Reddit is queried anonymously, which hosted runtimes are often blocked from"),
    ("REDDIT_CLIENT_SECRET", "social heat", "as above"),
    ("X_BEARER_TOKEN", "X social heat", "X is skipped"),
    ("META_ACCESS_TOKEN", "Instagram hashtag heat", "Meta is skipped"),
    ("META_IG_USER_ID", "Instagram hashtag heat", "Meta is skipped"),
)

REQUIRED_FOR_IMAGES = ("HF_TOKEN",)
MINIMAL_PACKAGES = ("Pillow", "requests", "ddgs")


def in_colab() -> bool:
    return "google.colab" in sys.modules or (Path("/content").is_dir() and "COLAB_RELEASE_TAG" in os.environ)


# --------------------------------------------------------------------------
# bootstrap
# --------------------------------------------------------------------------
def _run(command: list[str], *, quiet: bool = True) -> tuple[int, str]:
    process = subprocess.run(command, capture_output=True, text=True)
    output = (process.stdout + process.stderr).strip()
    if not quiet and output:
        print(output)
    return process.returncode, output


def bootstrap(
    target: Path | str | None = None,
    *,
    repo_url: str = REPO_URL,
    branch: str = REPO_BRANCH,
    install: bool = True,
    minimal: bool = True,
    quiet: bool = True,
) -> dict[str, Any]:
    """Fetch this repository and make ``archivist`` importable.

    Idempotent: an existing checkout is fast-forwarded instead of re-cloned, and
    only the packages a headless run needs are installed (the UI stack is not
    downloaded for a notebook that never opens it).
    """
    report: dict[str, Any] = {"repo": repo_url, "branch": branch, "installed": []}

    here = Path(target) if target else Path.cwd()
    local: Path | None = None
    for candidate in (here, here.parent, Path.cwd(), Path.cwd().parent):
        if (candidate / "archivist").is_dir():
            local = candidate
            break

    if local is not None:
        report["source"] = "local checkout"
    else:
        path = Path(target or ("/content/archivist-src" if Path("/content").is_dir() else Path.cwd() / "archivist-src"))
        if (path / ".git").is_dir():
            _run(["git", "-C", str(path), "fetch", "--depth", "1", "origin", branch], quiet=quiet)
            code, output = _run(["git", "-C", str(path), "reset", "--hard", f"origin/{branch}"], quiet=quiet)
            report["source"] = "updated existing checkout" if code == 0 else f"update failed: {output[:200]}"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            code, output = _run(
                ["git", "clone", "--depth", "1", "--branch", branch, repo_url, str(path)], quiet=quiet
            )
            if code != 0:
                raise RuntimeError(f"could not clone {repo_url} ({branch}): {output[:300]}")
            report["source"] = "cloned"
        local = path

    report["path"] = str(local)
    if str(local) not in sys.path:
        sys.path.insert(0, str(local))

    code, commit = _run(["git", "-C", str(local), "rev-parse", "--short", "HEAD"], quiet=True)
    report["commit"] = commit if code == 0 else "unknown"

    if install:
        missing = _missing_packages(minimal)
        if missing:
            _run([sys.executable, "-m", "pip", "install", "-q", *missing], quiet=quiet)
            report["installed"] = missing
    return report


def _missing_packages(minimal: bool) -> list[str]:
    import importlib.util

    modules = {"Pillow": "PIL", "requests": "requests", "ddgs": "ddgs", "gradio": "gradio"}
    wanted = list(MINIMAL_PACKAGES) if minimal else list(MINIMAL_PACKAGES) + ["gradio"]
    return [name for name in wanted if importlib.util.find_spec(modules[name]) is None]


# --------------------------------------------------------------------------
# secrets
# --------------------------------------------------------------------------
@dataclass
class SecretStatus:
    name: str
    present: bool
    source: str          # colab secret | parameter cell | environment | .env | missing
    needed_for: str
    without_it: str

    @property
    def badge(self) -> str:
        return "🟢" if self.present else ("🔴" if self.name in REQUIRED_FOR_IMAGES else "🟡")


def _colab_secret(name: str) -> str:
    try:
        from google.colab import userdata  # type: ignore

        return str(userdata.get(name) or "").strip()
    except Exception:
        return ""


def load_secrets(
    overrides: dict[str, str] | None = None,
    *,
    use_colab_secrets: bool = True,
    root: Path | str = ".",
    persist: bool = False,
) -> list[SecretStatus]:
    """Resolve every key once, in a fixed order, without printing any value.

    Order: the parameter cell wins (you typed it deliberately), then Colab
    Secrets, then whatever is already in the environment, then ``.env``.
    """
    from .config import load_env

    overrides = {key: str(value or "").strip() for key, value in (overrides or {}).items()}
    file_values = load_env(root)
    statuses: list[SecretStatus] = []

    for name, needed_for, without_it in SECRET_SPECS:
        value, source = "", "missing"
        if overrides.get(name):
            value, source = overrides[name], "parameter cell"
        elif use_colab_secrets and (secret := _colab_secret(name)):
            value, source = secret, "colab secret"
        elif os.environ.get(name, "").strip() and name not in file_values:
            value, source = os.environ[name].strip(), "environment"
        elif file_values.get(name, "").strip():
            value, source = file_values[name].strip(), ".env"
        elif os.environ.get(name, "").strip():
            value, source = os.environ[name].strip(), "environment"

        if value:
            os.environ[name] = value
        statuses.append(SecretStatus(name, bool(value), source, needed_for, without_it))

    if persist:
        write_env({status.name: os.environ.get(status.name, "") for status in statuses if status.present}, root)
    return statuses


def write_env(values: dict[str, str], root: Path | str = ".") -> Path:
    """Merge keys into .env, preserving everything already there."""
    path = Path(root) / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in values and values[key]:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    out.extend(f"{key}={value}" for key, value in values.items() if key not in seen and value)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return path


def secret_table(statuses: Iterable[SecretStatus]) -> str:
    """A readable status table. Values never appear — only where they came from."""
    statuses = list(statuses)
    rows = ["| key | state | source | needed for |", "|---|---|---|---|"]
    for status in statuses:
        rows.append(
            f"| `{status.name}` | {status.badge} {'set' if status.present else 'not set'} "
            f"| {status.source} | {status.needed_for} |"
        )
    missing = [status for status in statuses if not status.present]
    if missing:
        rows.append("")
        rows.append("What is missing changes, but never breaks, the run:")
        rows.extend(f"- **{status.name}** — {status.without_it}" for status in missing)
    return "\n".join(rows)


def capability_line(statuses: Iterable[SecretStatus], *, offline: bool) -> str:
    have = {status.name for status in statuses if status.present}
    if offline:
        return "⚪ offline mode — synthetic signals and a synthesised frame; no network, no spend"
    if "BFL_API_KEY" not in have:
        return "🟡 no BFL key — the run will stop after the prompt contract; nothing will be rendered"
    if "OPENAI_API_KEY" not in have:
        return ("🟡 no OpenAI key — market truth cannot be audited, so live generation stays "
                "blocked. Research artefacts are still written.")
    return "🟢 ready — discovery, creative route, one paid generation, visual critic, delivery"


# --------------------------------------------------------------------------
# recovery
# --------------------------------------------------------------------------
def find_recoverable_raw(runs_dir: Path | str) -> Path | None:
    """The newest paid frame from a run that never produced a final.

    An interrupted run has already been charged for; re-running the notebook with
    this path costs nothing extra.
    """
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return None
    candidates = sorted(runs_dir.glob("*/*/artwork/*_raw.png"), key=lambda path: path.stat().st_mtime, reverse=True)
    for candidate in candidates:
        if not (candidate.parent.parent / "final").is_dir():
            return candidate
    return None


# --------------------------------------------------------------------------
# presentation
# --------------------------------------------------------------------------
def contract_lines(route: dict[str, Any], discovery: dict[str, Any] | None = None) -> list[str]:
    """The creative contract, as one readable block."""
    discovery = discovery or {}
    intent = (route.get("intent_validation") or {}).get("dominant_intent", "—")
    silhouette = (route.get("silhouette") or {}).get("label", "—")
    lines = [
        f"{'market signal':<20}: {route.get('market_signal')}",
        f"{'chosen by':<20}: {discovery.get('chosen_by', 'user topic')}",
        f"{'dominant intent':<20}: {intent}",
        f"{'evidence subject':<20}: {route.get('real_subject')}",
        f"{'true property':<20}: {route.get('source_property')}",
        f"{'artistic world':<20}: {route.get('artistic_topic')}",
        f"{'single mutation':<20}: {route.get('mutation')}",
        f"{'silhouette':<20}: {silhouette}",
        f"{'hero motif':<20}: {route.get('hero_motif')}",
        f"{'interruption':<20}: {route.get('signature_interruption')}",
        f"{'statement':<20}: {route.get('statement')}",
        f"{'statement lockup':<20}: {route.get('statement_lockup')}",
        f"{'placement':<20}: {route.get('placement_logic')}",
        f"{'palette':<20}: {', '.join(route.get('palette', []))}",
        f"{'conditioning':<20}: owned blueprint only; searched pixels are research-only",
    ]
    if discovery.get("relative_volume"):
        lines.insert(2, f"{'relative volume':<20}: {discovery['relative_volume']} (benchmark archive = 100)")
    return lines


def proof_lines(delivery) -> list[str]:
    """The measured proof behind an approved candidate."""
    if delivery is None:
        return ["no candidate was rendered"]
    measured = delivery.selected.get("measured", {})
    statement = delivery.selected.get("statement_spec", {})
    review = delivery.selected.get("visual_review", {}) or {}
    lines = [
        f"{'paid generations':<20}: {delivery.paid_calls}",
        f"{'hard checks':<20}: " + ", ".join(
            f"{name} {'ok' if value else 'FAIL'}" for name, value in measured.get("hard_checks", {}).items()
        ),
        f"{'asymmetry / shift':<20}: {measured.get('asymmetry')} / {measured.get('mass_shift')}",
        f"{'hero envelope':<20}: {measured.get('hero_envelope_ratio')}",
        f"{'ink coverage':<20}: {measured.get('ink_coverage')}% (expected {measured.get('expected_ink_range')})",
        (f"{'statement':<20}: {statement.get('cap_height_mm')}mm cap height, "
         f"contrast {statement.get('contrast_ratio')}:1") if statement.get("applied")
        else f"{'statement':<20}: none — this design carries no copy, which is a finished state",
        f"{'heuristic total':<20}: {measured.get('heuristic_total')}",
    ]
    if review:
        lines.append(f"{'vision critic':<20}: total {review.get('total', '—')} — {str(review.get('reason', ''))[:120]}")
    elif not delivery.selected.get("vision_reviewed"):
        lines.append(f"{'vision critic':<20}: not run — approved on the deterministic proof alone")
    return lines


def preview_images(result) -> list[tuple[str, str]]:
    """(path, caption) for whatever there is to look at — approved or not."""
    pairs: list[tuple[str, str]] = []
    if getattr(result, "delivery", None):
        final = Path(result.delivery.final_dir)
        printed = bool((result.delivery.selected.get("statement_spec") or {}).get("applied"))
        for name, caption in (
            ("FINAL_mockup.png", "garment proof"),
            ("FINAL_artwork.png",
             "composed artwork with the typeset statement" if printed else "composed artwork"),
            ("FINAL_print.png", "print file"),
            ("FINAL_blueprint.png", "the owned blueprint that conditioned generation"),
        ):
            if (final / name).is_file():
                pairs.append((str(final / name), caption))
        return pairs

    # Rejected or unrendered: show whatever the run did produce, so the failure
    # is visible rather than described.
    run_result = getattr(result, "result", None)
    if run_result is not None:
        run_dir = Path(run_result.run_dir)
        for path in sorted(run_dir.glob("artwork/*.png")):
            pairs.append((str(path), path.stem))
        blueprint = run_dir / "blueprint" / "house_blueprint.png"
        if blueprint.is_file():
            pairs.append((str(blueprint), "owned blueprint"))
    return pairs


def package_delivery(result, output_dir: Path | str = ".") -> Path | None:
    """One zip to download: the approved delivery, or the rejection diagnosis."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if getattr(result, "rejected", "") and Path(result.rejected).is_file():
        destination = output_dir / Path(result.rejected).name
        if Path(result.rejected).resolve() != destination.resolve():
            shutil.copy2(result.rejected, destination)
        return destination

    if not getattr(result, "delivery", None):
        return None

    final = Path(result.delivery.final_dir)
    title = str(result.route.get("product_title", "delivery")).lower().replace(" ", "-")
    destination = output_dir / f"ARCHIVIST_{title}.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(final.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(final))
    return destination


def download(path: Path | str) -> bool:
    """Hand the file to the browser in Colab; a no-op anywhere else."""
    try:
        from google.colab import files  # type: ignore

        files.download(str(path))
        return True
    except Exception:
        return False
