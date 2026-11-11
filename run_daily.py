"""run_daily.py — Orchestrate the full daily pipeline: crawl → analyze → render.

Entry point for both local runs and GitHub Actions.

CLI usage:
    .venv/bin/python3 run_daily.py                  # run for today
    .venv/bin/python3 run_daily.py --date 2026-03-06  # backfill a specific date
"""

import argparse
import logging
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from analyzer import analyze
from config import (
    CRAWL_FAILURE_ERROR_RATIO,
    CRAWL_FAILURE_WARN_RATIO,
    ProgressCallback,
    create_run_dir,
    utc_today_str,
    validate_runtime_environment,
)
from crawl_options import add_crawl_arguments, prompt_crawl_options
from crawler import CrawlError, crawl_all, save_records
from renderer import render

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(module)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def _summarize_crawl(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build a crawl health summary for log output and alerting."""
    total_keywords = len(records)
    failed_keywords = [record["keyword"] for record in records if record["item_count"] == 0]
    total_items = sum(int(record["item_count"]) for record in records)
    failure_count = len(failed_keywords)
    failure_ratio = (failure_count / total_keywords) if total_keywords else 0.0
    return {
        "total_keywords": total_keywords,
        "failed_keywords": failed_keywords,
        "failure_count": failure_count,
        "failure_ratio": failure_ratio,
        "total_items": total_items,
    }


def _log_crawl_health(summary: dict[str, Any]) -> None:
    """Emit structured crawl health logs so cloud failures stand out quickly."""
    logger.info(
        "CRAWL_SUMMARY total_keywords=%d total_items=%d failed_keywords=%d failure_ratio=%.2f",
        summary["total_keywords"],
        summary["total_items"],
        summary["failure_count"],
        summary["failure_ratio"],
    )

    failed_keywords = summary["failed_keywords"]
    if failed_keywords:
        logger.warning("Zero-item keywords (written as 0-records): %s", failed_keywords)

    if summary["failure_ratio"] >= CRAWL_FAILURE_ERROR_RATIO:
        logger.error(
            "CRAWL_HEALTH degraded failure_ratio=%.2f threshold=%.2f failed_keywords=%s",
            summary["failure_ratio"],
            CRAWL_FAILURE_ERROR_RATIO,
            failed_keywords,
        )
    elif summary["failure_ratio"] >= CRAWL_FAILURE_WARN_RATIO:
        logger.warning(
            "CRAWL_HEALTH warning failure_ratio=%.2f threshold=%.2f failed_keywords=%s",
            summary["failure_ratio"],
            CRAWL_FAILURE_WARN_RATIO,
            failed_keywords,
        )


def run(
    target_date: str,
    keywords: list[str] | None = None,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> Path:
    """Execute the full pipeline for a given date.

    Steps:
        1. Crawl the requested keywords on Xianyu → list[CrawlRecord]
        2. Save daily documents and a new run folder
        3. Analyze records → AnalysisResult
        4. Render PNG + post.txt

    Args:
        target_date: Date string "YYYY-MM-DD" to process.
        keywords: Selected keywords; None uses the configured defaults.
        limit: Maximum unique items per keyword; None keeps two-page sampling.
    """
    validate_runtime_environment()
    logger.info("=== AI Shovel Index daily run — %s ===", target_date)
    logger.info("RUN_CONTEXT target_date=%s", target_date)

    # ── Step 1: Crawl ──────────────────────────────────────────────────────
    logger.info("[1/4] Crawling Xianyu…")
    if progress is None:
        records = crawl_all(target_date=target_date, keywords=keywords, limit=limit)
    else:
        progress({"stage": "crawling", "message": "正在打开抓取浏览器"})
        records = crawl_all(
            target_date=target_date, keywords=keywords, limit=limit, progress=progress
        )

    crawl_summary = _summarize_crawl(records)
    logger.info(
        "Crawl complete: %d keywords, %d total items, %d failed.",
        crawl_summary["total_keywords"],
        crawl_summary["total_items"],
        crawl_summary["failure_count"],
    )
    _log_crawl_health(crawl_summary)

    if not records or crawl_summary["total_items"] == 0:
        raise CrawlError("本次抓取没有有效商品，已停止保存文档和生成指数。请先检查登录状态。")

    # ── Step 2: Persist ────────────────────────────────────────────────────
    logger.info("[2/4] Saving data documents…")
    if progress:
        progress({"stage": "saving", "message": "正在保存本次数据"})
    output_dir = create_run_dir(target_date)
    save_records(records, output_dir=output_dir)
    logger.info("RUN_FOLDER %s", output_dir)

    # ── Step 3: Analyze ────────────────────────────────────────────────────
    logger.info("[3/4] Analyzing…")
    if progress:
        progress(
            {
                "stage": "analyzing",
                "message": "正在计算指数与趋势",
                "output_id": output_dir.name,
            }
        )
    result = analyze(target_date, keywords=[record["keyword"] for record in records])
    logger.info(
        "Index: %.2f  Status: %s  warming_up: %s",
        result["index"],
        result["status"],
        result["warming_up"],
    )
    logger.info(
        "ANALYSIS_SUMMARY index=%.2f status=%s warming_up=%s week_delta=%.2f",
        result["index"],
        result["status"],
        result["warming_up"],
        result["week_delta"],
    )

    # ── Step 4: Render ─────────────────────────────────────────────────────
    logger.info("[4/4] Rendering output files…")
    if progress:
        progress({"stage": "rendering", "message": "正在生成三张图片和发布文案"})
    idx_png, daily_png, wkly_png, txt_path = render(result, output_dir=output_dir)

    logger.info("=== Done ===")
    for png in (idx_png, daily_png, wkly_png):
        logger.info("PNG  → %s", png)
    logger.info("Text → %s", txt_path)
    logger.info(
        "OUTPUT_SUMMARY card1=%s card2=%s card3=%s post=%s",
        idx_png,
        daily_png,
        wkly_png,
        txt_path,
    )

    # Print final paths to stdout (for CI artifact collection)
    print(f"Card1 (index):   {idx_png}")
    print(f"Card2 (daily):   {daily_png}")
    print(f"Card3 (weekly):  {wkly_png}")
    print(f"TXT:             {txt_path}")
    return output_dir


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AI Shovel Index daily pipeline.")
    add_crawl_arguments(parser)
    parser.add_argument("--interactive", action="store_true", help="交互输入关键词和抓取数量。")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date in YYYY-MM-DD format. Defaults to today.",
    )
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()
    target = args.date or utc_today_str()

    try:
        keywords, limit = args.keyword, args.limit
        if args.interactive:
            keywords, limit = prompt_crawl_options(keywords, limit)
        run(target, keywords=keywords, limit=limit)
    except (EOFError, KeyboardInterrupt):
        logger.error("运行已取消。")
        sys.exit(1)
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
