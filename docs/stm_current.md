# STM: v1 — Cloud Deployment Readiness

**Version goal**: stabilize the project for cloud deployment, remove current doc and workflow drift, and reduce the chance of hidden failures in the daily batch pipeline.

**Created**: 2026-03-06  
**Current status**: BUILD

## Current Diagnosis

- The real product is now a 3-card renderer, but parts of the docs still describe older 4-card behavior.
- CI still includes a legacy Node/Tailwind build path that the active templates do not use.
- Runtime code is functional, but deployment concerns such as timezone clarity, SQLite single-writer assumptions, and render validation are not yet hardened.
- The project can already run daily, but it is not yet packaged as a clean cloud-ready batch service.

## Phase 1: Planning And Documentation

- [x] Refactor `AGENTS.md` into a concise, current workspace instruction file
- [x] Sync `docs/architecture.md` to the actual 3-card pipeline and current runtime assumptions
- [x] Add a dedicated deployment guide covering Python, Playwright, fonts, writable directories, and scheduler expectations
- [x] Decide the first deployment target: GitHub Actions only, VPS cron, Docker container, or managed cloud runtime

## Phase 2: Runtime Hardening

- [x] Make runtime date handling explicit and timezone-safe across `crawler.py`, `analyzer.py`, and `run_daily.py`
- [x] Define and implement the SQLite journal/concurrency strategy for single-run scheduling
- [x] Add clear render output validation so partial PNG generation fails fast
- [x] Add startup validation for required templates and critical directories

## Phase 3: CI And Delivery Simplification

- [x] Remove legacy Node/Tailwind steps from `.github/workflows/daily.yml` unless a task explicitly uses `templates/card.html`
- [x] Align CI commands with repo conventions by using `.venv` or document why CI intentionally differs
- [x] Add a deployment smoke test path for server verification

## Phase 4: Operability

- [x] Add crawler failure threshold warnings so systemic crawl breakage is visible quickly
- [x] Review logging for cloud execution and make sure failures are easy to diagnose from stdout logs
- [x] Decide whether `data/index.db` should keep being committed to git or move to server persistence

## Acceptance Criteria

- [ ] Documentation matches the real pipeline, outputs, and commands
- [ ] One clean daily run can execute in the target deployment environment without manual intervention
- [ ] Rendered cards are visually stable on the deployment OS
- [ ] Failure modes are explicit enough that a broken crawl or render is easy to detect

## VPS Deployment Kit

- [x] Add a repo-local Ubuntu VPS bootstrap script
- [x] Add systemd service and timer templates for the recommended deployment target
- [x] Add a step-by-step VPS deployment README tied to this project

## Docker Deployment Kit

- [x] Add a project Dockerfile and `.dockerignore`
- [x] Add a Docker Compose deployment path with bind-mounted persistence
- [x] Add Docker-oriented VPS bootstrap and systemd timer templates
- [x] Add a project-specific Docker deployment README with upgrade and rollback guidance

## Windows Crawl Recovery

- [x] Diagnose live search access and current result markup without changing stored data
- [x] Add persistent browser sessions and an interactive login command using installed Edge/Chrome
- [x] Parse current result cards, deduplicate items and sellers, and wait for results instead of network idle
- [x] Fail explicitly on login, access denial, or missing results; do not save fallback zeros or render misleading output
- [x] Add regression tests and document the Windows login/run workflow
- [x] Verify a live keyword yields real items (requires a usable Xianyu session)

Live verification on 2026-11-11: `AI 副业` returned 30 items per page,
55 unique items and 54 sellers across two pages. The user completed manual
login in the dedicated Chrome profile. Full batch verification completed:
all eight keywords succeeded, 380 per-keyword deduplicated item observations,
eight DB rows written, three PNGs and `post.txt` generated. SQLite integrity and
PNG validation passed. All 83 tests passed; changed-file Black/Ruff and full mypy
checks passed. Whole-repo style checks retain existing issues in unchanged files.

## Document Storage And Per-Run Output

- [x] Replace active SQLite reads/writes with daily JSON documents and readable Chinese TXT reports
- [x] Allocate a unique timestamped output folder for every daily run, smoke test, and preview
- [x] Export existing SQLite history into documents and archive existing flat outputs without losing data
- [x] Update Windows instructions, deployment assets, and architecture for document persistence
- [x] Verify history replacement/filtering, migration fidelity, and repeated-run output isolation with regression tests and a real run

Migration checked 1,992 original rows across 249 dates. A complete read-only legacy
export also remains under `data/旧版历史完整导出/`; the old database is a backup
under `.deployment/sqlite-backup/` and no longer exists in the runtime data path.
No legacy flat output files were present when checked, so none were moved.
The live run on 2026-11-11 succeeded for all eight keywords with 374 per-keyword
item observations. Its six files are isolated in
`output/2026-11-11_164830_449717_b3484009/`. PNG/document validation passed.
All 94 tests passed, including two same-date full generations into different folders.

