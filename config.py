"""config.py — Global constants, TypedDicts, and runtime directories.

Centralizes all configuration so other modules never hardcode paths,
keywords, or weights.
"""

import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import NotRequired, TypedDict
from uuid import uuid4

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT_DIR: Path = Path(__file__).parent
DATA_DIR: Path = ROOT_DIR / "data"
OUTPUT_DIR: Path = ROOT_DIR / "output"
TEMPLATES_DIR: Path = ROOT_DIR / "templates"
HISTORY_DIR: Path = DATA_DIR / "history"
LEGACY_DB_PATH: Path = DATA_DIR / "index.db"
RECORDS_JSON_NAME: str = "records.json"
RECORDS_TEXT_NAME: str = "抓取数据.txt"
LOCAL_TIMEZONE = timezone(timedelta(hours=8), name="Asia/Shanghai")
BROWSER_PROFILE_DIR: Path = DATA_DIR / "browser-profile"
XIANYU_SEARCH_URL: str = "https://www.goofish.com/search?q={keyword}"
SEARCH_API_NAME: str = "mtop.taobao.idlemtopsearch.pc.search"
XIANYU_ITEM_URL: str = "https://www.goofish.com/item?id={item_id}"
APP_TITLE: str = "AI 铲子指数"
WEB_DIR: Path = ROOT_DIR / "web"
WEB_JOBS_DIR: Path = DATA_DIR / "web-jobs"
WEB_HOST: str = "127.0.0.1"
WEB_PORT: int = 8765
WEB_DEFAULT_LIMIT: int = 100
BROWSER_CHANNEL: str = os.environ.get(
    "AI_INDEX_BROWSER_CHANNEL", "chrome" if sys.platform == "win32" else "chromium"
)
CRAWL_HEADLESS: bool = (
    os.environ.get("AI_INDEX_HEADLESS", "0" if sys.platform == "win32" else "1") == "1"
)
CRAWL_TIMEOUT_MS: int = 30_000
CRAWL_PAGES: int = 2
CRAWL_DELAY_MIN: float = 2.0
CRAWL_DELAY_MAX: float = 5.0
ACTIVE_TEMPLATE_NAMES: tuple[str, str, str] = (
    "card_index.html",
    "card_drivers.html",
    "card_cooling.html",
)

# ---------------------------------------------------------------------------
# Keywords to crawl
# ---------------------------------------------------------------------------

KEYWORDS: list[str] = [
    "ChatGPT 教程",
    "ChatGPT 副业",
    "AI 副业",
    "Sora 教程",
    "Stable Diffusion 教程",
    "Midjourney 教程",
    "Claude 教程",
    "AI 变现",
]

# ---------------------------------------------------------------------------
# Index calculation weights
# ---------------------------------------------------------------------------

WEIGHT_ITEMS: float = 0.6
WEIGHT_SELLERS: float = 0.4
INDEX_SCALE: float = 50.0
INDEX_MAX: float = 100.0
HISTORY_DAYS: int = 7  # days of history used for baseline average

# ---------------------------------------------------------------------------
# Status thresholds  (lower bound inclusive)
# ---------------------------------------------------------------------------

STATUS_THRESHOLDS: list[tuple[float, str]] = [
    (80.0, "bubble"),
    (60.0, "speculation"),
    (40.0, "rising"),
    (20.0, "early"),
    (0.0, "cold"),
]

# ---------------------------------------------------------------------------
# Render style constants
# ---------------------------------------------------------------------------

IMAGE_WIDTH: int = 1080
IMAGE_HEIGHT: int = 1080
BG_COLOR: str = "#0a0a0a"
TEXT_COLOR: str = "#ffffff"
SUBTEXT_COLOR: str = "#888888"
AUTHOR_HANDLE: str = os.environ.get("AI_INDEX_AUTHOR", "hwj")

STATUS_COLORS: dict[str, str] = {
    "cold": "#4a9eff",
    "early": "#a8e6cf",
    "rising": "#ffd93d",
    "speculation": "#ff6b35",
    "bubble": "#ff2d55",
}

# Crawl health thresholds used by run_daily.py for cloud log visibility.
CRAWL_FAILURE_WARN_RATIO: float = 0.25
CRAWL_FAILURE_ERROR_RATIO: float = 0.50

# ---------------------------------------------------------------------------
# TypedDicts — shared data contracts between modules
# ---------------------------------------------------------------------------


class CrawlRecord(TypedDict):
    """One document record per keyword and date."""

    date: str  # "YYYY-MM-DD"
    keyword: str
    item_count: int  # 0 only for a confirmed empty search, never a failed request
    seller_count: int
    avg_price: float


class CrawlItem(TypedDict):
    """A retained search item; old fixtures may omit display-only fields."""

    item_id: str
    seller_id: str
    price: float
    title: NotRequired[str]
    url: NotRequired[str]


class CrawlProgress(TypedDict, total=False):
    """Structured progress, safe to persist and display in the local workbench."""

    stage: str
    keyword: str
    page: int
    record: CrawlRecord
    items: list[CrawlItem]
    message: str
    output_id: str


ProgressCallback = Callable[[CrawlProgress], None]


class RankingEntry(TypedDict):
    """Per-keyword growth entry inside AnalysisResult."""

    keyword: str
    growth: float  # ratio vs 7-day baseline; 1.0 = flat


class DailyRankingEntry(TypedDict):
    """Per-keyword day-over-day change entry inside AnalysisResult."""

    keyword: str
    delta: float  # today_count - yesterday_count (absolute change in item_count)
    pct: float  # percentage change vs yesterday; 0.0 if no yesterday data


class AnalysisResult(TypedDict):
    """Output of analyzer.py, consumed by renderer.py."""

    date: str  # "YYYY-MM-DD"
    index: float  # 0.0–100.0
    status: str  # "cold" | "early" | "rising" | "speculation" | "bubble"
    rankings: list[RankingEntry]  # sorted descending by growth (7-day window)
    daily_rankings: list[DailyRankingEntry]  # sorted descending by pct (today vs yesterday)
    warming_up: bool  # True when history has fewer than HISTORY_DAYS days of data
    week_delta: float  # index change vs 7 days ago (positive = rising, negative = falling)


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------


def utc_today_str() -> str:
    """Return today's date in UTC as an ISO-8601 YYYY-MM-DD string."""
    return datetime.now(UTC).date().isoformat()


def create_run_dir(target_date: str, root: Path | None = None) -> Path:
    """Reserve a new folder, including for two runs within the same second."""
    datetime.strptime(target_date, "%Y-%m-%d")
    base = OUTPUT_DIR if root is None else root
    stamp = datetime.now(LOCAL_TIMEZONE).strftime("%H%M%S_%f")
    path = base / f"{target_date}_{stamp}_{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def ensure_runtime_dirs() -> None:
    """Create runtime directories used by the daily pipeline if missing."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def validate_runtime_environment() -> None:
    """Fail fast when required runtime directories are not writable.

    The project is designed as a batch job that writes local documents and
    output files, so both directories must exist and support write access.
    """
    ensure_runtime_dirs()
    for path in (DATA_DIR, HISTORY_DIR, OUTPUT_DIR):
        if not os.access(path, os.W_OK):
            raise PermissionError(f"Runtime directory is not writable: {path}")
