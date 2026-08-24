# ARCHIVIST

**An autonomous apparel-design bot.** Nobody types a topic.

It reads Google Trends for what is rising, Reddit / X / Meta for whether anyone
actually cares, and DuckDuckGo for how crowded the apparel market already is.
It throws out everything it must not print, scores what survives, works out which
survivors are the same cultural wave — and only then does the design work:
reference mining, Visual DNA, a named art direction, three ranked concepts, BFL
Context generation, and a print package a printer can take.

Everything runs from one Gradio control room: setup, connection tests,
discovery, autopilot, monitoring, scheduling and deployment.

```
 ─────────────────────────── the bot decides what to make ───────────────────────────
┌───────────────┐  ┌──────────────┐  ┌───────────────┐  ┌──────────────┐  ┌─────────┐
│ Google Trends │  │ Reddit / X / │  │  DuckDuckGo   │  │  screening   │  │ scoring │
│ trending now  │─▶│ Meta         │─▶│ marketplace   │─▶│ trademark /  │─▶│ + corre-│
│ rising +3m %  │  │ heat, eng/   │  │ listing       │  │ likeness /   │  │ lation  │
│ interest      │  │ post, views  │  │ density       │  │ tragedy      │  │ + GPT   │
└───────────────┘  └──────────────┘  └───────────────┘  └──────────────┘  └────┬────┘
                                                                               │
 ──────────────────────────── then it makes the thing ─────────────────────────┼─────
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐  ┌────────┐  ┌────────┐  │
│ queries  │─▶│ mining + │─▶│ scoring  │─▶│ visual  │─▶│  art   │─▶│ A/B/C  │◀─┘
│ 6 clus-  │  │ measure- │  │ + roles  │  │  DNA    │  │ direc- │  │ ranked │
│ ters     │  │ ment     │  │          │  │         │  │ tion   │  │ + gate │
└──────────┘  └──────────┘  └──────────┘  └─────────┘  └────────┘  └───┬────┘
                                     ┌──────────┐  ┌──────────────┐    │
                                     │  print   │◀─│ BFL Context  │◀───┘
                                     │  package │  │ (references  │
                                     └──────────┘  │  as context) │
                                                   └──────────────┘
```

---

## Start in three minutes

**Ubuntu 24.04**

```bash
./scripts/linux/archivist.sh setup     # venv + dependencies
./scripts/linux/archivist.sh app       # http://127.0.0.1:7860
```

**Windows (Python 3.14)**

Unzip `dist/archivist-windows-py314.zip`, double-click `run_archivist.bat`. It
finds `py -3.14`, or any Python 3.10+, or downloads the embeddable Python 3.14 —
nothing to install first.

**Notebook** — `notebooks/archivist_pipeline.ipynb` runs the same code stage by
stage, with the control room embedded in the last cell.

Then open **③ Discovery** and press **Run autopilot now**. That is the whole
product: it finds a topic and designs it.

**No API keys?** Tick **Offline mode**. Discovery runs on synthetic signals and
the design pipeline on procedurally generated references — the fastest way to
see the entire loop before spending anything.

---

## How the bot chooses a topic

| stage | source | what it produces |
|---|---|---|
| harvest | Google Trends `trending/rss`, rising related queries around neutral anchors, (with GPT) topics extracted from hot Reddit posts | raw candidate terms |
| screen | rules | drops trademarks, franchises, live news, tragedy, politics, health claims, and anything that reads as a person's name |
| measure | Google Trends interest-over-time | **growth over the last 3 months**, momentum, mean interest, peak ratio, breakout flag |
| measure | Reddit (anon or OAuth), X API v2, Instagram Graph | **social heat 0–100**, **average engagement per post**, estimated views, subreddit spread, freshness |
| measure | DuckDuckGo | **competition 0–100** — how many of the top results for `"<topic>" t shirt` are live Redbubble / Etsy / TeePublic / Amazon listings, plus design saturation in image search |
| score | weighted | growth .28 · social .20 · engagement .15 · competition gap .22 · apparel fit .10 · cross-source confirmation .05 |
| correlate | Pearson on first differences + shared vocabulary | groups co-moving topics into **families**, so a collection is one wave and not ten unrelated shirts |
| judge | GPT-5.1 (optional) | wearability 0–10, a design angle, audience, `fad / seasonal / lasting`, rights risk, drop-with-reason |

