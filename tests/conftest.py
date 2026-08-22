from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from archivist.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    """Offline settings pointed at a temp directory — no network, no keys."""
    for key in ("BFL_API_KEY", "PEXELS_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ARCHIVIST_OFFLINE", "1")
    return Settings.from_env(
        tmp_path,
        runs_dir=tmp_path / "runs",
        collection="test",
        offline=True,
        max_queries=10,
        candidates_per_query=3,
        max_candidates=15,
        keep_references=6,
        request_delay=0.0,
    )
