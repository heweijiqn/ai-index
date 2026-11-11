"""Crawl normal Xianyu search responses with a reusable browser login session."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import random
import re
import time
from typing import Any
from urllib.parse import quote, urlsplit

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    Response,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError

from config import (
    BROWSER_CHANNEL,
    BROWSER_PROFILE_DIR,
    CRAWL_DELAY_MAX,
    CRAWL_DELAY_MIN,
    CRAWL_HEADLESS,
    CRAWL_PAGES,
    CRAWL_TIMEOUT_MS,
    KEYWORDS,
    SEARCH_API_NAME,
    XIANYU_ITEM_URL,
    XIANYU_SEARCH_URL,
    CrawlRecord,
    ProgressCallback,
    utc_today_str,
)
from config import (
    CrawlItem as SearchItem,
)
from crawl_options import add_crawl_arguments
from storage import save_records

logger = logging.getLogger(__name__)


class CrawlError(RuntimeError):
    """A failed crawl must not be recorded as zero market activity."""


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_price(value: Any) -> float:
    """Read scalar or structured prices without treating labels as numbers."""
    if isinstance(value, list):
        value = "".join(str(p.get("text", "")) for p in value if isinstance(p, dict))
    if isinstance(value, dict):
        value = value.get("price", value.get("text", ""))
    match = re.fullmatch(r"[¥￥]?\s*(\d+(?:\.\d+)?)\s*(万)?", str(value).strip().replace(",", ""))
    if not match:
        return 0.0
    price = float(match[1]) * (10000 if match[2] else 1)
    return price if math.isfinite(price) else 0.0


def _parse_search_payload(payload: dict[str, Any]) -> list[SearchItem]:
    """Read the two result formats used by the current Xianyu frontend.

    The displayed seller label can be a city, so only real seller IDs count.
    """
    statuses = payload.get("ret", [])
    if not isinstance(statuses, list) or not any(str(s).startswith("SUCCESS") for s in statuses):
        raise CrawlError("闲鱼搜索未成功，请运行 login.bat 完成登录或验证后重试。")
    data = _as_dict(payload.get("data"))
    if not isinstance(data.get("resultList"), list):
        raise CrawlError("闲鱼搜索响应结构发生变化：缺少 resultList。")
    items: list[SearchItem] = []
    for entry in data["resultList"]:
        raw = _as_dict(_as_dict(entry).get("data"))
        main = _as_dict(_as_dict(raw.get("item")).get("main"))
        content = _as_dict(main.get("exContent"))
        args = _as_dict(_as_dict(main.get("clickParam")).get("args"))
        item_id = raw.get("id") or content.get("itemId")
        if not item_id:
            continue
        seller_id = (
            raw.get("userId")
            or content.get("userId")
            or args.get("seller_id")
            or args.get("user_id")
        )
        price = _parse_price(raw.get("price", content.get("price", "")))
        if not seller_id or price <= 0:
            raise CrawlError("商品缺少有效价格或卖家 ID，停止本次抓取以避免错误指数。")
        items.append(
            SearchItem(
                item_id=str(item_id),
                seller_id=str(seller_id),
                price=price,
                title=str(raw.get("title") or content.get("title") or f"商品 {item_id}"),
                url=XIANYU_ITEM_URL.format(item_id=quote(str(item_id), safe="")),
            )
        )
    if data["resultList"] and not items:
        raise CrawlError("搜索结果无法识别为商品，请检查网页结构或登录状态。")
    return items


def _aggregate_items(items: list[SearchItem], keyword: str, target_date: str) -> CrawlRecord:
    """Deduplicate both items and sellers across result pages."""
    unique = {item["item_id"]: item for item in items}
    return CrawlRecord(
        date=target_date,
        keyword=keyword,
        item_count=len(unique),
        seller_count=len({item["seller_id"] for item in unique.values()}),
        avg_price=(
            round(sum(item["price"] for item in unique.values()) / len(unique), 2)
            if unique
            else 0.0
        ),
    )


def _page_access_error(body: str) -> str | None:
    if "非法访问" in body or "请使用正常浏览器" in body:
        return "闲鱼拒绝本次访问，请在 login.bat 打开的浏览器中检查访问状态。"
    if "滑动验证" in body or "拖动滑块" in body or "访问受限" in body:
        return "闲鱼需要人工验证，请运行 login.bat 完成验证后重试。"
    return None


async def _wait_for_search(page: Page, queue: asyncio.Queue[dict[str, Any]]) -> list[SearchItem]:
    deadline = time.monotonic() + CRAWL_TIMEOUT_MS / 1000
    last_error = "未收到有效搜索结果。请运行 login.bat 登录，再使用 --dry-run 验证。"
    while time.monotonic() < deadline:
        try:
            payload = await asyncio.wait_for(queue.get(), timeout=0.5)
        except TimeoutError:
            error = _page_access_error(await page.locator("body").inner_text(timeout=2000))
            if error:
                raise CrawlError(error)
            continue
        statuses = " ".join(str(s) for s in payload.get("ret", []))
        # Allow the site's own client to refresh its token and retry.
        if "TOKEN_EXPIRED" in statuses or "TOKEN_EMPTY" in statuses:
            continue
        if not any(str(s).startswith("SUCCESS") for s in payload.get("ret", [])):
            # Observe the site's own retry. Do not initiate challenge/token requests.
            last_error = "闲鱼搜索受限或登录已过期，请运行 login.bat 检查并完成验证。"
            continue
        return _parse_search_payload(payload)
    raise CrawlError(last_error)


def _is_search_response(url: str) -> bool:
    """Exclude similarly named shade requests and URLs embedded in login queries."""
    return urlsplit(url).path.rstrip("/") == f"/h5/{SEARCH_API_NAME}/1.0"


async def _fetch_keyword_async(
    keyword: str,
    context: BrowserContext,
    target_date: str,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> CrawlRecord:
    """Observe requests made by the normal page, then click its next-page button."""
    page = await context.new_page()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def on_response(response: Response) -> None:
        if not _is_search_response(response.url):
            return
        try:
            text = await response.text()
            if not text.lstrip().startswith("{"):
                text = text[text.index("(") + 1 : text.rindex(")")]
            payload = json.loads(text)
            if isinstance(payload, dict):
                queue.put_nowait(payload)
        except (ValueError, PlaywrightError) as exc:
            # Never log URLs, cookies, tokens, or raw account/page responses.
            logger.debug("Could not read search response: %s", type(exc).__name__)

    page.on("response", on_response)
    collected: list[SearchItem] = []
    try:
        logger.info("Fetching keyword '%s'", keyword)
        if progress:
            progress({"stage": "crawling", "keyword": keyword, "page": 0})
        await page.goto(
            XIANYU_SEARCH_URL.format(keyword=quote(keyword, safe="")),
            wait_until="domcontentloaded",
            timeout=CRAWL_TIMEOUT_MS,
        )
        page_num = 0
        seen: set[str] = set()
        while True:
            page_num += 1
            items = await _wait_for_search(page, queue)
            logger.info("Keyword '%s', page %d: %d items", keyword, page_num, len(items))
            if not items:
                break
            new_items = []
            for item in items:
                if item["item_id"] not in seen:
                    seen.add(item["item_id"])
                    new_items.append(item)
            if not new_items:
                raise CrawlError("翻页后仍是同一批商品，停止抓取以避免重复计数。")
            collected.extend(new_items if limit is None else new_items[: limit - len(collected)])
            if progress:
                progress(
                    {
                        "stage": "crawling",
                        "keyword": keyword,
                        "page": page_num,
                        "record": _aggregate_items(collected, keyword, target_date),
                        "items": list(collected),
                    }
                )
            if limit is not None and len(collected) >= limit:
                break
            if limit is None and page_num == CRAWL_PAGES:
                break
            next_button = page.locator("button[class*='search-pagination-arrow-container']").last
            await next_button.wait_for(state="visible", timeout=5000)
            if await next_button.is_disabled():
                break
            await asyncio.sleep(random.uniform(CRAWL_DELAY_MIN, CRAWL_DELAY_MAX))
            await next_button.click()
    except CrawlError:
        raise
    except PlaywrightError as exc:
        raise CrawlError(
            f"关键词 {keyword} 抓取失败（{type(exc).__name__}），未写入数据。"
        ) from None
    finally:
        page.remove_listener("response", on_response)
        await page.close()
    if limit is not None and len(collected) < limit:
        logger.warning(
            "关键词 '%s' 搜索结果已结束：目标 %d 条，实际 %d 条去重商品。",
            keyword,
            limit,
            len(collected),
        )
    if progress and not collected:
        progress(
            {
                "stage": "crawling",
                "keyword": keyword,
                "page": page_num,
                "record": _aggregate_items([], keyword, target_date),
                "items": [],
            }
        )
    return _aggregate_items(collected, keyword, target_date)


async def _open_context(playwright: Playwright, *, login: bool = False) -> BrowserContext:
    """Reuse a dedicated profile, leaving the user's personal browser separate."""
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return await playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            channel=None if BROWSER_CHANNEL == "chromium" else BROWSER_CHANNEL,
            headless=False if login else CRAWL_HEADLESS,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={"width": 1440, "height": 1000},
        )
    except PlaywrightError:
        raise CrawlError(
            "无法启动抓取浏览器。请关闭本项目的登录/抓取窗口，确认已安装 Chrome，"
            "或设置 AI_INDEX_BROWSER_CHANNEL=msedge。"
        ) from None