**Hard filters** (all configurable in the UI): growth ≥ 25%, competition ≤ 70,
social heat ≥ 12, at least two independent sources that actually answered. A
topic that fails is not a low score — it is rejected, with the reason recorded so
you can audit it.

Everything the bot measured travels with the design: `manifest.json` carries the
raw signals, so a run can still answer *why this subject* long after the trend
has moved on.

### What it refuses to print

Google's trending page is mostly celebrities, sports fixtures, breaking news and
brands — exactly what an autonomous printer must not touch. Screening drops
those before they are ever measured, and GPT re-checks the survivors for
likeness and trademark risk. Rejections are listed in the UI with their category.

---

## The control room

| tab | what it is for |
|---|---|
| **① Setup** | keys (BFL, OpenAI, Pexels, Reddit, X, Meta), geo, collection, garment, print size; writes `.env` |
| **② Connection** | probes Python, disk, Google Trends, Reddit, X, Meta, DuckDuckGo, Pexels, BFL and GPT, with plain-language failures |
| **③ Discovery** | find opportunities with live evidence per topic — or **Run autopilot now** and let it design them |
| **④ Studio** | the design pipeline on one topic: live log, reference board, ranked concepts, prompts, artwork, print package |
| **⑤ Monitor** | every past run: report, assets, log, disk use |
| **⑥ Schedule** | autopilot on a cadence (rediscovers every firing), or a planned collection of topics |
| **⑦ House V9** | the house system end to end: creative route, owned blueprint, one paid image, measured proof, packaged delivery |
| **⑧ Deploy** | Dockerfile, compose, systemd unit, Windows task and HF Space entry point, filled in with your port and paths |

---

## What each design stage decides

| stage | module | decision |
|---|---|---|
| 1 | `trends` | topic → generic → better → niche → **micro-niche**, plus its cultural signals |
| 2 | `queries` | 10–30 searches across six clusters; near-duplicates rejected by token overlap |
| 3 | `mining` | candidates from DuckDuckGo + Pexels, de-duplicated by perceptual hash |
| 4 | `analysis` | contrast, grain, edge density, tonal split, colourfulness, structure, type-likeness, palette — measured with Pillow, not guessed |
| 5 | `scoring` | six weighted axes: subject .20, distinctiveness .20, composition .15, style .20, commercial .15, originality .10 |
| 6 | `roles` | one role per reference, by role-specific fitness with a swap-improvement pass |
| 7 | `dna` | the Visual DNA profile, every clause traceable to a measurement |
| 8–9 | `direction` | a named art direction, saved as the collection's **style lock** |
| 10 | `variations` | A safe commercial / B niche cultural / C extreme experimental, ranked |
| 11 | `prompts`, `gate` | structured BFL Context prompt; eight-category gate, a fail forces a two-axis mutation |
| 12 | `bfl` | generation with the references attached as context images |
| 13 | `apparel` | transparent 300 dpi print file, separation preview, ink report, three-metre legibility check, mockup |
| 14 | `board`, `brief` | reference board, creative brief, run report |

**Why the output is not a collage** — each reference contributes exactly one
named property and the prompt says so: *"contribute grain structure and ink
break-up; do not reproduce its content"*. Roles are unique, and the negative
constraints forbid copied compositions, brand marks and reproduced artwork.

**Why a collection looks like a collection** — the first run writes
`runs/<collection>/style_lock.json`; every later run inherits its composition
philosophy, texture language, typography behaviour, colour discipline and
palette. Subjects change, the visual language does not.