## GitHub Publication

- [x] Replace display attribution with maintainer hwj and the verified GitHub account heweijiqn
- [x] Rewrite README and usage documentation for clean installation and current document storage
- [x] Exclude local browser sessions, environments, crawl data, generated outputs and backups from publication
- [x] Validate the publishable tree and generate a current signed sample with the new display name
- [x] Publish the tested changes to a public ai-index repository under the verified account and check the remote revision

Published at https://github.com/heweijiqn/ai-index as a standalone public repository.
Current source, README, maintainer links, templates and sample caption use hwj.
Original Git history is retained in backups. Local credentials, browser sessions,
data documents, outputs, environments and backups are excluded from the source
snapshot. All 94 local tests and Black/Ruff/mypy checks passed before publication.

## Standalone Repository

- [x] Back up and verify the complete Git history before changing the hosted repository
- [x] Retain the previous hosted repository as a separate backup and publish the same commits at the original address
- [x] Verify that the public repository reports fork=false and has the same main revision

The current ai-index repository is independent of any fork network. Repository
backups remain available for rollback with the complete earlier source history.

## Single Maintainer Snapshot

- [x] Back up and verify the previous complete Git history before creating a fresh public history
- [x] Publish the current maintained files as a single initial snapshot submitted by hwj
- [x] Verify that the public repository is independent, public, and lists only heweijiqn as a contributor

The public source snapshot retains the current application and documentation.
Full earlier history remains in backups; the public main branch uses a fresh
initial import instead of relabeling old authors' commits.
GitHub contributor verification returned only heweijiqn (hwj), with one initial
snapshot commit. The previous hosted repository was archived as a history backup.

## Manual Keywords And Crawl Limits

**Goal**: let the user enter keywords and choose a per-keyword unique item limit,
then commit and push the verified change to the existing GitHub repository.

- [x] Add validated keyword/limit CLI options and interactive Chinese prompts to the Windows daily entry point, preserving unattended command defaults
- [x] Crawl pages until the requested unique item limit or confirmed search end, with precise truncation and existing failure protections
- [x] Limit each run's analysis to its requested keywords while preserving other same-date history
- [x] Update README, Windows usage guides, architecture and data report wording for configurable sampling
- [x] Verify input validation, deduplication, pagination, early exhaustion and pipeline forwarding; run project checks
- [x] Commit and push the verified changes, then confirm the remote revision

Validation on 2026-11-11: all 120 tests passed, including Chromium-backed
pagination past two pages, exact item limits, duplicate handling and early search
exhaustion. Whole-repository Black/Ruff/mypy checks passed. A live read-only
`crawler.py --keyword "AI 副业" --limit 3 --dry-run` returned exactly three items,
three sellers and an average price of 1.19; no history documents were changed.
Feature commit `fb9ea8a` was pushed to origin/main and verified with ls-remote.

## Usage Documentation Follow-up

- [x] Add a visible input walkthrough, copyable examples and input troubleshooting to README and Windows usage guides
- [x] Align deployment, VPS and Docker instructions with configurable keyword/item limits and unattended defaults
- [x] Check documented options against both CLI help screens, review document links/diffs, and commit the documentation update
- [x] Push the documentation update and verify origin/main

Documentation commit `de7b464` was pushed and verified on origin/main. Six usage
documents (including the local-only Windows quick guide) were checked for valid
links, balanced Markdown code fences and matching CLI example arguments. Both
entry points' help screens and git diff --check passed; application code was unchanged.

## Local Search And History Workbench

**Goal**: add a simple local Chinese UI for manual keyword/item-limit search,
live crawl results and keyword/date-filtered history; retain the CLI and JSON/TXT store.

- [x] Update product scope and architecture for an optional loopback web workbench
- [x] Add shared structured crawl progress and item previews, plus pipeline stage/output callbacks
- [x] Add persistent single-job execution, restart recovery and filtered/paginated daily/run history including old snapshots
- [x] Add a loopback JSON/static server with validated inputs, safe output downloads and a Windows launcher
- [x] Build responsive Chinese search/history pages with live polling, item links, filters, empty/error states and output previews
- [x] Add backend and browser integration coverage; verify existing tests and whole-repository checks
- [ ] Update usage/deployment instructions, verify the live UI, and commit/push the finished work

Validation on 2026-11-11: all 135 tests passed. Chromium integration covers live
page previews, refresh recovery (including restored request fields), keyword/date
filtering, empty states, run details, output images and desktop/mobile layouts.
Backend checks cover request validation, job serialization/restart/failure,
render-failure snapshot linking, pagination, old snapshots and file/origin access
boundaries. Whole-repository Black/Ruff/mypy checks passed. Existing local daily
history and both run snapshots are readable. A live three-item crawl verified
progress metadata, titles and item links without writing history or outputs.
README, Windows guides and deployment instructions describe the new web.bat entry
point, record-date versus run-date filters, persistence and service lifecycle.
