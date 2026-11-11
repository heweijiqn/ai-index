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

Python 3.12 and all packages are installed in the project's `.venv`. Windows uses
`.venv\Scripts\python.exe`, equivalent to `.venv/bin/python3` on Linux/macOS.
The local renderer's headless Chromium lives in `.browsers/`.

1. Open `login.bat` and manually sign in to Xianyu, completing any verification.
2. After search items appear, close the entire dedicated Chrome login window.
3. Double-click `run.bat` to crawl, save documents, analyze and render.
4. Open the newest folder in `output/`; open its `抓取数据.txt` to read the counts.

For a single-keyword check that does not save data:

```powershell
Set-Location D:\ai-index
$env:PLAYWRIGHT_BROWSERS_PATH = 'D:\ai-index\.browsers'
$env:PYTHONUTF8 = '1'
.\.venv\Scripts\python.exe -X utf8 crawler.py --keyword 'AI 副业' --dry-run
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
Counts are a deduplicated sample of at most two pages per keyword, not total market
size. Keyword samples can overlap with one another.

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

GitHub Actions runs formatting/lint/type checks, regression tests and sample
rendering; it does not attempt authenticated live crawling. Local history,
outputs and browser sessions are excluded from Git. The active templates use
inline CSS, so normal rendering does not require Node/Tailwind builds.

## Validation

Use project-venv Python for pytest, Black, Ruff and mypy. Tests exercise document
validation, date-window loading, same-date replacement, immutable run snapshots,
read-only legacy export and independent output folders for repeated generations.