---

## The house system (V9)

Beyond the generic pipeline there is a **house system**: one real material fact,
transformed once, placed off-centre, finished with one printed sentence — and
proved before it ships.

```bash
python -m archivist house                       # discovery → route → art → proof → delivery
python -m archivist house --topic harbor        # skip discovery, keep everything else
python -m archivist house --no-generate         # blueprint, prompt contract and listing only
python -m archivist house --budget 2 --allow-edit          # allow one controlled edit
python -m archivist house --reuse-raw runs/.../B_paid_01_raw.png   # recover, no new spend
python -m archivist volume                      # rank the root pool by relative search volume
```

| guarantee | how |
|---|---|
| **owned conditioning** | only a blueprint this code draws reaches the image model; searched references inform the brief, never the pixels |
| **a nameable subject** | the blueprint carries the subject's silhouette archetype (arm, tower, plate, strata, truss, hull, wall) and the prompt names it — the fix for a real failure where a strong composition read as generic rubble and the critic scored `subject_truth: 3` |
| **real typography** | the statement is typeset from a real font at a measured cap height (≥2.4mm), after generation, and the runtime is proved *before* anything is paid for |
| **budget discipline** | one paid generation by default; a second only for a stated reason — a controlled edit, or a route rebuilt from the critic's own words |
| **no false finals** | a candidate that fails the proof is packaged as `REJECTED_review.zip` with every measurement, not shipped |

### What the proof measures

Deterministic first, and free: asymmetry and mass shift, hero envelope, mode-aware
ink coverage, clean canvas edges, statement contrast and cap height. Only a
candidate that passes all of them is shown to the vision critic, which judges the
pixels on ten axes and must clear 82/100 with no critical score below 8.

Failure classes decide whether money can help at all — `technical` is repaired
locally for free, `local-edit` can be fixed by a controlled edit, and `concept`
means the subject was wrong, so the route is rebuilt before any second call.

### Volume-first discovery

Growth alone finds risers nobody searches for. The house asks demand first: broad
one- and two-word roots are compared in Google Trends against a shared benchmark
(`archive` = 100), which is the only way separate requests are comparable. Trends
throttles freely, so batches retry with backoff and honour `Retry-After`, and if
fewer than 80% of the pool answered the ranking is abandoned rather than chosen
from holes. Only the leading quartile gets the expensive per-topic measurement,
and an intent gate then rejects leaders whose meaning is too ambiguous to design.


---

## Command line

```bash
python -m archivist autopilot                      # discover AND design — the whole bot
python -m archivist autopilot -n 3 --no-generate   # three topics, prompts only
python -m archivist discover -n 8 --rejected       # research only, with what was filtered out
python -m archivist app --port 7860 --scheduler    # the control room + background scheduler
python -m archivist run "deep sea salvage"         # design one topic you chose yourself
python -m archivist check                          # connection self-test
python -m archivist serve-scheduler                # headless: autopilot on a cadence
python -m archivist runs                           # run history
python -m archivist deploy --port 7860             # deployment artefacts
```

## What a run leaves behind

```
runs/_discovery/<timestamp>.json         every candidate, every signal, every rejection
runs/_discovery/latest.json              what the Studio loads as "the best topic on file"
runs/_scheduler/jobs.json                scheduled jobs and their history
runs/<collection>/style_lock.json        the collection's visual identity — back this up
runs/<collection>/<timestamp>-<topic>/
├── manifest.json          the whole run incl. the discovery evidence (never contains keys)
├── report.md              scores, gate verdicts, mutations, prompts
├── board.md / board.html  the reference board with sources and attribution
├── brief_<A|B|C>.md       creative brief per direction
├── queries.json           every search that was run
├── references/            mined images + thumbnails
├── prompts/               BFL prompt and negative constraints per direction
├── artwork/               generated frames
├── print/                 print file, separation, legibility check, mockup
└── run.log                timestamped stage log
```

