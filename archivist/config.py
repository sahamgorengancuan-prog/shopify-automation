"""Configuration and environment handling.

No hard dependency on python-dotenv: a tiny parser keeps the Windows bundle and
the Ubuntu script free of one more install step, but if python-dotenv happens to
be present it is used first so that its escaping rules win.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ENV_FILES = (".env", ".env.local")

# Keys that must never be echoed into a manifest, a log line or a notebook cell.
SECRET_KEYS = (
    "BFL_API_KEY", "PEXELS_API_KEY", "OPENAI_API_KEY",
    "REDDIT_CLIENT_SECRET", "X_BEARER_TOKEN", "META_ACCESS_TOKEN",
)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(root: Path | str = ".", files: tuple[str, ...] = DEFAULT_ENV_FILES) -> dict[str, str]:
    """Load .env files into ``os.environ`` without overwriting real env vars."""
    root = Path(root)
    loaded: dict[str, str] = {}
    for name in files:
        path = root / name
        if not path.is_file():
            continue
        try:  # optional, better quoting rules than the fallback parser
            from dotenv import dotenv_values  # type: ignore

            values = {k: v for k, v in dotenv_values(path).items() if v is not None}
        except Exception:
            values = _parse_env_file(path)
        for key, value in values.items():
            loaded[key] = value
            os.environ.setdefault(key, value)
    return loaded


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    """Everything the pipeline needs to know about its environment."""

    # --- credentials -----------------------------------------------------
    bfl_api_key: str = ""
    pexels_api_key: str = ""
    openai_api_key: str = ""

    # --- endpoints / models ---------------------------------------------
    bfl_base_url: str = "https://api.bfl.ai"
    bfl_model: str = "flux-kontext-max"
    bfl_fallback_model: str = "flux-pro-1.1-ultra"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.1"
    openai_reasoning_effort: str = "low"

    # --- discovery credentials (all optional) ----------------------------
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "archivist/1.0 (trend discovery)"
    x_bearer_token: str = ""
    meta_access_token: str = ""
    meta_ig_user_id: str = ""

    # --- discovery behaviour ---------------------------------------------
    trends_geo: str = "US"
    trends_timeframe: str = "today 3-m"
    discovery_min_growth: float = 25.0
    discovery_max_competition: float = 70.0
    discovery_min_social: float = 12.0
    discovery_candidates: int = 24
    discovery_keep: int = 6
    autopilot_designs: int = 1
    reddit_allow_anonymous: bool = True

    # --- house system (V9) ------------------------------------------------
    house_paid_budget: int = 1            # paid generations per design, 1 or 2
    house_allow_controlled_edit: bool = False
    house_allow_concept_retry: bool = False
    house_require_critic: bool = True
    house_print_statement: bool = True
    house_anchor: str = "auto"            # auto | upper-left | upper-right | low-left | low-right
    house_statement_override: str = ""

    # --- mining ----------------------------------------------------------
    max_queries: int = 24
    candidates_per_query: int = 6
    max_candidates: int = 60
    keep_references: int = 8
    min_reference_score: float = 5.5
    request_delay: float = 0.8
    http_timeout: int = 45
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    )

    # --- generation ------------------------------------------------------
    aspect_ratio: str = "3:4"
    output_format: str = "png"
    safety_tolerance: int = 2
    poll_interval: float = 2.0
    poll_timeout: int = 300

    # --- print -----------------------------------------------------------
    print_width_in: float = 12.0
    print_dpi: int = 300
    garment: str = "dark"  # dark | light — drives the knockout direction

    # --- housekeeping ----------------------------------------------------
    collection: str = "default"
    runs_dir: Path = field(default_factory=lambda: Path("runs"))
    cache_dir: Path = field(default_factory=lambda: Path(".cache/archivist"))
    offline: bool = False
    seed: int = 0

    @classmethod
    def from_env(cls, root: Path | str = ".", **overrides) -> "Settings":
        load_env(root)
        settings = cls(
            bfl_api_key=os.environ.get("BFL_API_KEY", "").strip(),
            pexels_api_key=os.environ.get("PEXELS_API_KEY", "").strip(),
            openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
            bfl_base_url=os.environ.get("BFL_BASE_URL", "https://api.bfl.ai").rstrip("/"),
            bfl_model=os.environ.get("BFL_MODEL", "flux-kontext-max").strip(),
            bfl_fallback_model=os.environ.get("BFL_FALLBACK_MODEL", "flux-pro-1.1-ultra").strip(),
            openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-5.1").strip(),
            openai_reasoning_effort=os.environ.get("OPENAI_REASONING_EFFORT", "low").strip(),
            reddit_client_id=os.environ.get("REDDIT_CLIENT_ID", "").strip(),
            reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET", "").strip(),
            reddit_user_agent=os.environ.get("REDDIT_USER_AGENT", "archivist/1.0 (trend discovery)").strip(),
            x_bearer_token=os.environ.get("X_BEARER_TOKEN", "").strip(),
            meta_access_token=os.environ.get("META_ACCESS_TOKEN", "").strip(),
            meta_ig_user_id=os.environ.get("META_IG_USER_ID", "").strip(),
            trends_geo=os.environ.get("ARCHIVIST_TRENDS_GEO", "US").strip(),
            trends_timeframe=os.environ.get("ARCHIVIST_TRENDS_TIMEFRAME", "today 3-m").strip(),
            discovery_min_growth=_float("ARCHIVIST_MIN_GROWTH", 25.0),
            discovery_max_competition=_float("ARCHIVIST_MAX_COMPETITION", 70.0),
            discovery_min_social=_float("ARCHIVIST_MIN_SOCIAL", 12.0),
            discovery_candidates=_int("ARCHIVIST_DISCOVERY_CANDIDATES", 24),
            discovery_keep=_int("ARCHIVIST_DISCOVERY_KEEP", 6),
            autopilot_designs=_int("ARCHIVIST_AUTOPILOT_DESIGNS", 1),
            reddit_allow_anonymous=_bool("ARCHIVIST_REDDIT_ANONYMOUS", True),
            house_paid_budget=_int("ARCHIVIST_PAID_BUDGET", 1),
            house_allow_controlled_edit=_bool("ARCHIVIST_ALLOW_CONTROLLED_EDIT", False),
            house_allow_concept_retry=_bool("ARCHIVIST_ALLOW_CONCEPT_RETRY", False),
            house_require_critic=_bool("ARCHIVIST_REQUIRE_CRITIC", True),
            house_print_statement=_bool("ARCHIVIST_PRINT_STATEMENT", True),
            house_anchor=os.environ.get("ARCHIVIST_ANCHOR", "auto").strip() or "auto",
            house_statement_override=os.environ.get("ARCHIVIST_STATEMENT", "").strip(),
            max_queries=_int("ARCHIVIST_MAX_QUERIES", 24),
            candidates_per_query=_int("ARCHIVIST_CANDIDATES_PER_QUERY", 6),
            max_candidates=_int("ARCHIVIST_MAX_CANDIDATES", 60),
            keep_references=_int("ARCHIVIST_KEEP_REFERENCES", 8),
            min_reference_score=_float("ARCHIVIST_MIN_REFERENCE_SCORE", 5.5),
            request_delay=_float("ARCHIVIST_REQUEST_DELAY", 0.8),
            http_timeout=_int("ARCHIVIST_HTTP_TIMEOUT", 45),
            aspect_ratio=os.environ.get("ARCHIVIST_ASPECT_RATIO", "3:4").strip(),
            output_format=os.environ.get("ARCHIVIST_OUTPUT_FORMAT", "png").strip(),
            safety_tolerance=_int("ARCHIVIST_SAFETY_TOLERANCE", 2),
            poll_interval=_float("ARCHIVIST_POLL_INTERVAL", 2.0),
            poll_timeout=_int("ARCHIVIST_POLL_TIMEOUT", 300),
            print_width_in=_float("ARCHIVIST_PRINT_WIDTH_IN", 12.0),
            print_dpi=_int("ARCHIVIST_PRINT_DPI", 300),
            garment=os.environ.get("ARCHIVIST_GARMENT", "dark").strip().lower(),
            collection=os.environ.get("ARCHIVIST_COLLECTION", "default").strip() or "default",
            runs_dir=Path(os.environ.get("ARCHIVIST_RUNS_DIR", "runs")),
            cache_dir=Path(os.environ.get("ARCHIVIST_CACHE_DIR", ".cache/archivist")),
            offline=_bool("ARCHIVIST_OFFLINE", False),
            seed=_int("ARCHIVIST_SEED", 0),
        )
        for key, value in overrides.items():
            if value is None:
                continue
            if not hasattr(settings, key):
                raise AttributeError(f"unknown setting: {key}")
            setattr(settings, key, value)
        return settings

    # -- capability probes ------------------------------------------------
    @property
    def can_generate(self) -> bool:
        return bool(self.bfl_api_key) and not self.offline

    @property
    def can_use_pexels(self) -> bool:
        return bool(self.pexels_api_key) and not self.offline

    @property
    def can_use_llm(self) -> bool:
        return bool(self.openai_api_key) and not self.offline

    @property
    def social_sources(self) -> list[str]:
        """Which social platforms can actually be measured right now."""
        if self.offline:
            return ["offline"]
        active = ["reddit"]  # reddit answers anonymously, if the IP is not blocked
        if self.x_bearer_token:
            active.append("x")
        if self.meta_access_token and self.meta_ig_user_id:
            active.append("meta")
        return active

    def capability_report(self) -> dict[str, str]:
        def state(ok: bool, key: str) -> str:
            if self.offline:
                return "offline mode — synthetic references, no network"
            return "ready" if ok else f"missing {key} (stage degrades, pipeline still runs)"

        return {
            "duckduckgo": "offline mode" if self.offline else "ready (no key required)",
            "pexels": state(bool(self.pexels_api_key), "PEXELS_API_KEY"),
            "bfl": state(bool(self.bfl_api_key), "BFL_API_KEY"),
            "llm_assist": state(bool(self.openai_api_key), "OPENAI_API_KEY"),
            "google_trends": "offline mode" if self.offline else "ready (no key required)",
            "reddit": (
                "offline mode" if self.offline
                else "ready (oauth)" if self.reddit_client_id and self.reddit_client_secret
                else "anonymous — set REDDIT_CLIENT_ID/SECRET if your IP is blocked"
            ),
            "x": state(bool(self.x_bearer_token), "X_BEARER_TOKEN"),
            "meta": state(bool(self.meta_access_token and self.meta_ig_user_id), "META_ACCESS_TOKEN"),
        }

    def redacted(self) -> dict[str, object]:
        out: dict[str, object] = {}
        for key, value in vars(self).items():
            if key in {
                "bfl_api_key", "pexels_api_key", "openai_api_key",
                "reddit_client_id", "reddit_client_secret", "x_bearer_token",
                "meta_access_token", "meta_ig_user_id",
            }:
                out[key] = "set" if value else "unset"
            elif isinstance(value, Path):
                out[key] = str(value)
            else:
                out[key] = value
        return out
