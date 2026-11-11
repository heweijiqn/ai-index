# 热卖指数 — Architecture

## Product

热卖指数 observes arbitrary user-chosen Xianyu product/category/topic keywords.
A batch tool crawls search pages, calculates a sample-heat index and renders
three 1080×1080 images with a post caption. An optional local web workbench adds
interactive crawling, live page results and searchable history. It binds only to
127.0.0.1; no external database or public hosting is required. Python 3.12 and a
project-local virtual environment are used.

## Data Flow

```text
crawler.py -> storage.py -> data/history/YYYY-MM-DD.json + YYYY-MM-DD.txt
                              |
                         analyzer.py
                              |
                         renderer.py
                              |
output/YYYY-MM-DD_HHMMSS_microseconds_unique/
  抓取数据.txt
  records.json
  card1_index_YYYY_MM_DD.png
  card2_daily_YYYY_MM_DD.png
  card3_weekly_YYYY_MM_DD.png
  post.txt
```

Daily history is stored as ordinary documents, with one JSON and one Chinese TXT
report per date. JSON supplies typed records to the analyzer; TXT is intended
for the user to open directly in Notepad. Repeating a date replaces that date's
latest history while every run retains its own original snapshot and outputs.
Snapshots use Beijing creation times and a unique suffix, including for backfills.
Dates recorded in analysis continue to default to UTC unless --date is supplied.

The new runtime does not import or access SQLite. migrate_history.py is a separate,
explicit one-time legacy importer; it reads the old database in read-only mode,
exports the same observations, and checks duplicates before writing documents.
Old database files are archived locally after migration verification. All-zero
legacy history is retained and identified in the TXT reports, not fabricated or
silently removed. Existing history can still affect trend and warm-up calculation.

## Modules And Contracts

- config.py owns paths, browser settings, shared TypedDicts, runtime validation,
  and creation of unique run folders.
- storage.py validates records, atomically replaces individual daily documents,
  writes readable TXT reports and loads history within a date window. A malformed
  history document raises an error rather than silently dropping a day.
- crawler.py observes ordinary search JSON/JSONP responses in a persistent browser.
  The exact API path excludes shade requests, and site-initiated token refresh or
  retries are observed without solving challenges. Legacy and current response
  formats use item/seller IDs, and actual next-page controls drive pagination.
- analyzer.py loads daily JSON documents and performs the existing index math.
- renderer.py renders the three active templates using Jinja2 and Chromium.
  Explicit output_dir means the caller owns that run folder; omitted output_dir
  allocates a fresh folder. post.txt shares the folder with its three images.
- run_daily.py validates a complete crawl, allocates a run folder, saves document
  snapshots/history, analyzes only that batch's keywords and renders into that
  same folder. Same-date history still retains other previously saved keywords.
- crawl_options.py shares validated repeatable --keyword and positive --limit
  arguments between the crawler and daily CLI. run.bat enables --interactive,
  prompting in Chinese for missing keywords and the per-keyword unique item limit.
- smoke_test.py and preview_all.py allocate fresh folders per generation; sample
  data remains separate from live history.

Shared contracts remain CrawlRecord, RankingEntry, DailyRankingEntry and
AnalysisResult in config.py. Public function signatures must be typed. UI text
in the Chinese templates remains Chinese. Paths and author settings come from
config.py. Tests use temporary history and output directories.

## Failure And Persistence Rules

A login challenge, access denial, unrecognized response or broken pagination
raises CrawlError. No fallback zero rows are saved. A wholly empty batch does not
produce a new index. Document batches are validated before any writes. JSON files
are replaced atomically on the same filesystem, and same-date records are merged
by keyword. One batch writer is expected; do not overlap runs on one profile.

Raw data documents can remain if analysis/rendering fails. A folder with fewer
than three PNGs and post.txt is incomplete and the process reports failure.
Previously completed folders are never reused by the normal entry points.

Daily history lives in data/history and must be persisted alongside output on a
VPS or Docker host. Deleting output snapshots does not remove analysis history.
GitHub Actions runs checks, tests and sample rendering. Local history documents,
browser profiles and live output snapshots are excluded from the public source tree.
No browser profile or login state may be committed.

## Local Browser Setup

Windows defaults to visible installed Chrome, with a separate persistent profile
at data/browser-profile. login.bat lets the user sign in and complete challenges;
run.bat reuses the profile. AI_INDEX_BROWSER_CHANNEL selects the browser and
AI_INDEX_HEADLESS selects headless operation. Renderer screenshots still use the
separately installed Playwright Chromium. A session can expire and require manual
login again. With --limit, normal pagination continues until that many unique
items have been collected or the search ends; the last page is truncated before
computing sellers and average price. Exhausted searches log the actual count,
while failed/repeated pages still abort the batch. Without --limit, unattended
Python entry points retain the two-page default and configured keyword list.
Counts are sampled items, not the platform-wide total. Users should keep limits
consistent across dates because changing the sample size affects index trends.

APP_TITLE, APP_TAGLINE and POST_HASHTAGS in config.py define the shared public
name, card tagline and caption tags. The title is 热卖指数 and the display
maintainer is 小鱼鱼, configurable through AI_INDEX_AUTHOR for both web and
output signatures. Existing repository paths, service unit identifiers and
AI_INDEX_* environment names are retained for installation compatibility. The GitHub
repository is https://github.com/heweijiqn/ai-index, maintained as a standalone
public repository. The public main branch starts with a maintained snapshot
submitted by hwj. Earlier development history is retained in local and archived
repository backups.

## Local Web Workbench

`web_app.py` serves a buildless Chinese HTML/CSS/JavaScript interface from `web/`
and a small JSON API using Python's standard-library threaded HTTP server.
`web.bat` launches it in the project environment and opens the local browser.
The CLI and scheduled batch entry points remain available independently.

`web_jobs.py` serializes background pipeline jobs, atomically saving requests,
timestamps, status and page-by-page item previews in `data/web-jobs/`. Crawling
publishes structured progress through optional callbacks rather than exposing
browser responses or credentials. `run_daily.py` reports pipeline stages and
returns the output folder. A failed batch keeps its job error/preview, and does
not save partial crawl observations as successful daily history. After a restart,
unfinished jobs are marked interrupted and can be submitted again explicitly.

`web_history.py` provides date/keyword filtering and pagination over validated
daily documents, web jobs and pre-existing run snapshots. Daily history remains
the latest observation per date/keyword; run history retains individual attempts
and links completed outputs. Older summary-only runs have no item-level previews.
The UI polls current jobs while running, recovers the active job after refresh,
and offers output image previews and document downloads after completion.

The loopback server checks Host/Origin and requires a per-session token on job
creation. File downloads are limited to known artifacts under output/. It never
serves browser profiles, arbitrary local paths or raw browser responses. Only one
web job runs at a time; do not run CLI/login tasks against the same profile while
a web crawl is active. No Node build or new Python dependency is required.

## Templates And Deployment

Active templates are card_index.html, card_drivers.html and card_cooling.html.
Legacy templates card_weekly.html and card.html are kept for reference. The active
renderer uses inline CSS and needs no Node build.

Linux VPS and Docker Compose deployment scripts remain available. The host owns
scheduling, the project owns writable data/history and output, and Playwright needs
Chromium, required system libraries and Chinese fonts. Windows uses
.venv/Scripts/python.exe; Linux/macOS uses .venv/bin/python3.
