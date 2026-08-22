"""``python -m archivist`` → the CLI. ``python -m archivist.app`` → the UI."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
