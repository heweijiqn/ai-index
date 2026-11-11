# AI Shovel Index — Deployment Guide

## Current Storage And Outputs

Normal runs use ordinary documents. Read daily data in
`data/history/YYYY-MM-DD.txt`; matching JSON files supply history to analysis.
There is no active database. Each generation reserves a fresh output folder:

```text
output/YYYY-MM-DD_HHMMSS_microseconds_unique/
  抓取数据.txt
  records.json
  card1_index_YYYY_MM_DD.png
  card2_daily_YYYY_MM_DD.png
  card3_weekly_YYYY_MM_DD.png
  post.txt
```

Repeated runs on the same day preserve all prior output folders. Daily history
uses the latest record for each keyword and date; repeated runs do not add counts
or duplicate the same day in trend calculation. Folder times use Beijing time.
The analysis record date defaults to UTC; --date overrides it.

Persist and back up both `data/history/` and `output/`. Deleting old output folders
does not remove the daily analysis history. A broken history document raises a
clear error rather than being silently skipped. Keep one writer at a time.

## Windows Local Setup

### Optional Local Web Workbench

Double-click `web.bat` to start the loopback-only workbench and open
`http://127.0.0.1:8765`. Keep the server console open. The Chinese UI submits
keywords, a per-keyword item limit and record date; it polls structured status
approximately every second and displays retained item previews after each page.
Completion exposes image previews and downloads. The history screen filters
daily records by record date, or individual runs by Beijing execution date,
with partial-keyword search and pagination. Existing documents and output
snapshots are readable without migration; old runs have no item-level previews.

```powershell
.\.venv\Scripts\python.exe -X utf8 web_app.py --open
.\web.bat --port 8766
```

Use one of these commands, choosing another port only if needed. Linux/macOS
can run `.venv/bin/python3 web_app.py` and open the printed local URL. No new
Python dependency or Node build is required. The server always binds to
127.0.0.1; the existing VPS/Docker timers remain CLI batch jobs and do not expose
this interface publicly.

Web requests/status/item previews persist in `data/web-jobs/`; back it up along
with `data/history/` and `output/`. Refreshing or closing a browser tab does not
stop an active job. Stopping the server can interrupt it; startup marks unfinished
jobs interrupted instead of silently rerunning them. Only one web job runs at
a time. Do not launch CLI crawls or a login browser against the same profile
while a web crawl is active. Failed jobs retain previews and errors, but a
failed crawl does not commit a partial daily batch. After a successful crawl,
analysis/rendering failure may still leave the validated data documents.

### Console Batch Entry Point

Python 3.12 and all packages are installed in the project's `.venv`. Windows uses
`.venv\Scripts\python.exe`, equivalent to `.venv/bin/python3` on Linux/macOS.
The local renderer's headless Chromium lives in `.browsers/`.

1. Open `login.bat` and manually sign in to Xianyu, completing any verification.
2. After search items appear, close the entire dedicated Chrome login window.
3. Double-click `run.bat`. Enter keywords separated by Chinese or English commas,
   then a positive integer maximum item count per keyword. Press Enter after each.
4. Wait for `=== Done ===` and `Exit code: 0`. Open the newest folder in `output/`;
   open its `抓取数据.txt` to read the counts.

For example, entering `AI 副业，Sora 教程` and `100` requests up to 100 unique
items for each keyword, at most 200 keyword-item observations in total. Spaces
inside a keyword are preserved; duplicate keywords are crawled once. Invalid
interactive input is retried. Choices apply to the current run and are not saved.

To supply both settings without prompts:

```powershell
.\run.bat --keyword 'AI 副业' --keyword 'Sora 教程' --limit 100
```

Repeat `--keyword` for multiple keywords on the command line. `run.bat` prompts
only for missing keywords or limit. A direct Python invocation prompts only when
`--interactive` is supplied. See the [Chinese usage guide](../使用手册.txt) for the
complete input walkthrough and troubleshooting.

For a single-keyword check that does not save data:

