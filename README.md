# ARCHIVIST

**Trend research → reference mining → BFL Context → apparel graphics.**

A pipeline that turns a topic into a wearable graphic the way an art director would:
it escalates the topic into a micro-niche, searches for *visual ingredients* rather
than finished designs, measures every reference it finds, gives each one a single job
(composition, texture, typography behaviour, palette, mood), synthesises a named art
direction, locks that direction to the collection, and only then generates artwork —
followed by a print package a printer can actually take.

Everything is driven from one Gradio control room: setup, connection tests, running,
monitoring, scheduling and deployment.

```
┌──────────┐   ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌─────────┐   ┌────────┐
│  topic   │──▶│ queries │──▶│ mining + │──▶│ scoring  │──▶│ visual  │──▶│  art   │
│ → niche  │   │ 6 clus- │   │ measure- │   │ + roles  │   │  DNA    │   │ direc- │
│  ladder  │   │  ters   │   │  ment    │   │          │   │         │   │ tion   │
└──────────┘   └─────────┘   └──────────┘   └──────────┘   └─────────┘   └───┬────┘
                                                                             │
      ┌────────────┐   ┌──────────┐   ┌─────────────┐   ┌──────────────┐    │
      │  print     │◀──│ BFL      │◀──│ prompts +   │◀──│ A / B / C    │◀───┘
      │  package   │   │ Context  │   │ quality gate│   │ ranked       │
      └────────────┘   └──────────┘   └─────────────┘   └──────────────┘
```

---

## Start in three minutes

**Ubuntu 24.04**

```bash
./scripts/linux/archivist.sh setup     # venv + dependencies
./scripts/linux/archivist.sh app       # http://127.0.0.1:7860
```

**Windows (Python 3.14)**

Unzip `dist/archivist-windows-py314.zip`, then double-click `run_archivist.bat`.
It finds `py -3.14`, or any Python 3.10+, or downloads the embeddable Python 3.14 —
you do not have to install anything first.

**Notebook**

`notebooks/archivist_pipeline.ipynb` runs the same code stage by stage, with the
control room embedded in the last cell.

**No API keys?** Turn on **Offline mode**. The whole pipeline runs against
procedurally generated references — the fastest way to understand it before spending
credits.

---

## The control room

| tab | what it is for |
|---|---|
| **① Setup** | paste keys, choose collection / garment / print size; writes `.env` for you |
| **② Connection** | probes Python, disk, DuckDuckGo, Pexels, BFL and the OpenAI creative assist, with plain-language failures |
| **③ Studio** | run the pipeline with a live log, reference board, ranked directions, prompts, artwork and print package |
| **④ Monitor** | every past run: report, assets, log, disk use; delete or reopen any of them |
| **⑤ Auto-plan** | turn one theme into a scheduled collection; start/stop the scheduler, run jobs now, watch history |
| **⑥ Deploy** | write a Dockerfile, compose file, systemd unit, Windows task and HF Space entry point, filled in with your port and paths |

---

## What each stage actually decides

| stage | module | decision |
|---|---|---|
| 1 | `trends` | trend → generic → better → niche → **micro-niche**, plus the cultural signals behind it |
| 2 | `queries` | 10–30 searches across six clusters; near-duplicates rejected by token overlap |
| 3 | `mining` | candidates from DuckDuckGo + Pexels (or the offline generator), de-duplicated by perceptual hash |
| 4 | `analysis` | contrast, grain, edge density, tonal split, colourfulness, structure, type-likeness, palette — measured with Pillow, not guessed |
| 5 | `scoring` | six weighted axes: subject .20, distinctiveness .20, composition .15, style .20, commercial .15, originality .10 |
| 6 | `roles` | one role per reference, assigned by role-specific fitness with a swap-improvement pass |
| 7 | `dna` | the Visual DNA profile, every clause traceable to a measurement |
| 8–9 | `direction` | a named art direction, saved as the collection's **style lock** |
| 10 | `variations` | A safe commercial / B niche cultural / C extreme experimental, ranked |
| 11 | `prompts`, `gate` | structured BFL Context prompt; eight-category gate, a fail forces a two-axis mutation |
| 12 | `bfl` | generation with the references attached as context images |
| 13 | `apparel` | transparent 300 dpi print file, separation preview, ink report, three-metre legibility check, mockup |
| 14 | `board`, `brief` | reference board, creative brief, run report |

