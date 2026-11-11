"""Local workbench integration: persistence, filtering, HTTP boundaries and browser flows."""

import json
import threading
import time
from collections.abc import Iterator
from http.client import HTTPConnection
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright

import storage
from config import APP_TITLE, AUTHOR_HANDLE, CrawlProgress, CrawlRecord
from web_app import WorkbenchServer
from web_history import artifact, daily_history, run_history
from web_jobs import JobManager, parse_request


def row(keyword: str = "AI 副业", day: str = "2026-11-11", count: int = 2) -> CrawlRecord:
    return CrawlRecord(date=day, keyword=keyword, item_count=count, seller_count=1, avg_price=15.0)


def create_output(folder: Path, records: list[CrawlRecord], history: Path) -> Path:
    storage.save_records(records, folder, history_dir=history)
    suffix = records[0]["date"].replace("-", "_")
    for name in (
        f"card1_index_{suffix}.png",
        f"card2_daily_{suffix}.png",
        f"card3_weekly_{suffix}.png",
    ):
        Image.new("RGB", (32, 32), "#355c48").save(folder / name)
    (folder / "post.txt").write_text("测试发布文案", encoding="utf-8-sig")
    return folder


def wait_finished(manager: JobManager, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = manager.detail(job_id)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.01)
    pytest.fail("background job did not finish")


@pytest.fixture
def workbench(tmp_path: Path) -> Iterator[tuple[WorkbenchServer, JobManager, threading.Event, str]]:
    gate = threading.Event()
    history = tmp_path / "history"
    output = tmp_path / "output"
    storage.save_history([row("旧关键词", "2026-11-10", 5)], history_dir=history)
    create_output(output / "old-run", [row("旧关键词", "2026-11-10", 5)], history)

    def runner(target: str, keywords: list[str], limit: int, progress: Any) -> Path:
        for word in keywords:
            progress(
                CrawlProgress(
                    stage="crawling",
                    keyword=word,
                    page=1,
                    record=row(word, target),
                    items=[
                        {
                            "item_id": "1",
                            "seller_id": "s1",
                            "price": 10,
                            "title": "<img src=x onerror=alert(1)>",
                            "url": "https://www.goofish.com/item?id=1",
                        },
                        {
                            "item_id": "2",
                            "seller_id": "s1",
                            "price": 20,
                            "title": "用于回归测试的商品",
                            "url": "https://www.goofish.com/item?id=2",
                        },
                    ],
                )
            )
        assert gate.wait(30), "test did not release the worker"
        progress(CrawlProgress(stage="rendering", message="正在生成图片与文案"))
        return create_output(output / "new-run", [row(word, target) for word in keywords], history)

    manager = JobManager(tmp_path / "jobs", output, runner)
    server = WorkbenchServer(0, manager, history)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield server, manager, gate, url
    finally:
        gate.set()
        active = manager.active()
        if active:
            wait_finished(manager, active["id"])
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(
    url: str, path: str, data: Any = None, headers: dict[str, str] | None = None
) -> tuple[int, Any]:
    payload = None if data is None else json.dumps(data).encode()
    parts = urlsplit(url)
    assert parts.hostname is not None
    connection = HTTPConnection(parts.hostname, parts.port, timeout=5)
    try:
        connection.request("GET" if data is None else "POST", path, payload, headers or {})
        response = connection.getresponse()
        body = response.read()
        return response.status, json.loads(body) if body and path.startswith("/api/") else body
    finally:
        connection.close()