```powershell
Set-Location D:\ai-index
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\ai-index\.browsers'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -X utf8 crawler.py --keyword 'AI 副业' --limit 100 --dry-run
```

Run `smoke-test.bat` for renderer checks without crawling. Every invocation creates
a separate sample folder below `output/smoke/`; these samples do not update history.

Windows crawling defaults to visible installed Chrome, a real browser user agent,
and a separate persistent profile in `data/browser-profile/`. Never share or commit
that profile. `AI_INDEX_BROWSER_CHANNEL` selects Chrome/Edge/bundled Chromium;
`AI_INDEX_HEADLESS=1` requests headless crawling, which can encounter different
access restrictions. The site can require manual login again at any time.

The crawler observes ordinary search responses and clicks the actual pagination
controls. It matches the exact search endpoint, ignores similarly named shade
requests, and observes site-initiated retries. No captcha solving is provided.
With `--limit`, counts are capped at that number of unique items per keyword.
Pagination continues beyond two pages if needed and stops at the limit or a
confirmed search end. Sellers and average price use only the retained sample.
An exhausted search logs its actual count; failed pagination still aborts the
batch. These counts are samples, not total market size, and keyword samples can
overlap. Keep the same limits across dates when comparing trends.

Each run analyzes only its own keywords. Daily history merges records by keyword,
preserving other same-date keywords, while the run folder stores only that batch.

## Failure Handling

Login challenges, access denial, missing result fields or broken pagination stop
the batch before storage. Failed crawls do not become zero-item records. A wholly
empty batch is also rejected. Valid raw data documents may remain if a later
analysis or render fails; an incomplete folder is not a completed output.

Important log lines include RUN_CONTEXT, CRAWL_SUMMARY, CRAWL_HEALTH, RUN_FOLDER,
ANALYSIS_SUMMARY and OUTPUT_SUMMARY. A complete run folder contains three PNGs,
post.txt and the two data documents.

## Legacy Data Migration

`migrate_history.py` is an explicit one-time read-only SQLite importer. Normal
runtime modules do not use SQLite. It exports the original date/keyword/count/
price values, validates them, checks conflicting existing documents, and verifies
the exported rows. It never silently deletes zero records or overwrites different
existing history. Pass --source to import an archived legacy database.

The local migration exported and checked 1,992 rows across 249 daily documents
on 2026-11-11. Old database files remain only as local backups in `.deployment/`.
The original history through 2026-11-10 was all zero; Chinese reports flag all-zero
days. That legacy history is retained, so trend and warm-up results need care
until valid observations have accumulated.

## Linux And Docker

Use Python 3.12, a project `.venv`, Playwright Chromium, required Linux libraries
and Chinese fonts. The existing `deploy/vps/`, `deploy/systemd/` and
`deploy/docker/` deployment assets still apply. Keep `data/` and `output/` writable;
Docker bind mounts must retain both. The host owns scheduling and logs. A usable
Xianyu session remains necessary; unattended cloud access is not guaranteed.

Scheduled jobs should pass their sampling settings directly, without
`--interactive`. From the repository root, for example:

```bash
.venv/bin/python3 run_daily.py --keyword 'AI 副业' --keyword 'Sora 教程' --limit 100
```

Without `--keyword`, Python entry points use the eight keywords in `config.py`;
without `--limit`, they retain the two-page sampling default. This also applies
to the existing systemd and Docker templates. The interactive Windows launcher
always asks for missing settings. See the [VPS guide](../deploy/vps/README.md)
and [Docker guide](../deploy/docker/README.md) for scheduled command examples.

GitHub Actions runs formatting/lint/type checks, regression tests and sample
rendering; it does not attempt authenticated live crawling. Local history,
outputs and browser sessions are excluded from Git. The active templates use
inline CSS, so normal rendering does not require Node/Tailwind builds.

## Validation

Use project-venv Python for pytest, Black, Ruff and mypy. Tests exercise document
validation, date-window loading, same-date replacement, immutable run snapshots,
read-only legacy export and independent output folders for repeated generations.
