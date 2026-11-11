"""Regression tests for authenticated search parsing and failed-batch behavior."""

import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

import crawler
import storage
from config import CrawlRecord


def payload(*rows):
    return {"ret": ["SUCCESS::调用成功"], "data": {"resultList": list(rows)}}


def item(item_id, seller, price):
    return {"data": {"id": item_id, "userId": seller, "price": price, "city": "杭州"}}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("￥1,299.90", 1299.9),
        ("1.2万", 12000),
        ([{"text": "¥"}, {"text": "29"}, {"text": ".90"}], 29.9),
        ("面议", 0),
        ("¥29包邮", 0),
        ("NaN", 0),
    ],
)
def test_price_display_formats(value, expected):
    assert crawler._parse_price(value) == expected


def test_current_formats_use_seller_ids_not_displayed_city():
    newer = {
        "data": {
            "item": {
                "main": {
                    "exContent": {"itemId": "b", "price": [{"text": "20"}], "area": "杭州"},
                    "clickParam": {"args": {"seller_id": "seller-b"}},
                }
            }
        }
    }
    items = crawler._parse_search_payload(payload(item("a", "seller-a", "10"), newer))
    result = crawler._aggregate_items(items + items, "AI 副业", "2026-11-11")
    assert result == {
        "date": "2026-11-11",
        "keyword": "AI 副业",
        "item_count": 2,
        "seller_count": 2,
        "avg_price": 15.0,
    }


@pytest.mark.parametrize(
    "data",
    [
        {"ret": ["FAIL_SYS_SESSION_EXPIRED"], "data": {}},
        {"ret": ["SUCCESS"], "data": {}},
        payload({"data": {"id": "a", "city": "杭州", "price": "10"}}),
        payload(item("a", "s", "面议")),
        payload({"unexpected": "markup changed"}),
    ],
)
def test_failed_or_unrecognized_response_never_becomes_zero(data):
    with pytest.raises(crawler.CrawlError):
        crawler._parse_search_payload(data)


def test_confirmed_empty_response_is_distinct_from_a_failure():
    assert crawler._parse_search_payload(payload()) == []
    assert crawler._page_access_error("非法访问 请使用正常浏览器")


@pytest.mark.asyncio
async def test_real_browser_observes_search_and_clicks_pagination(monkeypatch):
    monkeypatch.setattr(crawler, "CRAWL_DELAY_MIN", 0)
    monkeypatch.setattr(crawler, "CRAWL_DELAY_MAX", 0)
    html = """<html><body><script>
    function load(page) {
      fetch('/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/?page='+page).then(r=>r.json()).then(data => {
        if(!data.ret[0].startsWith('SUCCESS')) { setTimeout(()=>load(page), 50); return; }
        if(page===1) setTimeout(() => {
          let b=document.createElement('button');
          b.className='search-pagination-arrow-container--fixture';
          b.textContent='Next'; b.onclick=()=>load(2); document.body.append(b);
        }, 100);
      });
    }
    fetch('/h5/mtop.taobao.idlemtopsearch.pc.search.shade/1.0/').then(()=>load(1));
    </script></body></html>"""
    pages = []

    async def route_handler(route):
        if ".shade/" in route.request.url:
            await route.fulfill(
                content_type="application/json", body=json.dumps({"ret": ["SUCCESS"], "data": {}})
            )
            return
        if crawler.SEARCH_API_NAME in route.request.url:
            number = 2 if "page=2" in route.request.url else 1
            pages.append(number)
            if len(pages) == 1:
                await route.fulfill(
                    content_type="application/json",
                    body=json.dumps({"ret": ["RGV587_ERROR"], "data": {}}),
                )
                return
            rows = (
                [item("1", "s1", "10"), item("2", "s1", "20")]
                if number == 1
                else [item("2", "s1", "20"), item("3", "s2", "30")]
            )
            await route.fulfill(content_type="application/json", body=json.dumps(payload(*rows)))
        else:
            await route.fulfill(content_type="text/html", body=html)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        await context.route("https://www.goofish.com/**", route_handler)
        try:
            record = await crawler._fetch_keyword_async("AI & 教程", context, "2026-11-11")
            assert pages == [1, 1, 2]
            assert record["item_count"] == 3
            assert record["seller_count"] == 2
            assert record["avg_price"] == 20
        finally:
            await browser.close()


def test_invalid_batch_does_not_create_any_document(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(storage, "HISTORY_DIR", tmp_path / "history")
    good = crawler._aggregate_items([], "valid", "2026-11-11")
    bad: CrawlRecord = {**good, "keyword": "invalid", "item_count": -1}
    with pytest.raises(ValueError):
        crawler.save_records([good, bad], output_dir=tmp_path / "run")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit,mode,expected_pages,expected_count,expected_price",
    [
        (1, "normal", [1], 1, 10),
        (2, "normal", [1], 2, 15),
        (3, "normal", [1, 2], 3, 20),
        (4, "normal", [1, 2, 3], 4, 25),
        (100, "normal", [1, 2, 3], 5, 30),
        (100, "empty", [1, 2, 3], 3, 20),
        (100, "repeat", [1, 2], None, None),
    ],
)
async def test_user_limit_paginates_deduplicates_and_stops(
    monkeypatch, caplog, limit, mode, expected_pages, expected_count, expected_price
):
    monkeypatch.setattr(crawler, "CRAWL_DELAY_MIN", 0)
    monkeypatch.setattr(crawler, "CRAWL_DELAY_MAX", 0)
    html = """<html><body>
    <button class="search-pagination-arrow-container--fixture" onclick="load(++number)">Next</button>
    <script>
    let number = 1;
    function load(n) {
      fetch('/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/?page='+n).then(r=>r.json()).then(() => {
        document.querySelector('button').disabled = n >= 3;
      });
    }
    load(number);
    </script></body></html>"""
    pages = []

    async def route_handler(route):
        if crawler.SEARCH_API_NAME in route.request.url:
            number = int(route.request.url.rsplit("=", 1)[1])
            pages.append(number)
            rows = {
                1: [item("1", "s1", "10"), item("2", "s1", "20")],
                2: [item("2", "s1", "20"), item("3", "s2", "30")],
                3: [item("4", "s2", "40"), item("5", "s3", "50")],
            }[1 if mode == "repeat" else number]
            if mode == "empty" and number == 3:
                rows = []
            await route.fulfill(content_type="application/json", body=json.dumps(payload(*rows)))
        else:
            await route.fulfill(content_type="text/html", body=html)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        await context.route("https://www.goofish.com/**", route_handler)
        try:
            if mode == "repeat":
                with pytest.raises(crawler.CrawlError, match="同一批商品"):
                    await crawler._fetch_keyword_async(
                        "自定义 关键词", context, "2026-11-11", limit
                    )
            else:
                record = await crawler._fetch_keyword_async(
                    "自定义 关键词", context, "2026-11-11", limit
                )
                assert record["item_count"] == expected_count
                assert record["avg_price"] == expected_price
                assert record["seller_count"] == (
                    1 if expected_count <= 2 else 2 if expected_count <= 4 else 3
                )
                if expected_count < limit:
                    assert "搜索结果已结束" in caplog.text
            assert pages == expected_pages
        finally:
            await browser.close()