@pytest.mark.parametrize(
    "value",
    [
        [],
        {},
        {"keywords": []},
        {"keywords": [" "]},
        {"keywords": ["AI"], "limit": True, "date": "2026-11-11"},
        {"keywords": ["AI"], "limit": 0, "date": "2026-11-11"},
        {"keywords": ["AI"], "limit": 10, "date": "2026-02-30"},
        {"keywords": ["AI"], "limit": 10, "date": "20261111"},
    ],
)
def test_invalid_web_request_never_creates_job(value: Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        parse_request(value)


def test_daily_history_filters_paginates_and_rejects_corruption(tmp_path: Path) -> None:
    storage.save_history([row(f"AI {i}") for i in range(25)], history_dir=tmp_path)
    storage.save_history([row("other", "2026-11-10")], history_dir=tmp_path)
    first = daily_history("ai", "2026-11-11", "2026-11-11", root=tmp_path)
    assert first["total"] == 25 and len(first["rows"]) == 20 and first["pages"] == 2
    assert len(daily_history("ai", page=2, root=tmp_path)["rows"]) == 5
    assert first["summary"]["keywords"] == 25
    assert daily_history("missing", root=tmp_path)["total"] == 0
    with pytest.raises(ValueError, match="开始日期"):
        daily_history(start="2026-11-12", end="2026-11-11", root=tmp_path)
    (tmp_path / "2026-11-11.json").write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError, match="历史文档损坏"):
        daily_history(root=tmp_path)


def test_http_jobs_recover_progress_and_merge_old_snapshots(workbench: Any) -> None:
    server, manager, gate, url = workbench
    assert request(url, "/api/runs")[1]["total"] == 1
    body = {"keywords": [" AI 副业 ", "AI 副业"], "limit": 3, "date": "2026-11-11"}
    headers = {"Content-Type": "application/json", "X-AI-Index-Token": server.token}
    code, job = request(url, "/api/jobs", body, headers)
    assert code == 202 and job["keywords"] == ["AI 副业"]
    assert request(url, "/api/jobs", body, headers)[0] == 409
    assert request(url, "/api/active")[1]["job"]["id"] == job["id"]
    deadline = time.monotonic() + 3
    while not manager.detail(job["id"])["items"] and time.monotonic() < deadline:
        time.sleep(0.01)
    preview = request(url, f"/api/jobs/{job['id']}")[1]
    assert len(preview["items"]["AI 副业"]) == 2
    gate.set()
    assert wait_finished(manager, job["id"])["status"] == "succeeded"
    detail = request(url, f"/api/jobs/{job['id']}")[1]
    assert len(detail["files"]) == 6
    assert request(url, "/api/runs")[1]["total"] == 2  # new output isn't listed twice
    assert request(url, "/api/runs?keyword=AI")[1]["total"] == 1
    assert request(url, "/api/history?keyword=AI")[1]["total"] == 1
    assert request(url, "/files/new-run/post.txt")[0] == 200
    loaded = JobManager(manager.root, manager.output_root)
    assert loaded.detail(job["id"])["items"] == detail["items"]
    assert loaded.active() is None


def test_http_rejects_cross_origin_and_arbitrary_file_access(workbench: Any) -> None:
    server, _, _, url = workbench
    body = {"keywords": ["AI"], "limit": 1, "date": "2026-11-11"}
    headers = {"Content-Type": "application/json", "X-AI-Index-Token": server.token}
    assert request(url, "/api/jobs", body, {"Content-Type": "application/json"})[0] == 403
    assert request(url, "/api/jobs", body, {**headers, "Origin": "https://example.com"})[0] == 403
    assert request(url, "/api/config", headers={"Host": "example.com"})[0] == 403
    assert request(url, "/files/%2e%2e/records.json")[0] == 404
    assert request(url, "/files/old-run/../../config.py")[0] == 404
    assert request(url, "/files/old-run/cookies.json")[0] == 404
    assert request(url, "/data/browser-profile/Cookies")[0] == 404
    assert request(url, "/api/history?start=bad")[0] == 400
    assert request(url, "/api/history?page=0")[0] == 400
    assert request(url, "/api/history?page=no")[0] == 400
    assert request(url, "/api/jobs", {**body, "limit": -1}, headers)[0] == 400


def test_failed_and_interrupted_jobs_remain_queryable(tmp_path: Path) -> None:
    def failed(*args: Any, **kwargs: Any) -> Path:
        raise RuntimeError("登录已过期，请运行 login.bat")

    manager = JobManager(tmp_path / "jobs", tmp_path / "output", failed)
    job = manager.start({"keywords": ["AI"], "limit": 5, "date": "2026-11-11"})
    completed = wait_finished(manager, job["id"])
    assert completed["status"] == "failed" and "登录" in completed["error"]
    assert run_history(manager)["rows"][0]["status"] == "failed"
    completed["status"] = "running"
    (manager.root / f"{job['id']}.json").write_text(json.dumps(completed), encoding="utf-8")
    recovered = JobManager(manager.root, manager.output_root)
    assert recovered.detail(job["id"])["status"] == "interrupted"
    assert recovered.active() is None


