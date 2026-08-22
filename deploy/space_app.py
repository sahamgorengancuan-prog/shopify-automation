"""Hugging Face Space entry point."""

import os

from archivist.app import build_app

os.environ.setdefault("ARCHIVIST_RUNS_DIR", os.environ.get("ARCHIVIST_RUNS_DIR", "runs"))

demo = build_app()

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
