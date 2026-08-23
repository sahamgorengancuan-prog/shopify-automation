---
title: Archivist
emoji: 🗄️
colorFrom: gray
colorTo: indigo
sdk: gradio
sdk_version: 6.25.0
app_file: space_app.py
pinned: false
---

# ARCHIVIST

Trend research → reference mining → BFL Context → apparel graphics.

Set `BFL_API_KEY` (and optionally `PEXELS_API_KEY`, `OPENAI_API_KEY`, plus the
Reddit/X/Meta discovery credentials) as Space secrets. Without them the Space still runs in offline mode with synthetic
references, which is enough to see the whole pipeline work.

Note: Space storage is ephemeral unless persistent storage is enabled — attach a
disk and point `ARCHIVIST_RUNS_DIR` at it if you want the collection style lock
and run history to survive a restart.