## Configuration

Every setting is an environment variable or a field in the Setup tab — see
[`.env.example`](.env.example).

| variable | default | meaning |
|---|---|---|
| `BFL_API_KEY` | — | required to generate artwork |
| `OPENAI_API_KEY` | — | optional: judges topics, sharpens the direction (GPT-5.1) |
| `REDDIT_CLIENT_ID` / `_SECRET` | — | optional: use if anonymous Reddit is blocked from your IP |
| `X_BEARER_TOKEN` | — | optional: X API v2 social heat |
| `META_ACCESS_TOKEN` / `META_IG_USER_ID` | — | optional: Instagram hashtag heat |
| `ARCHIVIST_TRENDS_GEO` | `US` | where demand is read from; blank = worldwide |
| `ARCHIVIST_MIN_GROWTH` | `25` | % rise required over the window |
| `ARCHIVIST_MAX_COMPETITION` | `70` | crowding ceiling, 0–100 |
| `ARCHIVIST_MIN_SOCIAL` | `12` | social heat floor, 0–100 |
| `ARCHIVIST_AUTOPILOT_DESIGNS` | `1` | designs produced per autopilot cycle |
| `ARCHIVIST_PAID_BUDGET` | `1` | paid generations per house design |
| `ARCHIVIST_REQUIRE_CRITIC` | `1` | no final without the vision critic |
| `ARCHIVIST_ANCHOR` | `auto` | which corner the hero mass enters from |
| `ARCHIVIST_REDDIT_ANONYMOUS` | `1` | set `0` on cloud IPs that Reddit 403s |
| `ARCHIVIST_COLLECTION` | `default` | collections share a style lock |
| `ARCHIVIST_OFFLINE` | `0` | `1` = synthetic signals and references, no network, no spend |

## Deploy

```bash
docker compose -f deploy/docker-compose.yml up -d --build
sudo cp deploy/archivist.service /etc/systemd/system/ && sudo systemctl enable --now archivist
schtasks /Create /TN ARCHIVIST /XML deploy\windows-task.xml
```

Mount `runs/` on a volume — it holds the style lock and the discovery history.
Put the app behind `--auth user:password` or a reverse proxy before exposing it:
it holds API keys, and an autopilot schedule spends credits on a timer.

## Tests

```bash
./scripts/linux/archivist.sh test      # or: python -m pytest -q tests
```

115 tests, all offline, no keys, no credits: growth and momentum maths, screening
refusals, opportunity thresholds, correlation (including "merely both rising is
not a correlation"), competition counting, Reddit heat, the full discovery cycle,
autopilot writing its evidence into a manifest, scheduler cadences, `.env`
handling, the app surface — and for the house system: statement rules, silhouette
archetypes (including the exact breakwater case that failed), blueprint geometry,
typography legibility, local repair of generated leakage, the proof's hard checks,
budget arithmetic, zero-cost recovery, and the rejection package.

## Requirements

Python 3.10+ (3.14 targeted on Windows), `gradio`, `Pillow`, `requests`.
Optional: `ddgs` (tracks DuckDuckGo endpoint changes), `python-dotenv`.

External services: **Google Trends** and **DuckDuckGo** (no key, unofficial
endpoints — rate limited, and the code degrades when they refuse), **Reddit**
(anonymous or OAuth), **X** and **Meta** (paid / business credentials), **BFL**
for generation, **Pexels** for photography, **OpenAI GPT-5.1** for judgement.

## Using it responsibly

An autonomous bot that picks its own subjects needs firmer limits than a manual
tool, not looser ones. Screening drops trademarks, likenesses, tragedy and live
politics before measurement, and references are ingredients rather than targets —
nothing mined is reproduced in the output. Check licensing before commercial use,
keep the Pexels attribution the board records, and review what autopilot picked
before you print it: the filters are good, and they are not a lawyer.