async def _login_async() -> None:
    async with async_playwright() as playwright:
        context = await _open_context(playwright, login=True)
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(
                XIANYU_SEARCH_URL.format(keyword=quote("AI 副业", safe="")),
                wait_until="domcontentloaded",
                timeout=CRAWL_TIMEOUT_MS,
            )
            print("请在浏览器中手动登录闲鱼并完成必要验证。")
            print(
                "确认能看到搜索商品后，关闭整个登录浏览器窗口；登录状态会保存在本机。", flush=True
            )
            await context.wait_for_event("close", timeout=0)
        finally:
            await context.close()


def login() -> None:
    """Let the user complete login in the dedicated browser."""
    asyncio.run(_login_async())


async def _crawl_all_async(
    target_date: str,
    keywords: list[str] | None = None,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> list[CrawlRecord]:
    records: list[CrawlRecord] = []
    async with async_playwright() as playwright:
        context = await _open_context(playwright)
        try:
            for index, keyword in enumerate(KEYWORDS if keywords is None else keywords):
                if index:
                    await asyncio.sleep(random.uniform(CRAWL_DELAY_MIN, CRAWL_DELAY_MAX))
                records.append(
                    await _fetch_keyword_async(keyword, context, target_date, limit, progress)
                )
        finally:
            await context.close()
    return records


def crawl_all(
    target_date: str | None = None,
    keywords: list[str] | None = None,
    limit: int | None = None,
    progress: ProgressCallback | None = None,
) -> list[CrawlRecord]:
    """Return a complete batch or raise before the caller can persist partial data."""
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise ValueError("抓取数量必须是大于 0 的整数。")
    if keywords is not None:
        if not keywords or any(not keyword.strip() for keyword in keywords):
            raise ValueError("关键词不能为空。")
        keywords = list(dict.fromkeys(keyword.strip() for keyword in keywords))
    return asyncio.run(_crawl_all_async(target_date or utc_today_str(), keywords, limit, progress))


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl Xianyu with a reusable login session.")
    parser.add_argument("--login", action="store_true", help="Open browser for manual login.")
    add_crawl_arguments(parser)
    parser.add_argument("--date", help="Record date YYYY-MM-DD; defaults to UTC today.")
    parser.add_argument("--dry-run", action="store_true", help="只显示结果，不保存数据文档。")
    return parser


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
    args = _build_arg_parser().parse_args()
    try:
        if args.login:
            login()
        else:
            records = crawl_all(args.date, args.keyword, args.limit)
            if args.dry_run:
                for record in records:
                    print(
                        f"{record['keyword']} items={record['item_count']} "
                        f"sellers={record['seller_count']} avg_price={record['avg_price']:.2f}"
                    )
            else:
                print(f"数据文档：{save_records(records)}")
    except (CrawlError, OSError, ValueError, TypeError) as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from None