### Why the output is not a collage

Each reference contributes exactly one named property and the prompt says so
explicitly — *"contribute grain structure and ink break-up; do not reproduce its
content"*. Roles are unique, so nothing competes for the same job, and the negative
constraints forbid copied compositions, brand marks and reproduced artwork.

### Why a collection looks like a collection

The first run in a collection writes `runs/<collection>/style_lock.json`; every later
run inherits its composition philosophy, texture language, typography behaviour,
colour discipline, print degradation and palette. Subjects change, the visual language
does not.

---

## Command line

```bash
python -m archivist app --port 7860 --scheduler   # the control room
python -m archivist run "deep sea salvage" --garment dark
python -m archivist run "deep sea salvage" --no-generate      # prompts only
python -m archivist check                                     # connection self-test
python -m archivist queries "cold war radio jamming"          # see the search plan
python -m archivist plan "north sea oil" -n 6 --create        # auto-plan a collection
python -m archivist serve-scheduler                           # headless scheduler
python -m archivist runs                                      # run history
python -m archivist deploy --port 7860                        # deployment artefacts
```

## What a run leaves behind

```
runs/<collection>/<timestamp>-<topic>/
├── manifest.json          the whole run, machine-readable (never contains keys)
├── report.md              scores, gate verdicts, mutations, prompts
├── board.md / board.html  the reference board with sources and attribution
├── brief_<A|B|C>.md       creative brief per direction
├── queries.json           every search that was run
├── references/            mined images + thumbnails
├── prompts/               BFL prompt and negative constraints per direction
├── artwork/               generated frames
├── print/                 print file, separation, legibility check, mockup
└── run.log                timestamped stage log
runs/<collection>/style_lock.json    the collection's visual identity — back this up
runs/_scheduler/jobs.json            scheduled jobs and their history
```

## Configuration

Every setting is an environment variable or a field in the Setup tab — see
[`.env.example`](.env.example). The ones that matter most:

| variable | default | meaning |
|---|---|---|
| `BFL_API_KEY` | — | required to generate artwork |
| `BFL_MODEL` | `flux-kontext-max` | Kontext models accept the references as context images |
| `OPENAI_API_KEY` | — | optional creative assist |
| `OPENAI_MODEL` | `gpt-5.1` | model used for that assist |
| `ARCHIVIST_COLLECTION` | `default` | collections share a style lock |
| `ARCHIVIST_OFFLINE` | `0` | `1` = synthetic references, no network, no spend |
| `ARCHIVIST_SEED` | `0` | non-zero makes a run reproducible |
| `ARCHIVIST_PRINT_WIDTH_IN` / `_DPI` | `12` / `300` | print file size |

## Deploy

The Deploy tab (or `python -m archivist deploy`) writes:

```bash
docker compose -f deploy/docker-compose.yml up -d --build
sudo cp deploy/archivist.service /etc/systemd/system/ && sudo systemctl enable --now archivist
schtasks /Create /TN ARCHIVIST /XML deploy\windows-task.xml
```

Mount `runs/` on a volume — it holds the style lock. Put the app behind
`--auth user:password` or a reverse proxy before exposing it: it holds API keys and
the scheduler can spend credits on a timer.

## Tests

```bash
./scripts/linux/archivist.sh test      # or: python -m pytest -q tests
```

33 tests cover every stage offline: query variety, measurement, scoring, role
uniqueness, style-lock persistence, prompt structure, the competitor check and its
mutations, print output, scheduler cadences, `.env` handling and the app surface. No
network, no keys, no credits.

## Requirements

Python 3.10+ (3.14 targeted on Windows), `gradio`, `Pillow`, `requests`. Optional:
`ddgs` (tracks DuckDuckGo endpoint changes), `python-dotenv`.

External services: **BFL** for generation, **Pexels** for photography (optional),
**OpenAI GPT-5.1** for the creative assist (optional). The assist is called through
the Responses API, falling back to Chat Completions for OpenAI-compatible gateways.

## Using it responsibly

References are ingredients, never targets: nothing mined is reproduced in the output.
Check licensing before commercial use and keep the Pexels attribution the board
records. Keep recognisable brands, logos, trademarks and real people out of what you
print — the negative constraints push against them, but the final call is yours.
