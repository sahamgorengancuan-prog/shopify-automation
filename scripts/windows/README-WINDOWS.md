# ARCHIVIST on Windows

Everything in this folder is self-contained. You do not need to install Python
first — `setup.bat` will find it or fetch it.

## Quick start

1. Unzip anywhere you can write, e.g. `C:\archivist`.
2. Double-click **`run_archivist.bat`**.
   * first run: it resolves Python 3.14, creates the environment and installs
     dependencies (a few minutes);
   * then the browser opens at <http://127.0.0.1:7860>.
3. In the app, open **① Setup**, paste any API keys you have, press
   **Save configuration**.
4. Open **② Connection** and press **Run all checks**.
5. Open **③ Studio**, type a topic, press **Run pipeline**.

No keys? Tick **Offline mode** in Setup. The whole pipeline runs against
procedurally generated references — enough to see exactly what it does before
spending anything.

## What the scripts do

| file | purpose |
|---|---|
| `setup.bat` | finds `py -3.14`, else a 3.10+ `python`, else downloads the embeddable Python 3.14 into `%LOCALAPPDATA%\archivist`; creates the environment; installs dependencies; writes `env.cmd` |
| `run_archivist.bat` | launches the Gradio control room (runs setup first if needed). Arguments pass through: `run_archivist.bat --port 8000 --scheduler` |
| `run_pipeline.bat` | headless, no browser — the whole bot or any one stage |

### Headless commands

```bat
run_pipeline.bat --auto                  discover AND design: the whole bot
run_pipeline.bat --house                 the V9 house system end to end
run_pipeline.bat --house --topic harbor  the house system on a chosen signal
run_pipeline.bat --house --no-generate   blueprint, prompt contract and listing only
run_pipeline.bat --volume                rank roots by relative search volume
run_pipeline.bat --discover -n 8         research only
run_pipeline.bat "deep sea salvage" --no-generate
run_pipeline.bat --check                 connection self-test
run_pipeline.bat --plan "north sea oil"  auto-plan a collection
```

Set `ARCHIVIST_OFFLINE=1` before any of them to rehearse the entire chain with
no network and no spend. Offline runs cannot call the vision critic, so they are
approved on the deterministic print proof alone and say so.

### Colab / Jupyter

`notebooks\archivist_pipeline.ipynb` is the one-run surface: open it, fill the
parameter cell, run all. It clones the repository, loads keys from Colab Secrets,
the environment or `.env` (presence only is ever shown, never a value), tests each
service, then runs a single autonomous pipeline to a finished delivery.

## Keeping it running

To start the app at logon, use the **⑥ Deploy** tab to write
`windows-task.xml`, then:

```bat
schtasks /Create /TN ARCHIVIST /XML windows-task.xml
```

## Where things go

```
runs\<collection>\<timestamp>-<topic>\   one run: references, prompts, artwork, print files, report
runs\<collection>\style_lock.json        the collection's visual identity — back this up
runs\_scheduler\jobs.json                scheduled jobs and their history
.env                                     your API keys (never leaves this machine)
```

## If something goes wrong

* **"download failed"** during setup — a proxy or firewall blocked python.org.
  Install Python 3.14 from <https://www.python.org/downloads/> (tick *Add
  python.exe to PATH*) and run `setup.bat` again.
* **PowerShell execution policy errors** — the scripts only use `powershell
  -NoProfile -Command`, which is not affected by script-execution policy. If it
  still fails, unpack the embeddable zip manually into
  `%LOCALAPPDATA%\archivist\python3.14.0`.
* **DuckDuckGo check fails** — usually rate limiting. Wait a minute, or
  `pip install ddgs` inside the environment, or work in offline mode.
* **Port already in use** — `run_archivist.bat --port 8001`.
* **Antivirus quarantines the download** — allow `%LOCALAPPDATA%\archivist`, or
  install Python system-wide instead.