def test_artifacts_reject_unlisted_existing_files(tmp_path: Path) -> None:
    create_output(tmp_path / "run", [row()], tmp_path / "history")
    (tmp_path / "run" / "private.txt").write_text("private", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        artifact("run", "private.txt", tmp_path)
    with pytest.raises(FileNotFoundError):
        artifact("..", "records.json", tmp_path)


def test_render_failure_keeps_output_link_without_duplicate_history(tmp_path: Path) -> None:
    output = tmp_path / "output"

    def failed_render(*args: Any, **kwargs: Any) -> Path:
        storage.save_records([row()], output / "partial", history_dir=tmp_path / "history")
        kwargs["progress"]({"stage": "rendering", "output_id": "partial"})
        raise RuntimeError("图片生成失败")

    manager = JobManager(tmp_path / "jobs", output, failed_render)
    job = manager.start({"keywords": ["AI 副业"], "limit": 2, "date": "2026-11-11"})
    completed = wait_finished(manager, job["id"])
    assert completed["status"] == "failed" and completed["output_id"] == "partial"
    assert run_history(manager)["total"] == 1
    assert artifact("partial", "records.json", output).is_file()


def test_browser_live_search_refresh_filters_details_and_mobile(
    workbench: Any, tmp_path: Path
) -> None:
    _, manager, gate, url = workbench
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1080})
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(url)
            expect(page.locator("#start-button")).to_be_enabled()
            expect(page.locator("#brand-title")).to_have_text(APP_TITLE)
            expect(page.locator("#author")).to_have_text(AUTHOR_HANDLE)
            expect(page.locator("#avatar")).to_have_text(AUTHOR_HANDLE[0].upper())
            page.locator("#keywords").fill("AI 副业")
            page.locator("#limit").fill("3")
            page.locator("#record-date").fill("2026-11-11")
            page.locator("#start-button").click()
            expect(page.locator(".item-card")).to_have_count(2)
            expect(page.locator("#start-button")).to_be_disabled()
            assert page.locator("#results img").count() == 0  # untrusted title is text, not markup
            page.reload()
            expect(page.locator(".item-card")).to_have_count(2)
            expect(page.locator("#start-button")).to_be_disabled()
            expect(page.locator("#keywords")).to_have_value("AI 副业")
            expect(page.locator("#limit")).to_have_value("3")
            gate.set()
            expect(page.locator("#job-status")).to_have_text("已完成", timeout=10000)
            expect(page.locator("#current-artifacts img")).to_have_count(3)
            page.screenshot(path=str(tmp_path / "web-search-desktop.png"), full_page=True)
            page.locator("#nav-history").click()
            expect(page.locator("#history-content tbody tr")).to_have_count(2)
            page.locator("#filter-keyword").fill("AI")
            page.locator("#filter-start").fill("2026-11-11")
            page.locator("#filter-end").fill("2026-11-11")
            page.locator("#filter-form button[type=submit]").click()
            expect(page.locator("#history-content tbody tr")).to_have_count(1)
            expect(page.locator("#history-content")).to_contain_text("AI 副业")
            page.locator("#reset-filters").click()
            page.locator("#mode-runs").click()
            expect(page.locator("#history-content tbody tr")).to_have_count(2)
            page.locator("#history-content button").first.click()
            expect(page.locator("#run-dialog")).to_be_visible()
            expect(page.locator("#dialog-content img")).to_have_count(3)
            page.locator("#close-dialog").click()
            page.locator("#filter-keyword").fill("不存在的词")
            page.locator("#filter-form button[type=submit]").click()
            expect(page.locator("#history-content")).to_contain_text("没有符合条件的记录")
            page.locator("#reset-filters").click()
            page.screenshot(path=str(tmp_path / "web-history-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path=str(tmp_path / "web-history-mobile.png"), full_page=True)
            page.locator("#nav-search").click()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert errors == []
            assert manager.active() is None
        finally:
            browser.close()
